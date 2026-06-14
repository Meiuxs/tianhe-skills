"""DMS 浏览器自动化模块。

包含 Playwright 浏览器操作的核心功能：
  - 数据类: FlowRecord, TableProcessResult
  - 登录: is_on_login_page, ensure_logged_in, do_login
  - 筛选: _navigate_to_process_center, _process_table_rows, filter_and_get_flow_ids
  - 提取: _extract_from_html, _split_agent, _extract_bom, extract_detail_by_url, extract_all_parallel
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from column_definitions import (
    DMS_URL, LOGIN_CHECK_DOMAIN,
    NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT, WAIT_MEDIUM,
    MAX_RETRIES, RETRY_BASE_DELAY,
)

USER_DATA_DIR = Path.home() / ".dms_browser_data"
from dms_credentials import get_credentials as _get_dms_credentials, source_label
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright._impl._errors import TargetClosedError

logger = logging.getLogger("dms_report")


# ==================== 数据类 ====================


@dataclass
class FlowRecord:
    """提取到的单条询价记录——最终写入 Excel 的一行数据。"""
    flow_id: str = ""
    project_name: str = "--"
    agent_code: str = "--"
    agent_name: str = "--"
    province: str = "--"
    salesperson: str = "--"
    module_kw: float = 0.0
    inverter_kw: float = 0.0
    battery_kwh: float = 0.0
    unit_price: str = "--"
    total_price: str = "--"
    submit_time: str = "--"
    remark: str = "无"
    ordered: str = "否"
    province_processor: str = "--"
    province_status: str = "--"
    purchase_processor: str = "--"
    purchase_status: str = "--"
    final_approval_time: str = "--"


@dataclass
class TableProcessResult:
    """表格翻页处理结果。"""
    flow_ids: list[str] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    skipped_wrong_type: int = 0
    skipped_invalid: int = 0
    skipped_dup: int = 0
    valid_rows: int = 0


# ==================== 重试装饰器 ====================


def retry_async(max_retries: int = MAX_RETRIES, base_delay: float = RETRY_BASE_DELAY):
    """异步函数重试装饰器，指数退避。"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
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


# ==================== 工具函数 ====================


def is_on_login_page(url: str) -> bool:
    """判断当前 URL 是否为登录页面。"""
    return LOGIN_CHECK_DOMAIN in url


async def ensure_logged_in(page: Any, target_url: str) -> None:
    """如果当前在登录页面则自动登录，然后导航到目标 URL。"""
    if is_on_login_page(page.url):
        await do_login(page)
        await page.goto(target_url, timeout=NAV_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)


async def get_access_token(context: Any) -> str | None:
    """从浏览器 cookie 中提取 DMS 的 access_token。

    登录后 DMS 系统会在 cookie 中设置 dms_admin_token，
    该 token 用于后端 API 调用的 Authorization 头。

    Args:
        context: Playwright BrowserContext

    Returns:
        access_token 字符串，未登录或无 cookie 时返回 None。
    """
    cookies = await context.cookies()
    for c in cookies:
        if c["name"] == "dms_admin_token":
            return c["value"]
    return None


