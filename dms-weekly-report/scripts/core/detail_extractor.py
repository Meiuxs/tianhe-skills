"""单条询价详情提取的编排层（orchestrator）。

协调 api_parser、html_parser、bom_parser、approval_parser 的工作。
从 dms_browser.py 拆分而来，包含：
  - fetch_detail_via_api: 直接调用 flowDetails API 获取详情
  - extract_detail_by_url: 提取单条询价详情（回退方案）
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
    DMS_URL, DMS_FLOW_DETAILS_API,
    NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT,
)

logger = logging.getLogger("dms_report")


async def extract_approval_info(page) -> dict[str, str]:
    """从审批历史表提取完整的审批链信息。"""
    from core.approval_parser import extract_approval_info as _extract_approval
    return await _extract_approval(page)


async def fetch_detail_via_api(context: BrowserContext, flow_id: str, flow_status: int = 1) -> dict | None:
    """直接调用 flowDetails API 获取流程详情。

    比页面拦截方式更快、更可靠，不依赖前端 SPA 行为。
    """
    from core.dms_browser import _get_api_headers

    headers = await _get_api_headers(context)
    if not headers:
        logger.warning("无法获取 API headers，跳过直接 API 调用: flow_id=%s", flow_id)
        return None

    try:
        resp = await context.request.post(
            DMS_FLOW_DETAILS_API,
            data={"bizFlowId": flow_id, "flowStatus": flow_status},
            headers=headers,
            timeout=NAV_TIMEOUT,
        )
        if not resp.ok:
            logger.warning("flowDetails API 请求失败: HTTP %d, flow_id=%s", resp.status, flow_id)
            return None
        body = await resp.json()
        if body.get("code") == 1:
            detail = body.get("data")
            if detail:
                logger.debug("直接 API 获取成功: flow_id=%s", flow_id)
                return detail
        logger.debug("flowDetails API 返回异常: code=%s, flow_id=%s", body.get("code"), flow_id)
        return None
    except Exception as e:
        logger.warning("flowDetails API 请求异常: %s, flow_id=%s", e, flow_id)
        return None


async def extract_detail_by_url(
    context: BrowserContext, flow_id: str, sem: asyncio.Semaphore,
    page=None, flow_status: int = 1,
):
    """提取单条询价详情。

    优先通过直接 API 调用获取数据，失败时回退到页面拦截方式。

    Args:
        page: 预创建的页面对象。仅在 API 调用失败时用于页面拦截回退。
        flow_status: 流程状态，用于 flowDetails API 请求参数。
    """
    from core.dms_browser import ensure_logged_in, FlowRecord
    from core.api_parser import (
        parse_json_date,
        fill_record_from_api,
        fill_record_from_html,
        fill_approval_from_dict,
    )
    from core.html_parser import extract_bom

    try:
        async with sem:
            # 优先方案：直接 API 调用
            api_data = await fetch_detail_via_api(context, flow_id, flow_status)

            if api_data:
                parse_json_date(api_data)
            else:
                # 回退方案：页面拦截
                logger.debug("直接 API 失败，回退到页面拦截: flow_id=%s", flow_id)
                api_data = await _fetch_via_page_interception(context, flow_id, page)
                if api_data:
                    parse_json_date(api_data)

            rec = FlowRecord(flow_id=flow_id)

            if api_data:
                fill_record_from_api(rec, api_data, flow_id)

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
                logger.debug("API 数据未获取到，回退到 HTML 解析: flow_id=%s", flow_id)
                html = await page.content()
                fill_record_from_html(rec, html)
                approval = await extract_approval_info(page)
                fill_approval_from_dict(rec, approval)

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


async def _fetch_via_page_interception(
    context: BrowserContext, flow_id: str, page=None,
) -> dict | None:
    """回退方案：通过页面拦截 flowDetails API 响应获取数据。"""
    from core.dms_browser import ensure_logged_in

    captured_data = None

    async def _capture_detail_api(response: Response) -> None:
        nonlocal captured_data
        if "flowDetails" not in response.url:
            return
        try:
            body = await response.json()
            detail = body.get("data")
            if detail:
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

    # 检查当前页面状态，如果是 SPA 内部导航，需要强制刷新
    current_url = getattr(page, "url", "") or ""
    if DMS_URL in current_url and "process_detail" in current_url:
        await page.goto("about:blank", timeout=NAV_TIMEOUT)
        await page.wait_for_timeout(100)

    await page.goto(url, timeout=NAV_TIMEOUT)

    if not captured_data:
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
        await page.wait_for_timeout(WAIT_SHORT)
    await ensure_logged_in(page, url)

    return captured_data
