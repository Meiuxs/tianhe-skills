"""下单检查模块。

通过 DMS 后端 API 批量拉取订单数据，在内存中匹配流程编号。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from column_definitions import ORDER_CHECK_EXTEND_DAYS
from core.dms_browser import get_access_token

logger = logging.getLogger("dms_report")

# 内部 API：DMS 订单历史查询接口，仅限公司内网访问
API_URL = "https://apigw.trinablue.com/dms-admin/orderHistory/getOrderHistoryList"
PAGE_SIZE = 500


async def fetch_ordered_flow_ids(
    context: Any,
    start_date: str,
    end_date: str,
) -> set[str]:
    """调用订单 API，返回所有已下单的流程编号集合。

    查询范围从 start_date 到 end_date + ORDER_CHECK_EXTEND_DAYS 天，
    支持分页拉取（每页 500 条）。使用 Playwright 内置的 APIRequestContext
    发送请求，不依赖第三方 HTTP 库。

    Args:
        context: Playwright BrowserContext
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD

    Returns:
        已下单的流程编号集合，API 异常时返回空集合并记录日志。
    """
    # 获取 token
    token = await get_access_token(context)
    if not token:
        logger.warning("未获取到 access_token，无法查询订单数据")
        return set()

    # 计算扩展后的结束日期
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=ORDER_CHECK_EXTEND_DAYS)
    extended_end = end_dt.strftime("%Y-%m-%d")

    logger.info("拉取订单数据：%s ~ %s（扩展 %d 天）", start_date, extended_end, ORDER_CHECK_EXTEND_DAYS)

    all_ids: set[str] = set()
    page_num = 1
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }

    MAX_API_RETRIES = 3
    API_RETRY_DELAY = 2.0

    while True:
        resp = None
        last_error = None
        for attempt in range(MAX_API_RETRIES):
            try:
                resp = await context.request.post(
                    API_URL,
                    data={
                        "createTime": start_date,
                        "toCreateTime": extended_end,
                        "pageNum": page_num,
                        "pageSize": PAGE_SIZE,
                    },
                    headers=headers,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < MAX_API_RETRIES - 1:
                    import asyncio
                    await asyncio.sleep(API_RETRY_DELAY * (2 ** attempt))
                    logger.debug("订单 API 第 %d 页请求重试 (%d/%d)", page_num, attempt + 1, MAX_API_RETRIES)

        if resp is None:
            logger.warning("订单 API 第 %d 页重试 %d 次后仍失败: %s", page_num, MAX_API_RETRIES, last_error)
            break

        try:
            data = await resp.json()
        except Exception as e:
            logger.warning("订单 API 第 %d 页响应解析失败: %s", page_num, e)
            break

        if data.get("code") != 1:
            logger.warning("订单 API 返回异常 code=%s: %s", data.get("code"), data.get("errMsg", ""))
            break

        records = data.get("data", {}).get("records", [])
        for record in records:
            flow_id = record.get("bizFlowId")
            if flow_id:
                all_ids.add(str(flow_id).strip())

        logger.debug("第 %d 页: 获取 %d 条", page_num, len(records))

        if len(records) < PAGE_SIZE:
            break

        page_num += 1

    logger.info("订单 API 拉取完成：共 %d 条已下单记录", len(all_ids))
    return all_ids


async def check_orders_parallel(
    context: Any,
    records: list,
    start_date: str,
    end_date: str,
) -> list:
    """并行检查所有记录的下单状态。

    Args:
        context: Playwright BrowserContext
        records: 包含 flow_id 属性的对象列表
        start_date: 查询开始日期
        end_date: 查询结束日期

    Returns:
        records（ordered 字段被更新）
    """
    logger.info("下单检查 %d 条（API 批量模式）...", len(records))

    ordered_ids = await fetch_ordered_flow_ids(context, start_date, end_date)

    for record in records:
        flow_id = getattr(record, "flow_id", "")
        record.ordered = "是" if flow_id in ordered_ids else "否"

    ordered_count = sum(1 for r in records if r.ordered == "是")
    logger.info("下单检查完成：%d 条已下单，%d 条未下单", ordered_count, len(records) - ordered_count)
    return records
