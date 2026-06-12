"""下单检查模块。

通过 DMS 后端 API 批量拉取订单数据，在内存中匹配流程编号。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from column_definitions import ORDER_CHECK_EXTEND_DAYS

logger = logging.getLogger("dms_report")

API_URL = "https://apigw.trinablue.com/dms-admin/orderHistory/getOrderHistoryList"
MAX_RETRIES = 2
PAGE_SIZE = 500


async def fetch_ordered_flow_ids(
    token: str,
    start_date: str,
    end_date: str,
) -> set[str]:
    """调用订单 API，返回所有已下单的流程编号集合。

    查询范围从 start_date 到 end_date + ORDER_CHECK_EXTEND_DAYS 天，
    支持分页拉取（每页 500 条）。

    Args:
        token: access_token（通过 dms_browser.get_access_token(context) 获取）
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD

    Returns:
        已下单的流程编号集合，API 异常时返回空集合并记录日志。
    """
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                resp = await client.post(
                    API_URL,
                    json={
                        "createTime": start_date,
                        "toCreateTime": extended_end,
                        "pageNum": page_num,
                        "pageSize": PAGE_SIZE,
                    },
                    headers=headers,
                )
                data = resp.json()

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

            except httpx.TimeoutException:
                logger.warning("订单 API 第 %d 页超时，终止分页", page_num)
                break
            except httpx.HTTPStatusError as e:
                logger.warning("订单 API HTTP 错误: %s", e)
                break
            except Exception as e:
                logger.warning("订单 API 请求异常: %s", e)
                break

    logger.info("订单 API 拉取完成：共 %d 条已下单记录", len(all_ids))
    return all_ids


async def check_orders_parallel(
    token: str,
    records: list,
    start_date: str,
    end_date: str,
) -> list:
    """并行检查所有记录的下单状态。

    Args:
        token: access_token
        records: 包含 flow_id 属性的对象列表
        start_date: 查询开始日期
        end_date: 查询结束日期

    Returns:
        records（ordered 字段被更新）
    """
    logger.info("下单检查 %d 条（API 批量模式）...", len(records))

    ordered_ids = await fetch_ordered_flow_ids(token, start_date, end_date)

    for record in records:
        flow_id = getattr(record, "flow_id", "")
        record.ordered = "是" if flow_id in ordered_ids else "否"

    ordered_count = sum(1 for r in records if r.ordered == "是")
    logger.info("下单检查完成：%d 条已下单，%d 条未下单", ordered_count, len(records) - ordered_count)
    return records
