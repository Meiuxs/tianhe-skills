"""下单检查模块。

通过 DMS 后端 API 批量拉取订单数据，在内存中匹配流程编号。

架构定位：
  - fetch_ordered_flow_ids: 调用订单 API 分页拉取已下单流程编号集合
  - check_orders_parallel:  遍历询价记录，标注 ordered 字段

使用场景：
  询价详情提取完成后，调用 check_orders_parallel 批量标记"是否已下单"。
  日期范围 = start_date ~ end_date + ORDER_CHECK_EXTEND_DAYS 天，
  扩展天数覆盖审批周期，避免漏掉已下单但未在周内完成的流程。

TODO: 后续可能恢复使用。当前已替换为项目管理部核价审批有效性检查。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from column_definitions import ORDER_CHECK_EXTEND_DAYS, NAV_TIMEOUT
from core.dms_browser import get_access_token

logger = logging.getLogger("dms_report")

# ==================== API 配置 ====================

API_URL = "https://apigw.trinablue.com/dms-admin/orderHistory/getOrderHistoryList"
PAGE_SIZE = 500
"""每页请求条数，与后端保持一致。"""

MAX_API_RETRIES = 3
"""单页请求最大重试次数。"""

API_RETRY_DELAY = 2.0
"""重试基础延迟（秒），实际使用指数退避。"""

MAX_CONCURRENT_PAGES = 10
"""并发拉取页面的最大并发数，避免对服务器造成过大压力。"""


async def _fetch_one_page(
    context: Any, page_num: int, start_date: str, extended_end: str,
    headers: dict[str, str],
) -> tuple[list[str], int, int] | None:
    """拉取单页订单数据，返回 (flow_id 列表, total, pages)，失败返回 None。

    每次请求最多重试 MAX_API_RETRIES 次，使用指数退避策略。

    Args:
        context: Playwright BrowserContext
        page_num: 页码（从 1 开始）
        start_date: 创建开始日期（YYYY-MM-DD）
        extended_end: 创建结束日期（已扩展的天数，YYYY-MM-DD）
        headers: 请求头，至少包含 Authorization

    Returns:
        (flow_id 列表, total) 元组，API 调用失败或网络异常时返回 None。
    """
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
                timeout=NAV_TIMEOUT,
            )
            data = await resp.json()
            if data.get("code") != 1:
                logger.warning("订单 API 第 %d 页返回异常 code=%s: %s",
                               page_num, data.get("code"), data.get("errMsg", ""))
                return None
            resp_data = data.get("data") or {}
            records = resp_data.get("records", [])
            total = resp_data.get("total", 0)
            pages = resp_data.get("pages", 0)
            ids = [str(r["bizFlowId"]).strip() for r in records if r.get("bizFlowId")]
            logger.debug("第 %d 页: 获取 %d 条, total=%d, pages=%d", page_num, len(records), total, pages)
            return ids, total, pages
        except Exception as e:
            if attempt < MAX_API_RETRIES - 1:
                await asyncio.sleep(API_RETRY_DELAY * (2 ** attempt))
                logger.debug("订单 API 第 %d 页请求重试 (%d/%d)", page_num, attempt + 1, MAX_API_RETRIES)
            else:
                logger.warning("订单 API 第 %d 页重试 %d 次后仍失败: %s", page_num, MAX_API_RETRIES, e)
    return None


async def fetch_ordered_flow_ids(
    context: Any,
    start_date: str,
    end_date: str,
) -> tuple[set[str], int]:
    """调用订单 API，返回 (已下单流程编号集合, API total)。

    分页拉取策略：
      1. 先拉第 1 页，从返回的 data.pages 获取后端计算的总页数
      2. 直接并发拉取第 2 ~ pages 页，避免无效请求
      3. 使用 Semaphore 限流并发（最多 MAX_CONCURRENT_PAGES）

    容错：
      - 单页失败会重试 MAX_API_RETRIES 次，仍失败则跳过并记录日志
      - 不会因某一页失败而中断整个拉取流程

    Args:
        context: Playwright BrowserContext
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD

    Returns:
        (已下单的流程编号集合, API total)，全部失败时返回 (空集合, 0)。
    """
    token = await get_access_token(context)
    if not token:
        logger.warning("未获取到 access_token，无法查询订单数据")
        return set(), 0

    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=ORDER_CHECK_EXTEND_DAYS)
    extended_end = end_dt.strftime("%Y-%m-%d")
    logger.info("拉取订单数据：%s ~ %s（扩展 %d 天）", start_date, extended_end, ORDER_CHECK_EXTEND_DAYS)

    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }

    # 第 1 页：获取 total 和 pages（后端计算的总页数）
    first_page_result = await _fetch_one_page(context, 1, start_date, extended_end, headers)
    if first_page_result is None:
        return set(), 0

    first_page_ids, api_total, api_pages = first_page_result
    all_ids = set(first_page_ids)
    logger.info("订单 API 第 1 页: total=%d, pages=%d, 本页 %d 条", api_total, api_pages, len(first_page_ids))

    if api_pages <= 1:
        logger.info("订单 API 拉取完成：共 %d 条已下单记录（API total=%d, pages=%d）",
                    len(all_ids), api_total, api_pages)
        return all_ids, api_total

    # 后端给定了 pages，直接并发拉取第 2 ~ pages 页
    pages_to_fetch = list(range(2, api_pages + 1))
    logger.info("订单 API 共 %d 页，开始拉取第 2-%d 页（共 %d 页）",
                api_pages, api_pages, len(pages_to_fetch))

    sem = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

    async def _fetch_with_semaphore(page_num: int) -> tuple[list[str], int, int] | None:
        async with sem:
            return await _fetch_one_page(context, page_num, start_date, extended_end, headers)

    results = await asyncio.gather(
        *[_fetch_with_semaphore(p) for p in pages_to_fetch]
    )

    for p, page_result in zip(pages_to_fetch, results):
        if page_result is None:
            logger.warning("第 %d 页拉取失败，跳过", p)
            continue
        page_ids, _, _ = page_result
        all_ids.update(page_ids)
        logger.debug("第 %d 页: 获取 %d 条, 累计 %d 条", p, len(page_ids), len(all_ids))

    logger.info("订单 API 拉取完成：共 %d 条已下单记录（API total=%d, pages=%d）",
                len(all_ids), api_total, api_pages)
    return all_ids, api_total


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

    ordered_ids, _ = await fetch_ordered_flow_ids(context, start_date, end_date)
    ordered_set = ordered_ids  # fetch_ordered_flow_ids 返回 (set[str], int)

    for record in records:
        flow_id = getattr(record, "flow_id", "")
        record.ordered = "是" if flow_id in ordered_set else "否"

    ordered_count = sum(1 for r in records if r.ordered == "是")
    logger.info("下单检查完成：%d 条已下单，%d 条未下单", ordered_count, len(records) - ordered_count)
    return records
