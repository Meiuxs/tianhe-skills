"""审批链解析模块。

从 DMS 详情页的审批历史表中提取审批链信息：
提交时间、省总审批人/状态、采购审批人/状态、最终完成时间。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("dms_report")


async def extract_approval_info(page: Any) -> dict[str, str]:
    """从审批历史表提取完整的审批链信息。

    提取字段：提交时间、核价审批人/状态/时间、省总审批人/状态、采购审批人/状态、最终完成时间。

    Args:
        page: Playwright Page 对象（已导航到详情页）。

    Returns:
        dict 包含 9 个键：
            submit_time,
            negotiation_processor, negotiation_status, negotiation_time,
            province_processor, province_status,
            purchase_processor, purchase_status,
            final_approval_time。
    """
    result: dict[str, str] = {
        "submit_time": "--",
        "negotiation_processor": "--",
        "negotiation_status": "--",
        "negotiation_time": "--",
        "province_processor": "--",
        "province_status": "--",
        "purchase_processor": "--",
        "purchase_status": "--",
        "final_approval_time": "--",
    }
    try:
        tables = await page.locator("table").all()
        for table in tables:
            thead = table.locator("thead")
            if await thead.count() > 0 and "审批节点" in ((await thead.text_content()) or ""):
                body_table = table.locator("xpath=./following::table[.//tbody][1]")
                if await body_table.count() > 0:
                    for row in await body_table.locator("tbody tr").all():
                        cells = await row.locator("td").all()
                        if len(cells) >= 4:
                            node = ((await cells[0].text_content()) or "").strip()
                            processor = ((await cells[1].text_content()) or "").strip()
                            status_val = ((await cells[2].text_content()) or "").strip()
                            time_text = ((await cells[3].text_content()) or "").strip()

                            if "流程发起人" in node and "提交审核" in status_val:
                                result["submit_time"] = time_text
                            elif "项目管理部核价" in node:
                                result["negotiation_processor"] = processor
                                result["negotiation_status"] = status_val
                                result["negotiation_time"] = time_text
                            elif "省总" in node or "省公司" in node:
                                result["province_processor"] = processor
                                result["province_status"] = status_val
                            elif "采购" in node or "商务" in node:
                                result["purchase_processor"] = processor
                                result["purchase_status"] = status_val

                            if "通过" in status_val and time_text not in ("--", ""):
                                if result["final_approval_time"] in ("--", "") or time_text > result["final_approval_time"]:
                                    result["final_approval_time"] = time_text
                break
    except Exception as e:
        logger.debug("审批信息提取异常（不影响主流程）: %s", e)
    return result
