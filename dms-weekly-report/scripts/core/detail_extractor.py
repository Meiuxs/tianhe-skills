"""单条询价详情提取的编排层（orchestrator）。

协调 api_parser、html_parser、bom_parser、approval_parser 的工作。
从 dms_browser.py 拆分而来，包含：
  - extract_detail_by_url: 提取单条询价详情
  - extract_approval_info: 从审批历史表提取完整的审批链信息
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import (
    BrowserContext,
    Response,
    TimeoutError as PlaywrightTimeout,
)
from playwright._impl._errors import TargetClosedError

from column_definitions import (
    DMS_URL,
    NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT,
)

logger = logging.getLogger("dms_report")


async def extract_approval_info(page) -> dict[str, str]:
    """从审批历史表提取完整的审批链信息。"""
    from core.approval_parser import extract_approval_info as _extract_approval
    return await _extract_approval(page)


async def extract_detail_by_url(
    context: BrowserContext, flow_id: str, sem: asyncio.Semaphore,
):
    """提取单条询价详情。

    流程：
      1. 打开页面，监听 flowDetails API 响应，捕获 jsonDate
      2. 从 API 数据解析项目信息、定价、审批链
      3. API 数据为空时回退到 HTML 解析
      4. BOM 数据来自 API（jsonDate.productInfo.bomList）
    """
    from core.dms_browser import ensure_logged_in, FlowRecord
    from core.api_parser import (
        parse_json_date,
        fill_record_from_api,
        fill_record_from_html,
        fill_approval_from_dict,
    )
    from core.html_parser import extract_bom

    page = None
    try:
        async with sem:
            page = await context.new_page()
            captured_data = None

            async def _capture_detail_api(response: Response) -> None:
                nonlocal captured_data
                if "flowDetails" not in response.url:
                    return
                try:
                    body = await response.json()
                    detail = body.get("data")
                    if detail:
                        parse_json_date(detail)
                        captured_data = detail
                        logger.debug("页面拦截到 flowDetails API: %s", response.url)
                        try:
                            page.remove_listener("response", _capture_detail_api)
                        except TargetClosedError:
                            pass
                except Exception as e:
                    logger.warning("拦截 flowDetails 响应失败: %s", e)

            page.on("response", _capture_detail_api)
            url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=1"
            await page.goto(url, timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
            await page.wait_for_timeout(WAIT_SHORT)
            await ensure_logged_in(page, url)

            api_data = captured_data

            # ===== 填充 record =====
            rec = FlowRecord(flow_id=flow_id)

            if api_data:
                fill_record_from_api(rec, api_data, flow_id)

                # API 返回的项目信息为空时，回退到 HTML 解析
                if (rec.project_name in ("--", "")
                        and rec.province in ("--", "")
                        and rec.salesperson in ("--", "")):
                    logger.warning(
                        "API 返回的项目信息为空（project_name=%s, province=%s, salesperson=%s），"
                        "回退到 HTML 解析补充: flow_id=%s",
                        rec.project_name, rec.province, rec.salesperson, flow_id,
                    )
                    html = await page.content()
                    fill_record_from_html(rec, html)
                    approval = await extract_approval_info(page)
                    fill_approval_from_dict(rec, approval)
            else:
                # API 完全失败，回退到 HTML 页面解析
                logger.debug("API 数据未获取到，回退到 HTML 解析: flow_id=%s", flow_id)
                html = await page.content()
                fill_record_from_html(rec, html)
                approval = await extract_approval_info(page)
                fill_approval_from_dict(rec, approval)

            # ===== BOM 提取（API 优先，HTML 回退） =====
            from core.bom_parser import calc_module_power, calc_inverter_power, calc_battery_capacity, build_remark
            bom_items = await extract_bom(page, api_data)
            rec.module_kw = calc_module_power(bom_items)
            rec.inverter_kw = calc_inverter_power(bom_items)
            rec.battery_kwh = calc_battery_capacity(bom_items)
            rec.remark = build_remark(bom_items)

            return rec
    except PlaywrightTimeout as e:
        logger.warning("%s: 页面操作超时 %s", flow_id, e)
        return None
    except TargetClosedError as e:
        logger.warning("%s: 页面已关闭 %s", flow_id, e)
        return None
    except Exception as e:
        logger.error("%s: 未预期的异常 %s (请报告 Bug)", flow_id, e, exc_info=True)
        return None
    finally:
        if page:
            await page.close()
