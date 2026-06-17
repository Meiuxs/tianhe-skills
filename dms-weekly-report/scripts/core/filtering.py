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

_session_logged_in = False


def _retry_async_simple(max_retries: int = 2, base_delay: float = 1.0):
    """轻量级重试装饰器（避免从 dms_browser 导入 retry_async 导致循环依赖）。"""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (PlaywrightTimeout, OSError, asyncio.TimeoutError) as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning("%s 第 %d/%d 次失败: %s，%.1fs 后重试",
                                       func.__name__, attempt, max_retries, e, delay)
                        await asyncio.sleep(delay)
                    else:
                        logger.error("%s 重试 %d 次后仍失败: %s",
                                     func.__name__, max_retries, e)
            raise last_exc
        return wrapper
    return decorator


@_retry_async_simple(max_retries=2)
async def _navigate_to_process_center(page: Page) -> None:
    """导航到流程中心页面，处理登录重定向。"""
    global _session_logged_in
    from core.dms_browser import is_on_login_page, do_login

    target = f"{DMS_URL}/#/process/process_center"
    if not _session_logged_in and is_on_login_page(page.url):
        await do_login(page)
        _session_logged_in = True
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

        if not re.match(r"^\d{15,}$", flow_text):
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
            continue

        if flow_text in result.seen_ids:
            result.skipped_dup += 1
            logger.debug("跳过重复流程: %s", flow_text)
            continue

        result.add_flow_id(flow_text)

    return result
