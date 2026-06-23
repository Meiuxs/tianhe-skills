"""流程筛选的 DOM 操作（翻页、表格解析）。

从 dms_browser.py 拆分而来，包含：
  - _navigate_to_process_center: 导航到流程中心页面
  - _process_table_rows: 处理当前页面的表格行，提取有效流程编号
"""

from __future__ import annotations

import re
import logging
from functools import wraps

from column_definitions import (
    DMS_URL,
    NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT,
    TARGET_FLOW_TYPE,
)
from playwright.async_api import Page

logger = logging.getLogger("dms_report")

# 从独立工具模块导入 retry_async（避免与 dms_browser 循环依赖）
from core._utils import retry_async

# 导入流程编号正则常量
from column_definitions import FLOW_ID_PATTERN


@retry_async(max_retries=2)
async def _navigate_to_process_center(page: Page) -> None:
    """导航到流程中心页面，处理登录重定向。

    每次实际检查页面 URL 状态，不依赖模块级全局标志。
    """
    from core.dms_browser import is_on_login_page, do_login

    target = f"{DMS_URL}/#/process/process_center"
    # 每次都检查当前 URL，而非依赖缓存的登录状态
    if is_on_login_page(page.url):
        await do_login(page)
    if page.url != target:
        await page.goto(target, timeout=NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
    await page.wait_for_timeout(WAIT_SHORT)


async def _process_table_rows(
    page: Page,
    result,  # TableProcessResult — 使用 Any 避免循环导入
) -> "TableProcessResult":
    """处理当前页面的表格行，提取有效流程编号。

    每行至少需要 2 列（流程编号 + 流程类型）才能被视为有效。
    """
    from core.dms_browser import SELECTORS

    rows = await page.locator(SELECTORS["table_tbody"]).all()
    if not rows:
        rows = await page.locator(f"{SELECTORS['table_body']} tr").all()
    logger.debug("找到 %d 行", len(rows))

    for row in rows:
        cell_texts = await row.locator("td").all_text_contents()
        if len(cell_texts) < 2:
            logger.debug("跳过列数不足的行: %d 列", len(cell_texts))
            continue

        cell_texts = [t.strip().strip('"') for t in cell_texts]
        flow_text = cell_texts[0] if cell_texts else ""

        if not re.match(FLOW_ID_PATTERN, flow_text):
            logger.debug("跳过非数字流程编号: %s", flow_text)
            continue

        flow_type = cell_texts[1] if len(cell_texts) > 1 else ""
        if TARGET_FLOW_TYPE not in flow_type:
            result.skipped_wrong_type += 1
            logger.debug("跳过非目标流程类型: %s (%s)", flow_text, flow_type)
            continue

        status_text = ""
        for t in cell_texts[-3:]:
            if any(k in t for k in ("作废", "驳回", "通过", "审批")):
                status_text = t
                break

        if "作废" in status_text:
            result.skipped_invalid += 1
            logger.debug("跳过作废流程: %s", flow_text)
            # 默认包含作废流程，不再跳过
            # continue

        if flow_text in result.seen_ids:
            result.skipped_dup += 1
            logger.debug("跳过重复流程: %s", flow_text)
            continue

        result.add_flow_id(flow_text)

    return result
