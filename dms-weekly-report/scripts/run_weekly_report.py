#!/usr/bin/env python3
"""DMS 非标询价周报自动化脚本（并行版 v2）。

架构总览（完整模式）：
  配置 → 登录 DMS → 筛选已办询价 → 多 Tab 并行提取详情（BOM + 审批） →
  多 Tab 并行检查下单状态 → 生成 Excel（4 Sheet） + HTML 报表 → 终端摘要

仅统计模式（--stats-only）：
  配置 → 读取已有 Excel → 按日期范围筛选 → 更新统计 Sheet → 终端输出

核心模块划分：
  - 数据类: BOMItem, FlowRecord, TableProcessProcess — 提取过程中的数据结构
  - 浏览器操作: do_login, filter_and_get_flow_ids, extract_detail_by_url — Playwright 自动化
  - BOM 解析: _extract_power, _extract_capacity, _build_remark — 从物料名称解析功率/容量
  - Excel 生成: generate_excel, _update_summary_sheet, _create_date_query_sheet_v2, _create_report_dashboard
  - 下单检查: check_orders_parallel — 并行查询订单历史

用法：
    python run_weekly_report.py [--headless] [--weeks N] [--workers N] [--verbose]
    python run_weekly_report.py --start-date 2026-05-01 --end-date 2026-05-31 [--headless]
    python run_weekly_report.py --stats-only --start-date 2026-06-01 --end-date 2026-06-07
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

# 共享 Excel 样式
from excel_styles import (
    Colors,
    THIN_BORDER, BOTTOM_BORDER,
    FONT_TITLE, FONT_SECTION, FONT_SUBSECTION, FONT_HEADER,
    FONT_DATA, FONT_LABEL, FONT_KPI_BIG, FONT_KPI_MED,
    FONT_HINT, FONT_VALUE,
    FILL_HEADER, FILL_LIGHT, FILL_VERY_LIGHT, FILL_CARD,
    ALIGN_CENTER, ALIGN_LEFT, ALIGN_DATA, ALIGN_HEADER,
    ROW_HEIGHT_TITLE, ROW_HEIGHT_SECTION, ROW_HEIGHT_DATA, ROW_HEIGHT_HEADER,
    COLUMN_WIDTHS,
    apply_header_style, apply_data_row,
    write_section_title, write_kpi_card,
)
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

# Excel 列定义
HEADERS: list[str] = [
    "流程编号", "项目名称", "代理商编号", "代理商名称", "省公司", "业务员",
    "组件总功率(kW)", "逆变器总功率(kW)", "电池总容量(kWh)",
    "瓦单价(元/瓦)", "总价(元)", "流程发起人提交审核时间", "备注", "是否下单",
    "省总审批人", "省总审批状态", "采购审批人", "采购审批状态", "审批完成时间",
]

# ==================== Playwright 超时与重试配置 ====================
# 这些值影响浏览器自动化的稳定性，DMS 页面响应慢时可适当调大
NAV_TIMEOUT = 30_000       # 页面导航超时（ms）
LOAD_TIMEOUT = 30_000      # networkidle 等待超时（ms）
WAIT_SHORT = 1000          # 短等待，用于 DOM 渲染后稳定（ms）
WAIT_MEDIUM = 2000         # 中等等待，用于分页/查询后数据加载（ms）

# 重试配置：失败时指数退避，避免网络抖动导致整体失败
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 秒，指数退避基数


# ==================== 数据类 ====================
# 以下三个 dataclass 是提取流程中的核心数据结构，
# 贯穿浏览器提取 → 数据计算 → Excel 生成全链路。

@dataclass
class BOMItem:
    """BOM 清单条目——从 DMS 详情页的物料表格中提取。"""
    code: str      # 物料编号
    name: str      # 物料名称（含功率/容量信息，用于解析）
    qty: float | int  # 数量
    unit: str      # 单位


@dataclass
class FlowRecord:
    """提取到的单条询价记录——最终写入 Excel 的一行数据。

    字段分三组：
      基本信息: flow_id ~ salesperson（从详情页 HTML 提取）
      BOM 计算: module_kw ~ battery_kwh（从物料名称解析功率/容量）
      审批链:   province_processor ~ final_approval_time（从审批历史表提取）
    """
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
    # 以下 5 列为审批链信息（v1.2.0 新增）
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
    await ensure_logged_in(page, f"{DMS_URL}/#/process/process_center")


async def _process_table_rows(
    page: Any,
    result: TableProcessResult,
) -> TableProcessResult:
    """处理当前页面的表格行，提取有效流程编号。"""
    rows = await page.locator("table.el-table__body tbody tr").all()
    logger.debug("找到 %d 行", len(rows))

    for row in rows:
        cells = await row.locator("td").all()
        if len(cells) < 2:
            continue
        cell_texts = [((await c.text_content()) or "").strip().strip('"') for c in cells]
        flow_text = cell_texts[0] if cell_texts else ""

        # 按流程类型筛选：仅保留"户用小型工商业询价流程"
        if len(cell_texts) >= 2 and "户用小型工商业询价流程" not in cell_texts[1]:
            result.skipped_invalid += 1
            logger.debug("跳过非目标流程类型: %s (%s)", flow_text, cell_texts[1] if len(cell_texts) > 1 else "?")
            continue

        if not re.match(r"^\d{15,}$", flow_text):
            continue
        result.valid_rows += 1

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

        result.seen_ids.add(flow_text)
        result.flow_ids.append(flow_text)

    return result


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

    result = TableProcessResult()

    # 处理第 1 页
    result = await _process_table_rows(page, result)

    # 翻页处理后续页面
    for page_num in range(2, total_pages + 1):
        logger.debug("翻到第 %d 页", page_num)
        try:
            await page.locator(".el-pager").get_by_text(str(page_num), exact=True).click()
            await page.wait_for_timeout(WAIT_MEDIUM)
        except PlaywrightTimeout:
            logger.warning("翻到第 %d 页失败，终止翻页", page_num)
            break

        result = await _process_table_rows(page, result)

    logger.info("有效行: %d 行（去重后 %d 个流程）", result.valid_rows, len(result.flow_ids))
    if result.skipped_invalid:
        logger.info("跳过作废流程: %d 条", result.skipped_invalid)
    if result.skipped_dup:
        logger.info("跳过重复流程: %d 条", result.skipped_dup)
    return result.flow_ids


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


# ==================== BOM 物料名称解析 ====================
# 以下函数从 DMS 物料名称中提取功率(kW)和容量(kWh)，
# 是计算组件总功率、逆变器总功率、电池总容量的核心逻辑。
# DMS 物料命名格式多样，需要多模式匹配回退。

def _extract_power(name: str) -> float | None:
    """从物料名称中提取功率（kW）。

    支持多种 DMS 物料命名格式：
    - 下划线分隔：SUN2000-50KTL_50_kW_ 或 xxx_50000_W_
    - 无分隔符：组串式逆变器50kW 或 逆变器 100kW
    """
    # 优先匹配标准下划线分隔格式
    m = re.search(r"_(\d+(?:\.\d+)?)\s*(k?W)_", name, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        return val / 1000 if m.group(2).lower() == "w" else val
    # 回退：匹配任意位置的 XXXXkW 或 XXXX W 格式
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k?W)", name, re.IGNORECASE)
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


def _calc_module_power(items: list[BOMItem]) -> float:
    total = 0.0
    for i in items:
        kw = _extract_power(i.name)
        if kw is not None and ("销售组件" in i.name or "组件" in i.name):
            total += kw * i.qty
    return round(total, 2)


def _calc_inverter_power(items: list[BOMItem]) -> float:
    total = 0.0
    for i in items:
        kw = _extract_power(i.name)
        if kw is not None and "逆变器" in i.name:
            total += kw * i.qty
    if total == 0:
        inv_names = [i.name for i in items if "逆变器" in i.name.lower()]
        if inv_names:
            logger.debug("逆变器物料名称未匹配功率: %s", inv_names)
    return round(total, 2)


def _calc_battery_capacity(items: list[BOMItem]) -> float:
    total = 0.0
    for i in items:
        kwh = _extract_capacity(i.name)
        if kwh is not None and ("电池" in i.name or "储能" in i.name):
            total += kwh * i.qty
    return round(total, 2)


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
    """从详情页提取 BOM 清单。

    支持多个 el-table 容器（组件表 + 逆变器/电池表分开的场景）。
    通过 body table text content 去重，避免同一个表被重复处理。
    """
    items: list[BOMItem] = []
    processed_tables: set[str] = set()
    try:
        tables = await page.locator("table").all()
        for table in tables:
            thead = table.locator("thead")
            if await thead.count() > 0 and "物料编号" in ((await thead.text_content()) or ""):
                # 使用 following:: 而非 following-sibling:: 来应对跨容器布局
                body_table = table.locator("xpath=./following::table[.//tbody][1]")
                if await body_table.count() > 0:
                    # 用 body table 的文本指纹去重，避免重复处理同一张表
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
                # 不 break — 继续处理后续 el-table（组件和逆变器可能分不同 table）
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


async def _extract_approval_info(page: Any) -> dict[str, str]:
    """从审批历史表提取完整的审批链信息。

    提取字段：提交时间、省总审批人/状态、采购审批人/状态、最终完成时间。
    Returns: 包含 6 个键的 dict
    """
    result: dict[str, str] = {
        "submit_time": "--", "province_processor": "--", "province_status": "--",
        "purchase_processor": "--", "purchase_status": "--", "final_approval_time": "--",
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
    except Exception:
        pass
    return result


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
            rec.module_kw = _calc_module_power(bom_items)
            rec.inverter_kw = _calc_inverter_power(bom_items)
            rec.battery_kwh = _calc_battery_capacity(bom_items)
            rec.remark = _build_remark(bom_items)
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

@retry_async(max_retries=MAX_RETRIES)
async def _search_order_for_flow(context: Any, flow_id: str, sem: asyncio.Semaphore) -> str:
    """在订单页面搜索流程编号是否已下单。成功时返回 '是'/'否'，失败时抛出异常由重试机制处理。"""
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
    try:
        return await _search_order_for_flow(context, flow_id, sem)
    except (PlaywrightTimeout, OSError, RuntimeError) as e:
        logger.error("%s: 下单检查重试 %d 次后仍失败: %s", flow_id, MAX_RETRIES, e)
        return "检查失败"


async def check_orders_parallel(
    context: Any, records: list[FlowRecord], workers: int,
) -> list[FlowRecord]:
    """并行检查所有记录的下单状态。"""
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



# ==================== Excel 增强 Sheet 生成 ====================
# 以下函数在 generate_excel() 中调用，生成除「询价汇总」外的 3 个增强 Sheet：
#   - _update_summary_sheet: 「询价统计」— KPI 仪表盘式汇总
#   - _create_date_query_sheet_v2: 「日期查询」— 下拉交互式分时段统计
#   - _create_report_dashboard: 「数据看板」— 审批人统计/省公司排名/审批天数


def _fill_date_helper_column(ws: Any) -> None:
    """补充询价汇总Sheet的T列（日期序列号，供Excel公式使用），然后隐藏该列。"""
    from datetime import date as dt_date
    max_row = ws.max_row
    for r in range(2, max_row + 1):
        existing = ws.cell(row=r, column=20).value
        if existing is not None and isinstance(existing, (int, float)) and existing < 100000:
            continue
        l_val = ws.cell(row=r, column=12).value
        if l_val:
            date_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(l_val))
            if date_match:
                y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                excel_serial = dt_date(y, m, d).toordinal() - 693594
                ws.cell(row=r, column=20, value=excel_serial)
    # 隐藏辅助列 T
    ws.column_dimensions["T"].hidden = True


def _update_summary_sheet(
    wb: Any, data_ws: Any, query_range: str,
    filtered_rows: list[Any] | None = None,
) -> None:
    """更新「询价统计」Sheet — 仪表盘式 KPI 布局。"""
    if "询价统计" in wb.sheetnames:
        del wb["询价统计"]

    ws = wb.create_sheet("询价统计")

    # 列宽：A=标签, B=数值, C=单位（紧凑布局，去掉间隔列）
    for c, w in enumerate([28, 20, 14], 1):
        ws.column_dimensions[chr(64 + c)].width = w

    # 计算统计数据（与原有逻辑相同）
    total_module = 0.0
    total_inverter = 0.0
    total_battery = 0.0
    total_projects = 0
    ordered_count = 0
    not_ordered_count = 0
    salesperson_set: set[str] = set()

    source_rows = filtered_rows if filtered_rows is not None else data_ws.iter_rows(min_row=2, values_only=True)

    for row in source_rows:
        flow_id = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", flow_id):
            continue
        total_projects += 1
        mk = row[6]
        if mk not in ("无", "--", None, ""):
            try:
                total_module += float(mk)
            except (ValueError, TypeError):
                pass
        ik = row[7]
        if ik not in ("无", "--", None, ""):
            try:
                total_inverter += float(ik)
            except (ValueError, TypeError):
                pass
        bk = row[8]
        if bk not in ("无", "--", None, ""):
            try:
                total_battery += float(bk)
            except (ValueError, TypeError):
                pass
        ordered = str(row[13] if row[13] else "")
        if ordered == "是":
            ordered_count += 1
        else:
            not_ordered_count += 1
        sp = str(row[5] if row[5] else "")
        if sp not in ("--", "无", ""):
            salesperson_set.add(sp)

    # ---- 新排版：KPI 仪表盘 ----
    r = 1

    # 标题行
    ws.cell(r, 1, "询价统计汇总").font = FONT_TITLE
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    ws.row_dimensions[r].height = ROW_HEIGHT_TITLE
    r += 1

    # 统计周期
    ws.cell(r, 1, f"统计周期: {query_range}").font = FONT_VALUE
    ws.cell(r, 1).fill = FILL_LIGHT
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    ws.row_dimensions[r].height = ROW_HEIGHT_SECTION
    r += 2

    # ---- 区域1：询价概览 —— 每个 KPI 一行，从 A 列开始 ----
    ws.cell(r, 1, "询价概览").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    r += 1

    kpis_1 = [
        ("询价项目总数", f"{total_projects}", "个", FONT_KPI_BIG),
        ("涉及业务员", f"{len(salesperson_set)}", "人" if salesperson_set else "", FONT_KPI_BIG),
        ("已下单项目", f"{ordered_count}", "个", FONT_KPI_BIG),
        ("未下单项目", f"{not_ordered_count}", "个", FONT_KPI_BIG),
    ]
    for i, (label, value, unit, vf) in enumerate(kpis_1):
        write_kpi_card(ws, r + i, 1, label, value, unit, vf)

    r += len(kpis_1) + 2

    # ---- 区域2：功率容量统计 —— 每个 KPI 一行，从 A 列开始 ----
    ws.cell(r, 1, "功率容量统计").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    r += 1

    module_display = f"{total_module:,.2f}" if total_module > 0 else "0"
    inverter_display = f"{total_inverter:,.2f}" if total_inverter > 0 else "0"
    battery_display = f"{total_battery:,.2f}" if total_battery > 0 else "0"
    ratio_display = f"{total_module / total_inverter:.2f}" if total_inverter > 0 else "--"

    kpis_2 = [
        ("组件总功率", module_display, "kW", FONT_KPI_BIG),
        ("逆变器总功率", inverter_display, "kW", FONT_KPI_BIG),
        ("电池总容量", battery_display, "kWh", FONT_KPI_BIG),
        ("容配比(组件/逆变器)", ratio_display, "", FONT_KPI_BIG),
    ]
    for i, (label, value, unit, vf) in enumerate(kpis_2):
        write_kpi_card(ws, r + i, 1, label, value, unit, vf)

    r += len(kpis_2) + 2
    # 页脚说明
    ws.cell(r, 1, f"数据范围：全部历史数据 | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}").font = FONT_HINT
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)


def _create_date_query_sheet_v2(wb: Any) -> None:
    """创建「日期查询」交互 Sheet — 紧凑布局，从 A 列开始。"""
    data_ws = wb["询价汇总"]
    last_data_row = max(data_ws.max_row, 2)

    rows_data: list[list[Any]] = []
    for r in range(2, last_data_row + 1):
        row = []
        for c in range(1, 20):
            row.append(data_ws.cell(r, c).value)
        rows_data.append(row)

    from datetime import date as dt_date

    def excel_serial(d: dt_date) -> int:
        return d.toordinal() - 693594

    def parse_date(l_val: Any) -> int | None:
        if l_val:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(l_val))
            if m:
                return excel_serial(dt_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        return None

    today = dt_date.today()
    wd = today.weekday()
    m_start = dt_date(today.year, today.month, 1)

    periods: dict[str, tuple[int, int]] = {}
    periods["全部"] = (excel_serial(dt_date(2000, 1, 1)), excel_serial(dt_date(2099, 12, 31)))
    periods["本周"] = (excel_serial(dt_date.fromordinal(today.toordinal() - wd)), excel_serial(today))
    periods["本月"] = (excel_serial(m_start), excel_serial(today))
    if today.month == 1:
        periods["上月"] = (excel_serial(dt_date(today.year - 1, 12, 1)), excel_serial(dt_date(today.year - 1, 12, 31)))
    else:
        lm = dt_date(today.year, today.month - 1, 1)
        lme = dt_date(today.year, today.month, 1) - dt_date.resolution
        periods["上月"] = (excel_serial(lm), excel_serial(lme))
    qs = (today.month - 1) // 3 * 3 + 1
    periods["本季度"] = (excel_serial(dt_date(today.year, qs, 1)), excel_serial(today))

    stats: dict[str, list[Any]] = {}
    for name, (s, e) in periods.items():
        cnt = 0; mod = 0.0; inv = 0.0; bat = 0.0
        for row in rows_data:
            fid = str(row[0]) if row[0] else ""
            if not re.match(r"^\d{15,}$", fid):
                continue
            o = parse_date(row[11] if len(row) > 11 else None)
            if o is None or o < s or o > e:
                continue
            cnt += 1
            if len(row) > 6 and isinstance(row[6], (int, float)):
                mod += float(row[6])
            if len(row) > 7 and isinstance(row[7], (int, float)):
                inv += float(row[7])
            if len(row) > 8 and isinstance(row[8], (int, float)):
                bat += float(row[8])
        ratio = round(mod / inv, 2) if inv > 0 else 0
        stats[name] = [cnt, round(mod, 2), round(inv, 2), round(bat, 2), ratio]

    for sheet_name in ("日期查询", "日期查询(旧)"):
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]

    ws = wb.create_sheet("日期查询")

    # 列宽 — 从 A 列开始紧凑布局
    for c, w in enumerate([24, 16, 20, 20, 20, 16, 18], 1):
        ws.column_dimensions[chr(64 + c)].width = w

    r = 1
    # 标题
    ws.cell(r, 1, "日期查询统计").font = FONT_TITLE
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    ws.row_dimensions[r].height = ROW_HEIGHT_TITLE
    r += 1

    # 筛选标签和下拉（从 B2 开始，比原来的 D3 更靠左）
    ws.cell(r, 1, "时间段筛选：").font = FONT_LABEL
    ws.cell(r, 1).alignment = ALIGN_LEFT
    ws.cell(r, 1).border = THIN_BORDER
    ws.cell(r, 2, "全部").font = FONT_DATA
    ws.cell(r, 2).border = THIN_BORDER
    ws.cell(r, 2).alignment = ALIGN_CENTER
    ws.cell(r, 3, "  ← 点击选择").font = FONT_HINT
    ws.cell(r, 3).alignment = ALIGN_LEFT
    ws.row_dimensions[r].height = ROW_HEIGHT_DATA

    # 下拉数据验证
    presets = list(stats.keys())
    dv = openpyxl.worksheet.datavalidation.DataValidation(
        type="list", formula1=f'"{",".join(presets)}"',
        allow_blank=True,
    )
    dv.prompt = "选择时间段"
    dv.promptTitle = "快速选择"
    ws.add_data_validation(dv)
    dv.add(ws.cell(r, 2))
    r += 2

    # 预计算结果表
    ws.cell(r, 1, "预计算结果").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    r += 1

    headers = ["时间段", "项目数", "组件功率(kW)", "逆变器功率(kW)", "电池容量(kWh)", "容配比"]
    apply_header_style(ws, r, headers)
    table_header_row = r
    r += 1

    for i, name in enumerate(presets):
        vals = [name] + stats[name]
        fmts = [None, '0', '#,##0.00', '#,##0.00', '#,##0.00', '#,##0.00']
        apply_data_row(ws, r, vals, is_alt=(i % 2 == 1))
        for ci, nf in enumerate(fmts):
            if nf:
                ws.cell(r, 1 + ci).number_format = nf
        ws.row_dimensions[r].height = ROW_HEIGHT_DATA
        r += 1

    r += 1

    # INDEX/MATCH 公式结果（实时对应下拉选择）
    ws.cell(r, 1, "当前选择结果").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    r += 1

    n_p = len(presets)
    data_first = table_header_row + 1
    data_last = table_header_row + n_p
    dr = f"$A${data_first}:$F${data_last}"
    lr = f"$A${data_first}:$A${data_last}"

    for label, ci, nf in [
        ("询价项目数", 2, '0'),
        ("组件总功率 (kW)", 3, '#,##0.00'),
        ("逆变器总功率 (kW)", 4, '#,##0.00'),
        ("电池总容量 (kWh)", 5, '#,##0.00'),
        ("容配比（组件/逆变器）", 6, '#,##0.00'),
    ]:
        ws.cell(r, 1, label).font = FONT_LABEL
        ws.cell(r, 1).border = THIN_BORDER
        ws.cell(r, 1).alignment = ALIGN_CENTER
        ws.cell(r, 2).value = f'=IFERROR(INDEX({dr},MATCH($B$2,{lr},0),{ci}),0)'
        ws.cell(r, 2).font = Font(bold=True, size=11, color=Colors.RED_ACCENT)
        ws.cell(r, 2).border = THIN_BORDER
        ws.cell(r, 2).alignment = ALIGN_CENTER
        ws.cell(r, 2).number_format = nf
        ws.row_dimensions[r].height = ROW_HEIGHT_DATA
        r += 1

    r += 2
    # 使用说明
    ws.cell(r, 1, "使用说明").font = FONT_SECTION
    r += 1
    for tip in [
        "1. 点击 B2 → 从下拉选择预设时间段",
        "2. 预计算表格展示所有周期数据",
        "3. '当前选择结果' 随下拉实时变化",
        "4. 如需最新数据，重新运行周报脚本",
    ]:
        ws.cell(r, 1, tip).font = FONT_HINT
        r += 1


def _create_report_dashboard(wb: Any) -> None:
    """创建「数据看板」Sheet — 管理层报表风格。"""
    if "数据看板" in wb.sheetnames:
        del wb["数据看板"]

    ws = wb.create_sheet("数据看板")

    data_ws = wb["询价汇总"]
    last_data_row = max(data_ws.max_row, 2)

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 18
    ws.column_dimensions["G"].width = 18

    rows_data: list[list[Any]] = []
    for r in range(2, last_data_row + 1):
        row = []
        for c in range(1, 20):
            row.append(data_ws.cell(r, c).value)
        rows_data.append(row)

    r = 1
    # 标题
    ws.cell(r, 1, "询价数据看板").font = FONT_TITLE
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    ws.row_dimensions[r].height = ROW_HEIGHT_TITLE
    r += 2

    # ===== 区域1：王剑审批统计（一行三卡片） =====
    ws.cell(r, 1, "王剑采购审批统计").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    r += 1

    wangjian_count = 0
    wangjian_total = 0
    for row in rows_data:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        proc = str(row[16] if len(row) > 16 and row[16] else "")
        status_val = str(row[17] if len(row) > 17 and row[17] else "")
        if "王剑" in proc:
            wangjian_total += 1
            if "审批通过" in status_val:
                wangjian_count += 1

    rate = f"{wangjian_count/wangjian_total*100:.0f}%" if wangjian_total > 0 else "--"

    cards = [
        ("审批通过", wangjian_count, "次", FONT_KPI_BIG),
        ("经手总次数", wangjian_total, "次", FONT_KPI_MED),
        ("通过率", rate, "", FONT_KPI_BIG),
    ]
    for i, (label, value, unit, vf) in enumerate(cards):
        col = 1 + i * 2  # A(1), C(3), E(5) — 从 A 列开始
        write_kpi_card(ws, r, col, label, value, unit, vf, alt_fill=True)
    r += 2

    # ===== 区域2：省公司询价排名 =====
    ws.cell(r, 1, "省公司询价排名").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    r += 1

    province_stats: dict[str, dict[str, Any]] = {}
    for row in rows_data:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        pv = str(row[4] if len(row) > 4 and row[4] else "")
        if pv in ("--", "无", ""):
            continue
        g = float(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else 0
        if pv not in province_stats:
            province_stats[pv] = {"cnt": 0, "module": 0.0}
        province_stats[pv]["cnt"] += 1
        province_stats[pv]["module"] += g

    sorted_prov = sorted(province_stats.items(), key=lambda x: -x[1]["cnt"])

    headers = ["排名", "省公司", "询价次数", "组件总功率(kW)"]
    apply_header_style(ws, r, headers)
    r += 1

    for rank_i, (rank, (pv, data)) in enumerate(zip(range(1, len(sorted_prov) + 1), sorted_prov)):
        row_vals = [rank, pv, data["cnt"], round(data["module"], 2)]
        apply_data_row(ws, r, row_vals, is_alt=(rank_i % 2 == 1))
        ws.cell(r, 4).number_format = '#,##0.00'
        ws.row_dimensions[r].height = ROW_HEIGHT_DATA
        r += 1

    r += 2

    # ===== 区域3：审批天数统计（一行四卡片） =====
    ws.cell(r, 1, "询价到审批完成天数").font = FONT_SECTION
    ws.cell(r, 1).alignment = ALIGN_CENTER
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    r += 1

    days_list: list[int] = []
    for row in rows_data:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        final_time = str(row[18] if len(row) > 18 and row[18] else "")
        if submit_time in ("--", "") or final_time in ("--", ""):
            continue
        sm = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
        fm = re.match(r"(\d{4}-\d{2}-\d{2})", final_time)
        if sm and fm:
            from datetime import datetime as dt_dt
            try:
                sd = dt_dt.strptime(sm.group(1), "%Y-%m-%d")
                fd = dt_dt.strptime(fm.group(1), "%Y-%m-%d")
                delta = (fd - sd).days
                if delta >= 0:
                    days_list.append(delta)
            except ValueError:
                pass

    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0
    total_with_both = len(days_list)

    day_cards = [
        ("平均天数", avg_days, "天", FONT_KPI_BIG),
        ("最短天数", min(days_list) if days_list else 0, "天", FONT_KPI_MED),
        ("最长天数", max(days_list) if days_list else 0, "天", FONT_KPI_MED),
        ("统计样本数", total_with_both, "条", FONT_KPI_MED),
    ]
    for i, (label, value, unit, vf) in enumerate(day_cards):
        col = 1 + i * 2  # A(1), C(3), E(5), G(7)
        write_kpi_card(ws, r, col, label, value, unit, vf, alt_fill=True)
    r += 2

    # 说明
    ws.cell(r, 1, "说明").font = FONT_SECTION
    r += 1
    for tip in [
        "1. 王剑审批统计基于采购审批节点数据",
        "2. 省公司排名按询价次数降序排列",
        "3. 审批天数 = 审批完成时间 - 发起人提交审核时间",
        "4. 如需最新数据，重新运行周报脚本即可",
    ]:
        ws.cell(r, 1, tip).font = FONT_HINT
        r += 1


# ==================== Excel 生成 ====================

def generate_excel(
    records: list[FlowRecord],
    output_dir: str | None = None,
    query_range: str = "",
    timestamp_str: str | None = None,
) -> tuple[str, list[list[Any]]]:
    """生成格式化 Excel 文件。"""
    output_dir = output_dir or os.getcwd()
    ts = timestamp_str or datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(output_dir, f"询价汇总_{ts}.xlsx")
    backup_path = os.path.join(output_dir, f"询价汇总_{ts}_v2.xlsx")

    if os.path.exists(file_path):
        try:
            with open(file_path, "a"):
                pass
        except PermissionError:
            logger.warning("%s 被占用，使用备用文件名", file_path)
            file_path = backup_path

    # 构建行数据（19 列，含审批链信息）
    rows_data: list[list[Any]] = []
    for r in records:
        rows_data.append([
            r.flow_id, r.project_name,
            r.agent_code, r.agent_name,
            r.province, r.salesperson,
            r.module_kw, r.inverter_kw, r.battery_kwh,
            r.unit_price, r.total_price,
            r.submit_time, r.remark, r.ordered,
            r.province_processor, r.province_status,
            r.purchase_processor, r.purchase_status,
            r.final_approval_time,
        ])

    if os.path.exists(file_path):
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active

        # 读取已有流程编号，去重
        existing_ids: set[str] = set()
        for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
            if row[0] and re.match(r"^\d{15,}$", str(row[0])):
                existing_ids.add(str(row[0]))

        new_rows = [r for r in rows_data if str(r[0]) not in existing_ids]
        skipped = len(rows_data) - len(new_rows)
        if skipped:
            logger.info("跳过 %d 条重复记录", skipped)
        rows_data = new_rows

        next_row = ws.max_row + 1
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "询价汇总"
        apply_header_style(ws, 1, HEADERS)
        for i, w in enumerate(COLUMN_WIDTHS):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
        ws.row_dimensions[1].height = ROW_HEIGHT_HEADER
        next_row = 2

    for i, row_data in enumerate(rows_data):
        is_alt = (i % 2 == 1)
        apply_data_row(ws, next_row, row_data, is_alt=is_alt)
        ws.row_dimensions[next_row].height = ROW_HEIGHT_DATA
        next_row += 1

    # 更新增强 Sheet（统计/日期查询/数据看板）
    _update_summary_sheet(wb, ws, query_range)
    _fill_date_helper_column(ws)
    _create_date_query_sheet_v2(wb)
    _create_report_dashboard(wb)

    wb.save(file_path)
    logger.info("Excel 已保存: %s (共 %d 条记录)", file_path, len(rows_data))
    return file_path, rows_data


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
    not_ordered = sum(1 for r in (records or []) if r.ordered == "否")
    check_failed = sum(1 for r in (records or []) if r.ordered == "检查失败")

    print("\n========================================")
    print("  执行摘要")
    print("========================================")
    print(f"  查询范围    {start_date} ~ {end_date}")
    if flow_ids:
        print(f"  提取记录    {len(flow_ids)} 条")
    if records:
        print(f"  已下单      {ordered} 条")
        print(f"  未下单      {not_ordered} 条")
        if check_failed:
            print(f"  检查失败    {check_failed} 条")
    if excel_path:
        print(f"  Excel文件   {excel_path}")
    if error:
        print(f"  执行状态    异常: {error}")
    print(f"  总耗时      {elapsed:.1f} 秒")
    print("========================================")


# ==================== 主流程编排 ====================

async def run(args: argparse.Namespace) -> None:
    """完整模式主流程：登录 → 筛选 → 提取 → 检查下单 → 生成报表。

    步骤：
      1. 启动 Playwright 持久化浏览器上下文（复用登录缓存）
      2. 登录 DMS（会话有效时跳过）
      3. 导航到流程中心，按日期筛选已办询价，翻页收集流程编号
      4. 并行打开新 Tab 提取每条流程的详情（BOM + 审批信息）
      5. 并行检查每条流程的下单状态
      6. 生成 Excel（4 Sheet）和 HTML 报表
    """
    output_dir = args.output_dir or os.getcwd()

    if args.start_date:
        start_date = args.start_date
        end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    else:
        start_date, end_date = get_week_range(args.weeks)

    start_time = datetime.now()
    timestamp_str = start_time.strftime("%Y%m%d_%H%M%S")
    logger.info("=== 询价周报自动化（%d 并发）===", args.workers)
    logger.info("日期范围: %s ~ %s", start_date, end_date)
    logger.info("输出目录: %s", output_dir)
    os.makedirs(output_dir, exist_ok=True)

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
            query_range = f"{start_date} ~ {end_date}"
            excel_path, rows_data = generate_excel(all_details, output_dir,
                                                     query_range=query_range,
                                                     timestamp_str=timestamp_str)

            # 6. 生成 HTML 报表（不影响主流程）
            try:
                from generate_html_report import generate_html_report as _gen_html
                html_path = os.path.join(output_dir, f"询价周报报表_{timestamp_str}.html")
                _gen_html(rows_data, query_range, html_path)
                logger.info("HTML 报表已生成: %s", html_path)
            except Exception as html_e:
                logger.warning("HTML 报表生成失败（不影响 Excel）: %s", html_e)

        except Exception as e:
            error_msg = str(e)
            logger.error("执行异常: %s", e)
            import traceback
            traceback.print_exc()
        finally:
            try:
                await context.close()
            except TargetClosedError:
                logger.debug("浏览器上下文已提前关闭，忽略")

    print_summary(start_time, start_date, end_date, flow_ids, records, excel_path, error=error_msg)


def stats_from_excel(args: argparse.Namespace) -> None:
    """仅统计模式主流程：读取已有 Excel → 按日期筛选 → 更新统计 Sheet。

    不启动浏览器，适用于已有数据只需重新计算统计的场景。
    兼容旧版无时间戳的文件名，支持 --this-month 快捷统计本月。
    """
    output_dir = args.output_dir or os.getcwd()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 尝试读取已有文件（兼容旧版无时间戳的文件名）
    candidates = [
        os.path.join(output_dir, f"询价汇总_{ts}.xlsx"),
        os.path.join(output_dir, "询价汇总.xlsx"),
        os.path.join(output_dir, "询价汇总_v2.xlsx"),
    ]
    file_path = next((p for p in candidates if os.path.exists(p)), candidates[0])

    if not os.path.exists(file_path):
        logger.error("未找到询价汇总文件: %s", file_path)
        return

    # 计算日期范围
    if args.this_month:
        today = datetime.now()
        start_date = today.replace(day=1).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
    elif args.start_date:
        start_date = args.start_date
        end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    else:
        start_date, end_date = get_week_range(0)

    query_range = f"{start_date} ~ {end_date}"
    logger.info("=== 询价统计（仅统计模式）===")
    logger.info("统计范围: %s", query_range)
    logger.info("数据来源: %s", file_path)

    wb = openpyxl.load_workbook(file_path)
    data_ws = wb["询价汇总"]

    # 确保列头完整（兼容老版本文件）
    for col in range(1, len(HEADERS) + 1):
        existing = data_ws.cell(row=1, column=col).value
        header_value = HEADERS[col - 1]
        if existing is None or existing != header_value:
            cell = data_ws.cell(row=1, column=col, value=header_value)
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.border = THIN_BORDER
            cell.alignment = ALIGN_HEADER

    # 清除旧数据行中 15~19 列的残留，补充辅助列 T(20)
    for r in range(2, data_ws.max_row + 1):
        for c in range(15, 20):
            data_ws.cell(row=r, column=c).value = None
    _fill_date_helper_column(data_ws)

    # 按日期范围筛选
    filtered_rows: list[Any] = []
    for row in data_ws.iter_rows(min_row=2, values_only=True):
        flow_id = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", flow_id):
            continue
        submit_time = str(row[11]) if row[11] else ""
        if submit_time not in ("--", "无", ""):
            date_match = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
            if date_match:
                row_date = date_match.group(1)
                if row_date < start_date or row_date > end_date:
                    continue
        filtered_rows.append(row)

    # 计算统计
    total_module = 0.0
    total_inverter = 0.0
    total_battery = 0.0
    ordered_count = 0
    not_ordered_count = 0
    salesperson_set: set[str] = set()

    for row in filtered_rows:
        mk = row[6]
        if mk not in ("无", "--", None, ""):
            try:
                total_module += float(mk)
            except (ValueError, TypeError):
                pass
        ik = row[7]
        if ik not in ("无", "--", None, ""):
            try:
                total_inverter += float(ik)
            except (ValueError, TypeError):
                pass
        bk = row[8]
        if bk not in ("无", "--", None, ""):
            try:
                total_battery += float(bk)
            except (ValueError, TypeError):
                pass
        ordered = str(row[13] if row[13] else "")
        if ordered == "是":
            ordered_count += 1
        else:
            not_ordered_count += 1
        sp = str(row[5] if row[5] else "")
        if sp not in ("--", "无", ""):
            salesperson_set.add(sp)

    # 更新统计 Sheet
    _update_summary_sheet(wb, data_ws, query_range, filtered_rows=filtered_rows)

    # 更新日期查询和数据看板 Sheet
    _fill_date_helper_column(data_ws)
    _create_date_query_sheet_v2(wb)
    _create_report_dashboard(wb)

    # 保存到新文件（带时间戳，不覆盖原文件）
    save_path = os.path.join(output_dir, f"询价汇总_{ts}.xlsx")
    wb.save(save_path)

    # 终端输出
    print(f"\n{'=' * 45}")
    print(f"  📊 统计结果 ({query_range})")
    print(f"{'=' * 45}")
    print(f"  询价项目       {len(filtered_rows)} 个")
    print(f"  涉及业务员     {len(salesperson_set)} 人")
    print(f"  已下单         {ordered_count} 个")
    print(f"  未下单         {not_ordered_count} 个")
    print(f"  ——")
    if total_module > 0:
        print(f"  组件总功率     {total_module:.2f} kW")
    if total_inverter > 0:
        print(f"  逆变器总功率   {total_inverter:.2f} kW")
    if total_battery > 0:
        print(f"  电池总容量     {total_battery:.2f} kWh")
    if total_inverter > 0:
        print(f"  容配比         {total_module / total_inverter:.2f}")
    print(f"{'=' * 45}")
    logger.info("统计结果已保存到: %s", save_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="DMS 非标询价周报自动化")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器）")
    parser.add_argument("--weeks", type=int, default=0,
                        help="查询最近 N 周（0=本周, 1=上周, 默认 0）")
    parser.add_argument("--start-date", type=str, default=None,
                        help="自定义开始日期（YYYY-MM-DD），优先于 --weeks")
    parser.add_argument("--end-date", type=str, default=None,
                        help="自定义结束日期（YYYY-MM-DD），默认为今天")
    parser.add_argument("--workers", type=int, default=4,
                        help="并行并发数（默认 4）")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="输出目录（默认为当前工作目录）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="输出详细调试日志")
    parser.add_argument("--stats-only", action="store_true",
                        help="仅统计模式：从已有Excel按日期范围重新统计，跳过浏览器操作")
    parser.add_argument("--this-month", action="store_true",
                        help="快捷统计本月（配合 --stats-only 使用）")
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)

    if args.stats_only:
        stats_from_excel(args)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
