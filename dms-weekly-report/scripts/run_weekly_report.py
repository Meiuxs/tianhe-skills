#!/usr/bin/env python3
"""DMS 非标询价周报自动化脚本（并行版 v2）。

一键完成：登录 → 筛选本周已办询价 → 多Tab并行提取详情 → 多Tab并行检查下单 → 生成Excel。

用法：
    python run_weekly_report.py [--headless] [--weeks N] [--workers N] [--verbose]
    python run_weekly_report.py --start-date 2026-05-01 --end-date 2026-05-31 [--headless]
"""

from __future__ import annotations

import io
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright._impl._errors import TargetClosedError

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402
from dms_credentials import get_credentials as _get_dms_credentials, source_label  # noqa: E402

# ==================== 日志配置 ====================

logger = logging.getLogger("dms_report")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(_handler)


def configure_logging(verbose: bool = False) -> None:
    """根据 --verbose 标志配置日志级别。"""
    # 修复 Windows 终端中文乱码（Git Bash 等 UTF-8 终端）
    if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding and sys.stdout.encoding.upper() not in ("UTF-8", "UTF-8-SIG"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    _handler.setLevel(level)


# ==================== 配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"
LOGIN_CHECK_DOMAIN = "iauth.trinapower.com"
USER_DATA_DIR = Path.home() / ".dms_browser_data"

# Excel 样式常量
HEADERS: list[str] = [
    "流程编号", "项目名称", "代理商编号", "代理商名称", "省公司", "业务员",
    "组件总功率(kW)", "逆变器总功率(kW)", "电池总容量(kWh)",
    "瓦单价(元/瓦)", "总价(元)", "流程发起人提交审核时间", "备注", "是否下单",
]
THIN_BORDER = Border(
    left=Side("thin"), right=Side("thin"),
    top=Side("thin"), bottom=Side("thin"),
)
BLUE_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
WHITE_BOLD = Font(bold=True, size=11, color="FFFFFF")
HEADER_ALIGN = Alignment(wrap_text=True, vertical="center", horizontal="center")
DATA_ALIGN = Alignment(wrap_text=True, vertical="center", horizontal="center")
COLUMN_WIDTHS: list[int] = [18, 40, 14, 28, 18, 10, 16, 18, 18, 14, 14, 24, 30, 10]

# Playwright 超时配置（毫秒）
NAV_TIMEOUT = 20_000
LOAD_TIMEOUT = 15_000
WAIT_SHORT = 1000
WAIT_MEDIUM = 2000

# 重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 秒，指数退避基数


# ==================== 数据类 ====================

@dataclass
class BOMItem:
    """BOM 清单条目。"""
    code: str
    name: str
    qty: float | int
    unit: str


@dataclass
class FlowRecord:
    """提取到的单条询价记录。"""
    flow_id: str = ""
    project_name: str = "--"
    agent_code: str = "--"
    agent_name: str = "--"
    province: str = "--"
    salesperson: str = "--"
    module_kw: float | str = "无"
    inverter_kw: float | str = "无"
    battery_kwh: float | str = "无"
    unit_price: str = "--"
    total_price: str = "--"
    submit_time: str = "--"
    remark: str = "无"
    ordered: str = "否"


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


def get_week_range(weeks_ago: int = 0) -> tuple[str, str]:
    """计算指定周的开始（周一）和结束日期。"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    end = today if weeks_ago == 0 else monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ==================== 登录 ====================

def _get_credentials() -> tuple[str, str]:
    """从共享模块读取登录凭据。"""
    def _log_source(source: str) -> None:
        logger.info("从 %s 加载登录凭据", source_label(source))

    return _get_dms_credentials(on_source=_log_source)


@retry_async(max_retries=3)
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
    if is_on_login_page(page.url):
        await do_login(page)
        await page.goto(f"{DMS_URL}/#/process/process_center", timeout=NAV_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)


async def _process_table_rows(
    page: Any,
    flow_ids: list[str],
    seen_ids: set[str],
    skipped_invalid: int,
    skipped_dup: int,
    valid_rows: int,
) -> tuple[list[str], set[str], int, int, int]:
    """处理当前页面的表格行，提取有效流程编号。"""
    rows = await page.locator("table.el-table__body tbody tr").all()
    logger.debug("找到 %d 行", len(rows))

    for row in rows:
        cells = await row.locator("td").all()
        if len(cells) < 2:
            continue
        cell_texts = [((await c.text_content()) or "").strip().strip('"') for c in cells]
        flow_text = cell_texts[0] if cell_texts else ""

        if not re.match(r"^\d{15,}$", flow_text):
            continue
        valid_rows += 1

        status_text = ""
        for t in cell_texts[-3:]:
            if any(k in t for k in ("作废", "驳回", "通过", "审批")):
                status_text = t
                break

        if "作废" in status_text:
            skipped_invalid += 1
            logger.debug("跳过作废流程: %s", flow_text)
            continue
        if flow_text in seen_ids:
            skipped_dup += 1
            logger.debug("跳过重复流程: %s", flow_text)
            continue

        seen_ids.add(flow_text)
        flow_ids.append(flow_text)

    return flow_ids, seen_ids, skipped_invalid, skipped_dup, valid_rows


async def filter_and_get_flow_ids(page: Any, start_date: str, end_date: str) -> list[str]:
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

    flow_ids: list[str] = []
    seen_ids: set[str] = set()
    skipped_invalid = 0
    skipped_dup = 0
    valid_rows = 0

    # 处理第 1 页
    flow_ids, seen_ids, skipped_invalid, skipped_dup, valid_rows = (
        await _process_table_rows(page, flow_ids, seen_ids,
                                  skipped_invalid, skipped_dup, valid_rows)
    )

    # 翻页处理后续页面
    for page_num in range(2, total_pages + 1):
        logger.debug("翻到第 %d 页", page_num)
        try:
            await page.locator(".el-pager").get_by_text(str(page_num), exact=True).click()
            await page.wait_for_timeout(WAIT_MEDIUM)
        except PlaywrightTimeout:
            logger.warning("翻到第 %d 页失败，终止翻页", page_num)
            break

        flow_ids, seen_ids, skipped_invalid, skipped_dup, valid_rows = (
            await _process_table_rows(page, flow_ids, seen_ids,
                                      skipped_invalid, skipped_dup, valid_rows)
        )

    logger.info("有效记录: %d 条, 提取流程: %d 个", valid_rows, len(flow_ids))
    if skipped_invalid:
        logger.info("跳过作废流程: %d 条", skipped_invalid)
    if skipped_dup:
        logger.info("跳过重复流程: %d 条", skipped_dup)
    return flow_ids


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


def _extract_power(name: str) -> float | None:
    """从物料名称中提取功率（kW）。"""
    m = re.search(r"_(\d+(?:\.\d+)?)\s*(k?W)_", name, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return val / 1000 if m.group(2).lower() == "w" else val
    return None


def _extract_capacity(name: str) -> float | None:
    """从物料名称中提取容量（kWh）。"""
    m = re.search(r"_(\d+(?:\.\d+)?)\s*(k?Wh)_", name, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return val / 1000 if m.group(2).lower() == "wh" else val
    return None


def _calc_module_power(items: list[BOMItem]) -> float | str:
    total = 0.0
    for i in items:
        kw = _extract_power(i.name)
        if kw is not None and ("销售组件" in i.name or "组件" in i.name):
            total += kw * i.qty
    return round(total, 2) if total > 0 else "无"


def _calc_inverter_power(items: list[BOMItem]) -> float | str:
    total = 0.0
    for i in items:
        kw = _extract_power(i.name)
        if kw is not None and "逆变器" in i.name:
            total += kw * i.qty
    return round(total, 2) if total > 0 else "无"


def _calc_battery_capacity(items: list[BOMItem]) -> float | str:
    total = 0.0
    for i in items:
        kwh = _extract_capacity(i.name)
        if kwh is not None and ("电池" in i.name or "储能" in i.name):
            total += kwh * i.qty
    return round(total, 2) if total > 0 else "无"


def _build_remark(items: list[BOMItem]) -> str:
    """从 BOM 中汇总备注信息。"""
    remarks: list[str] = []
    has_inverter = False
    has_grid_cabinet = False
    has_grid_box = False
    has_dc_cable = False

    for item in items:
        if "光储逆变器" in item.name and not has_inverter:
            remarks.append("光储逆变器")
            has_inverter = True
        if "并网柜" in item.name and not has_grid_cabinet:
            remarks.append("有并网柜")
            has_grid_cabinet = True
        if "并网箱" in item.name and not has_grid_box and not has_grid_cabinet:
            remarks.append("有并网箱")
            has_grid_box = True
        if ("直流电缆" in item.name or "直流线" in item.name) and not has_dc_cable:
            remarks.append("有直流线")
            has_dc_cable = True

    return "; ".join(remarks) if remarks else "无"


# ==================== 详情提取（BOM + 审批时间） ====================

async def _extract_bom(page: Any) -> list[BOMItem]:
    """从详情页提取 BOM 清单。"""
    items: list[BOMItem] = []
    try:
        tables = await page.locator("table").all()
        for i, table in enumerate(tables):
            thead = table.locator("thead")
            if await thead.count() > 0 and "物料编号" in ((await thead.text_content()) or ""):
                if i + 1 < len(tables):
                    for row in await tables[i + 1].locator("tbody tr").all():
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
                break
    except Exception as e:
        logger.warning("BOM 提取异常: %s", e)

    # 去重
    seen: set[str] = set()
    deduped: list[BOMItem] = []
    for item in items:
        if item.code not in seen:
            seen.add(item.code)
            deduped.append(item)
    return deduped


async def _extract_submit_time(page: Any) -> str:
    """从审批节点表中提取流程发起人提交审核时间。"""
    try:
        tables = await page.locator("table").all()
        for i, table in enumerate(tables):
            thead = table.locator("thead")
            if await thead.count() > 0 and "审批节点" in ((await thead.text_content()) or ""):
                if i + 1 < len(tables):
                    for row in await tables[i + 1].locator("tbody tr").all():
                        text = await row.text_content() or ""
                        if "流程发起人" in text and "提交审核" in text:
                            for cell in await row.locator("td").all():
                                ct = ((await cell.text_content()) or "").strip()
                                if re.match(r"\d{4}-\d{2}-\d{2}", ct):
                                    return ct
                break
    except Exception:
        pass
    return "--"


async def extract_detail_by_url(
    context: Any, flow_id: str, sem: asyncio.Semaphore,
) -> FlowRecord | None:
    """在新 Tab 中打开详情页提取单条询价数据。"""
    async with sem:
        page = await context.new_page()
        url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=1"
        try:
            await page.goto(url, timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
            await page.wait_for_timeout(WAIT_SHORT)

            if is_on_login_page(page.url):
                await do_login(page)
                await page.goto(url, timeout=NAV_TIMEOUT)
                await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)

            html = await page.content()
            rec = FlowRecord(flow_id=flow_id)

            rec.project_name = _extract_from_html(html, "项目名称")
            agent_raw = _extract_from_html(html, "代理商")
            rec.agent_code, rec.agent_name = _split_agent(agent_raw)
            rec.province = _extract_from_html(html, "省公司")
            rec.salesperson = _extract_from_html(html, "业务员")
            rec.unit_price = _extract_from_html(html, "瓦单价\\(元/瓦\\)")
            rec.total_price = _extract_from_html(html, "总价\\(元\\)")

            bom_items = await _extract_bom(page)
            rec.module_kw = _calc_module_power(bom_items)
            rec.inverter_kw = _calc_inverter_power(bom_items)
            rec.battery_kwh = _calc_battery_capacity(bom_items)
            rec.remark = _build_remark(bom_items)
            rec.submit_time = await _extract_submit_time(page)

            return rec
        except (PlaywrightTimeout, OSError, ValueError, AttributeError) as e:
            logger.warning("%s: 提取异常 %s", flow_id, e)
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
            logger.info("[%d/%d] %s: %s", i + 1, total, result.flow_id, result.project_name)
        else:
            logger.warning("[%d/%d] %s: 提取失败", i + 1, total, flow_ids[i])

    order = {fid: i for i, fid in enumerate(flow_ids)}
    records.sort(key=lambda r: order.get(r.flow_id, 999))
    return records


# ==================== 下单检查 ====================

async def check_single_order(
    context: Any, flow_id: str, sem: asyncio.Semaphore,
) -> str:
    """在订单页面搜索流程编号是否已下单。"""
    async with sem:
        page = await context.new_page()
        try:
            await page.goto(f"{DMS_URL}/#/orderManage/orderHistory", timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)

            # 处理可能的登录重定向
            if is_on_login_page(page.url):
                await do_login(page)
                await page.goto(f"{DMS_URL}/#/orderManage/orderHistory", timeout=NAV_TIMEOUT)
                await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)

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
        except Exception as e:
            logger.warning("%s: 下单检查异常 %s", flow_id, e)
            return "否"
        finally:
            await page.close()


async def check_orders_parallel(
    context: Any, records: list[FlowRecord], workers: int,
) -> list[FlowRecord]:
    """并行检查所有记录的下单状态。"""
    logger.info("并行检查下单状态 %d 条（%d 并发）...", len(records), workers)
    sem = asyncio.Semaphore(workers)
    tasks = [check_single_order(context, r.flow_id, sem) for r in records]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, (record, result) in enumerate(zip(records, results)):
        record.ordered = result if isinstance(result, str) else "否"
        status = "已下单" if record.ordered == "是" else "未下单"
        logger.info("[%d/%d] %s: %s", i + 1, len(records), record.flow_id, status)
    return records


# ==================== Excel 生成 ====================

def generate_excel(records: list[FlowRecord], output_dir: str | None = None) -> str:
    """生成格式化 Excel 文件。"""
    output_dir = output_dir or os.getcwd()
    file_path = os.path.join(output_dir, "询价汇总.xlsx")
    backup_path = os.path.join(output_dir, "询价汇总_v2.xlsx")

    if os.path.exists(file_path):
        try:
            with open(file_path, "a"):
                pass
        except PermissionError:
            logger.warning("%s 被占用，使用备用文件名", file_path)
            file_path = backup_path

    # 构建行数据
    rows_data: list[list[Any]] = []
    for r in records:
        rows_data.append([
            r.flow_id, r.project_name,
            r.agent_code, r.agent_name,
            r.province, r.salesperson,
            r.module_kw, r.inverter_kw, r.battery_kwh,
            r.unit_price, r.total_price,
            r.submit_time, r.remark, r.ordered,
        ])

    if os.path.exists(file_path):
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active
        next_row = ws.max_row + 1
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "询价汇总"
        for col, h in enumerate(HEADERS, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = WHITE_BOLD
            cell.fill = BLUE_FILL
            cell.border = THIN_BORDER
            cell.alignment = HEADER_ALIGN
        for i, w in enumerate(COLUMN_WIDTHS):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
        ws.row_dimensions[1].height = 30
        next_row = 2

    for row_data in rows_data:
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=next_row, column=col, value=val)
            cell.border = THIN_BORDER
            cell.alignment = DATA_ALIGN
        ws.row_dimensions[next_row].height = 35
        next_row += 1

    wb.save(file_path)
    logger.info("Excel 已保存: %s (共 %d 条记录)", file_path, len(rows_data))
    return file_path


# ==================== 终端摘要 ====================

def print_summary(
    start_time: datetime,
    start_date: str, end_date: str,
    flow_ids: list[str] | None,
    records: list[FlowRecord] | None,
    excel_path: str | None = None,
    error: str | None = None,
) -> None:
    """打印格式化执行摘要到终端。"""
    elapsed = (datetime.now() - start_time).total_seconds()
    ordered = sum(1 for r in (records or []) if r.ordered == "是")
    not_ordered = len(records or []) - ordered

    print("\n========================================")
    print("  执行摘要")
    print("========================================")
    print(f"  查询范围    {start_date} ~ {end_date}")
    if flow_ids:
        print(f"  提取记录    {len(flow_ids)} 条")
    if records:
        print(f"  已下单      {ordered} 条")
        print(f"  未下单      {not_ordered} 条")
    if excel_path:
        print(f"  Excel文件   {excel_path}")
    if error:
        print(f"  执行状态    异常: {error}")
    print(f"  总耗时      {elapsed:.1f} 秒")
    print("========================================")


# ==================== 主流程 ====================

async def run(args: argparse.Namespace) -> None:
    """主流程编排。"""
    output_dir = args.output_dir or os.getcwd()

    if args.start_date:
        start_date = args.start_date
        end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    else:
        start_date, end_date = get_week_range(args.weeks)

    start_time = datetime.now()
    logger.info("=== 询价周报自动化（%d 并发）===", args.workers)
    logger.info("日期范围: %s ~ %s", start_date, end_date)
    logger.info("输出目录: %s", output_dir)

    flow_ids: list[str] = []
    records: list[FlowRecord] = []
    excel_path: str | None = None
    error_msg: str | None = None

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=args.headless,
            no_viewport=True,
            locale="zh-CN",
            ignore_https_errors=True,
            args=["--start-maximized"],
        )
        page = await context.new_page()

        try:
            # 1. 登录
            await page.goto(DMS_URL, timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
            if is_on_login_page(page.url):
                await do_login(page)
            else:
                logger.info("会话有效（已复用缓存）")

            # 2. 筛选
            flow_ids = await filter_and_get_flow_ids(page, start_date, end_date)
            if not flow_ids:
                logger.info("本周无已办询价记录")
                return

            # 关闭初始 page，释放资源供并行 Tab 使用
            await page.close()

            # 3. 并行提取详情
            all_details = await extract_all_parallel(context, flow_ids, args.workers)
            if not all_details:
                logger.info("未能提取到任何详情")
                return

            # 4. 并行检查下单
            all_details = await check_orders_parallel(context, all_details, args.workers)
            records = all_details

            # 5. 生成 Excel
            excel_path = generate_excel(all_details, output_dir)

        except Exception as e:
            error_msg = str(e)
            logger.error("执行异常: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            await context.close()

    print_summary(start_time, start_date, end_date, flow_ids, records, excel_path, error=error_msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="DMS 非标询价周报自动化")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器）")
    parser.add_argument("--weeks", type=int, default=0,
                        help="查询最近 N 周（0=本周, 1=上周, 默认 0）")
    parser.add_argument("--start-date", type=str, default=None,
                        help="自定义开始日期（YYYY-MM-DD），优先于 --weeks")
    parser.add_argument("--end-date", type=str, default=None,
                        help="自定义结束日期（YYYY-MM-DD），默认为今天")
    parser.add_argument("--workers", type=int, default=3,
                        help="并行并发数（默认 3）")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="输出目录（默认为当前工作目录）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="输出详细调试日志")
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