def get_week_range(weeks_ago: int = 0) -> tuple[str, str]:
    """计算指定周的开始（周一）和结束日期。"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    end = today if weeks_ago == 0 else monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _get_credentials() -> tuple[str, str]:
    """从共享模块读取登录凭据。"""
    def _log_source(source: str) -> None:
        logger.info("从 %s 加载登录凭据", source_label(source))
    return _get_dms_credentials(on_source=_log_source)


# ==================== 登录 ====================


@retry_async(max_retries=MAX_RETRIES)
async def do_login(page: Any) -> None:
    """自动填写登录表单并提交。"""
    username, password = _get_credentials()
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
        if is_on_login_page(page.url):
            raise RuntimeError("登录失败，请检查账号密码")


# ==================== 筛选 ====================


@retry_async(max_retries=2)
async def _navigate_to_process_center(page: Any) -> None:
    """导航到流程中心页面，处理登录重定向。"""
    await page.goto(f"{DMS_URL}/#/process/process_center", timeout=NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
    await page.wait_for_timeout(WAIT_SHORT)
    await ensure_logged_in(page, f"{DMS_URL}/#/process/process_center")


async def _process_table_rows(
    page: Any,
    result: TableProcessResult,
) -> TableProcessResult:
    """处理当前页面的表格行，提取有效流程编号。"""
    rows = await page.locator("table.el-table__body").first.locator("tbody tr").all()
    logger.debug("找到 %d 行", len(rows))

    page_skipped_wrong_type = 0
    page_skipped_invalid = 0
    page_skipped_dup = 0
    page_valid = 0

    for row in rows:
        cells = await row.locator("td").all()
        if len(cells) < 2:
            continue
        cell_texts = [((await c.text_content()) or "").strip().strip('"') for c in cells]
        flow_text = cell_texts[0] if cell_texts else ""

        # 流程编号未匹配，跳过
        if not re.match(r"^\d{15,}$", flow_text):
            continue

        # 按流程类型筛选：仅保留"户用小型工商业询价流程"
        if len(cell_texts) >= 2 and "户用小型工商业询价流程" not in cell_texts[1]:
            page_skipped_wrong_type += 1
            result.skipped_wrong_type += 1
            logger.debug("跳过非目标流程类型: %s (%s)", flow_text, cell_texts[1] if len(cell_texts) > 1 else "?")
            continue

        status_text = ""
        for t in cell_texts[-3:]:
            if any(k in t for k in ("作废", "驳回", "通过", "审批")):
                status_text = t
                break

        if "作废" in status_text:
            page_skipped_invalid += 1
            result.skipped_invalid += 1
            logger.debug("跳过作废流程: %s", flow_text)
            continue

        if flow_text in result.seen_ids:
            page_skipped_dup += 1
            result.skipped_dup += 1
            logger.debug("跳过重复流程: %s", flow_text)
            continue

        page_valid += 1
        result.valid_rows += 1
        result.seen_ids.add(flow_text)
        result.flow_ids.append(flow_text)

    logger.info("有效行: %d 行（去重后 %d 个流程）", result.valid_rows, len(result.flow_ids))

    return result


async def filter_and_get_flow_ids(page: Any, start_date: str, end_date: str) -> TableProcessResult:
    """在已办流程中按日期筛选，返回有效流程编号列表（支持多页翻页）。"""
    logger.info("筛选日期范围: %s ~ %s", start_date, end_date)
    await _navigate_to_process_center(page)

    await page.get_by_role("menuitem", name="已办流程").click()
    await page.wait_for_timeout(WAIT_SHORT)
    await page.get_by_placeholder("开始时间").fill(start_date)
    await page.get_by_placeholder("结束时间").fill(end_date)
    await page.get_by_role("button", name="查询").click()
    await page.wait_for_timeout(WAIT_MEDIUM)

    # 读取总记录数
    total_el = page.locator("text=/共.*条记录/")
    if await total_el.count() == 0:
        logger.info("未找到分页信息，可能无记录")
        return []

    total_text = await total_el.first.text_content() or ""
    total_match = re.search(r"共\s*(\d+)\s*条", total_text)
    total = int(total_match.group(1)) if total_match else 0
    logger.info("共 %d 条记录", total)
    if total == 0:
        return []

    PAGE_SIZE = 10
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    logger.info("分页: %d 条/页，共 %d 页", PAGE_SIZE, total_pages)

    result = TableProcessResult()

    # 处理第 1 页
    result = await _process_table_rows(page, result)

    # 翻页处理后续页面
    for page_num in range(2, total_pages + 1):
        logger.debug("翻到第 %d 页", page_num)
        try:
            await page.locator(".el-pager").get_by_text(str(page_num), exact=True).click()
            # 等待表格新数据渲染完成，避免新旧数据重叠导致重复计数
            await page.locator("table.el-table__body tbody tr").first.wait_for(
                state="visible", timeout=LOAD_TIMEOUT
            )
            await page.wait_for_timeout(WAIT_MEDIUM)
        except PlaywrightTimeout:
            logger.warning("翻到第 %d 页失败，终止翻页", page_num)
            break

        result = await _process_table_rows(page, result)

    logger.info("有效行: %d 行（去重后 %d 个流程）", result.valid_rows, len(result.flow_ids))
    if result.skipped_wrong_type:
        logger.info("跳过非目标流程: %d 条", result.skipped_wrong_type)
    if result.skipped_invalid:
        logger.info("跳过作废流程: %d 条", result.skipped_invalid)
    if result.skipped_dup:
        logger.info("跳过重复流程: %d 条", result.skipped_dup)
    return result


# ==================== HTML 提取工具 ====================


def _extract_from_html(html: str, label: str) -> str:
    """从 HTML 中按字段 label 提取值。"""
    # 尝试直接匹配: label: </th><td>value
    m = re.search(rf'{re.escape(label)}[:\s]*</[^>]+>\s*<[^>]*>([^<]+)', html)
    if m:
        return m.group(1).strip()
    # 尝试嵌套匹配: label: </th><th><div>value
    m = re.search(rf'{re.escape(label)}[:\s]*</[^>]+>\s*<[^>]+>\s*<[^>]*>([^<]+)', html)
    if m:
        return m.group(1).strip()
    return "--"


def _split_agent(agent_raw: str) -> tuple[str, str]:
    """拆分代理商字段为 编号 和 名称。"""
    if not agent_raw or agent_raw == "--":
        return "--", "--"
    parts = agent_raw.split(" ", 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (agent_raw.strip(), "--")


# ==================== BOM 提取（Playwright 操作部分） ====================


async def _extract_bom(page: Any) -> list[Any]:
    """从详情页提取 BOM 清单。

    支持多个 el-table 容器（组件表 + 逆变器/电池表分开的场景）。
    通过 body table text content 去重，避免同一个表被重复处理。

    Returns:
        BOMItem 列表（BOMItem 定义在 bom_parser 模块）。
    """
    from core.bom_parser import BOMItem

    items: list[BOMItem] = []
    processed_tables: set[str] = set()
    try:
        tables = await page.locator("table").all()
        for table in tables:
            thead = table.locator("thead")
            if await thead.count() > 0 and "物料编号" in ((await thead.text_content()) or ""):
                body_table = table.locator("xpath=./following::table[.//tbody][1]")
                if await body_table.count() > 0:
                    body_text = (await body_table.text_content()) or ""
                    table_fingerprint = body_text.strip()[:200]
                    if table_fingerprint in processed_tables:
                        logger.debug("跳过已处理的 BOM 表（指纹重复）")
                        continue
                    processed_tables.add(table_fingerprint)

                    for row in await body_table.locator("tbody tr").all():
                        cells = await row.locator("td").all()
                        if len(cells) >= 4:
                            code = ((await cells[0].text_content()) or "").strip().strip('"')
                            name = ((await cells[1].text_content()) or "").strip()
                            qty_str = ((await cells[2].text_content()) or "").strip().strip('"')
                            unit = ((await cells[3].text_content()) or "").strip()
                            if not code or not name:
                                continue
                            try:
                                qty = int(qty_str)
                            except ValueError:
                                try:
                                    qty = float(qty_str)
                                except ValueError:
                                    continue
                            items.append(BOMItem(code=code, name=name, qty=qty, unit=unit))
    except Exception as e:
        logger.warning("BOM 提取异常: %s", e)

    # 去重（基于物料编号）
    seen: set[str] = set()
    deduped: list[BOMItem] = []
    for item in items:
        if item.code not in seen:
            seen.add(item.code)
            deduped.append(item)
    return deduped


# ==================== 审批信息提取（Playwright 操作部分） ====================


async def _extract_approval_info(page: Any) -> dict[str, str]:
    """从审批历史表提取完整的审批链信息。"""
    from core.approval_parser import extract_approval_info as _extract_approval
    return await _extract_approval(page)


# ==================== 详情提取 ====================


async def extract_detail_by_url(
    context: Any, flow_id: str, sem: asyncio.Semaphore,
) -> FlowRecord | None:
    """在新 Tab 中打开详情页提取单条询价数据。"""
    from core.bom_parser import calc_module_power, calc_inverter_power, calc_battery_capacity, build_remark

    async with sem:
        page = await context.new_page()
        url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=1"
        try:
            await page.goto(url, timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
            await page.wait_for_timeout(WAIT_SHORT)

            await ensure_logged_in(page, url)

            html = await page.content()
            rec = FlowRecord(flow_id=flow_id)

            rec.project_name = _extract_from_html(html, "项目名称")
            agent_raw = _extract_from_html(html, "代理商")
            rec.agent_code, rec.agent_name = _split_agent(agent_raw)
            rec.province = _extract_from_html(html, "省公司")
            rec.salesperson = _extract_from_html(html, "业务员")
            rec.unit_price = _extract_from_html(html, "瓦单价(元/瓦)")
            rec.total_price = _extract_from_html(html, "总价(元)")
            bom_items = await _extract_bom(page)
            rec.module_kw = calc_module_power(bom_items)
            rec.inverter_kw = calc_inverter_power(bom_items)
            rec.battery_kwh = calc_battery_capacity(bom_items)
            rec.remark = build_remark(bom_items)
            approval = await _extract_approval_info(page)
            rec.submit_time = approval["submit_time"]
            rec.province_processor = approval["province_processor"]
            rec.province_status = approval["province_status"]
            rec.purchase_processor = approval["purchase_processor"]
            rec.purchase_status = approval["purchase_status"]
            rec.final_approval_time = approval["final_approval_time"]

            return rec
        except (PlaywrightTimeout, OSError, ValueError, AttributeError) as e:
            logger.warning("%s: 提取异常 %s", flow_id, e)
            return None
        except Exception as e:
            logger.error("%s: 未预期的异常 %s (请报告 Bug)", flow_id, e, exc_info=True)
            return None
        finally:
            await page.close()


async def extract_all_parallel(
    context: Any, flow_ids: list[str], workers: int,
) -> list[FlowRecord]:
    """并行提取所有流程详情。"""
    total = len(flow_ids)
    logger.info("并行提取 %d 条（%d 并发）...", total, workers)
    sem = asyncio.Semaphore(workers)
    tasks = [extract_detail_by_url(context, fid, sem) for fid in flow_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    records: list[FlowRecord] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("[%d/%d] %s: 异常 %s", i + 1, total, flow_ids[i], result)
        elif isinstance(result, FlowRecord):
            records.append(result)
        # None 跳过（已记录）
    logger.info("提取完成: %d/%d 条成功", len(records), total)
    return records
