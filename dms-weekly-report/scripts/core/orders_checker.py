"""下单检查模块。

在 DMS 订单页面搜索流程编号是否已下单。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from column_definitions import DMS_URL, NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT, WAIT_MEDIUM, MAX_RETRIES
from dms_credentials import get_credentials as _get_dms_credentials, source_label

logger = logging.getLogger("dms_report")


def retry_async(max_retries: int = MAX_RETRIES, base_delay: float = 2.0):
    """异步函数重试装饰器，指数退避。"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            from playwright.async_api import TimeoutError as PlaywrightTimeout
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (PlaywrightTimeout, OSError, RuntimeError) as e:
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


async def ensure_logged_in(page: Any, target_url: str) -> None:
    """如果当前在登录页面则自动登录，然后导航到目标 URL。"""
    from column_definitions import LOGIN_CHECK_DOMAIN

    if LOGIN_CHECK_DOMAIN in page.url:
        await _do_login(page)
        await page.goto(target_url, timeout=NAV_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)


async def _do_login(page: Any) -> None:
    """自动填写登录表单并提交。"""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    username, password = _get_dms_credentials()
    logger.info("正在登录...")
    await page.wait_for_selector("#form_item_account", state="visible", timeout=NAV_TIMEOUT)
    await page.locator("#form_item_account").fill(username)
    await page.locator("#form_item_password").fill(password)
    await page.get_by_role("button", name="登 录").click()
    try:
        await page.wait_for_url(f"{DMS_URL}/**", timeout=NAV_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
        masked = username[:3] + "***" + (username[username.index("@"):] if "@" in username else "")
        logger.info("登录成功 (%s)", masked)
    except PlaywrightTimeout:
        if DMS_URL.split("//")[1].split("/")[0] in page.url:
            pass
        else:
            raise RuntimeError("登录失败，请检查账号密码")


@retry_async(max_retries=MAX_RETRIES)
async def search_order_for_flow(context: Any, flow_id: str, sem: asyncio.Semaphore) -> str:
    """在订单页面搜索流程编号是否已下单。成功时返回 '是'/'否'。"""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    async with sem:
        page = await context.new_page()
        try:
            await page.goto(f"{DMS_URL}/#/orderManage/orderHistory", timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
            await ensure_logged_in(page, f"{DMS_URL}/#/orderManage/orderHistory")
            await page.wait_for_timeout(WAIT_MEDIUM)

            flow_label = page.get_by_text("流程编号", exact=True)
            parent = flow_label.locator("..")
            search = parent.locator("input").first
            await search.fill(flow_id)
            await page.get_by_role("button", name="查询").first.click()
            await page.wait_for_timeout(WAIT_MEDIUM)

            no_data = page.locator("text=暂无数据")
            if await no_data.count() > 0:
                try:
                    if await no_data.first.is_visible(timeout=WAIT_SHORT):
                        return "否"
                except PlaywrightTimeout:
                    pass
                return "否"
            return "是"
        finally:
            await page.close()


async def check_single_order(context: Any, flow_id: str, sem: asyncio.Semaphore) -> str:
    """在订单页面搜索流程编号是否已下单（带重试），重试耗尽时返回 '检查失败'。"""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    try:
        return await search_order_for_flow(context, flow_id, sem)
    except (PlaywrightTimeout, OSError, RuntimeError) as e:
        logger.error("%s: 下单检查重试 %d 次后仍失败: %s", flow_id, MAX_RETRIES, e)
        return "检查失败"


async def check_orders_parallel(
    context: Any, records: list, workers: int,
) -> list:
    """并行检查所有记录的下单状态。

    Args:
        context: Playwright BrowserContext
        records: 包含 flow_id 属性的对象列表
        workers: 并发数

    Returns:
        records（ordered 字段被更新）
    """
    logger.info("并行检查下单状态 %d 条（%d 并发）...", len(records), workers)
    sem = asyncio.Semaphore(workers)
    tasks = [check_single_order(context, r.flow_id, sem) for r in records]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, (record, result) in enumerate(zip(records, results)):
        record.ordered = result if isinstance(result, str) else "检查失败"
        status_map = {"是": "已下单", "否": "未下单", "检查失败": "检查失败"}
        status = status_map.get(record.ordered, "检查失败")
        logger.info("[%d/%d] %s: %s", i + 1, len(records), record.flow_id, status)
    return records
