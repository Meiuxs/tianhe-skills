#!/usr/bin/env python3
"""DMS 非标询价周报自动化脚本（编排层 v3）。

架构总览（完整模式）：
  core/dms_browser.py      — Playwright 浏览器自动化（登录、筛选、提取）
  core/bom_parser.py       — BOM 物料解析（功率、容量计算）
  core/approval_parser.py  — 审批链信息解析
  core/orders_checker.py   — 下单检查
  core/excel_generator.py  — Excel 报表生成（4 Sheet）
  excel_styles.py          — Excel 样式主题
  column_definitions.py    — 列定义和常量集中管理
  generate_html_report.py  — HTML 报表生成
  dms_credentials.py       — 凭据管理

用法：
    python run_weekly_report.py [--headless] [--weeks N] [--workers N]
    python run_weekly_report.py --start-date 2026-05-01 --end-date 2026-05-31
    python run_weekly_report.py --stats-only --start-date 2026-06-01 --end-date 2026-06-07
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from playwright._impl._errors import TargetClosedError

# 共享模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402
from column_definitions import DMS_URL, NAV_TIMEOUT, LOAD_TIMEOUT
from core.dms_browser import (
    FlowRecord,
    do_login, filter_and_get_flow_ids,
    extract_all_parallel, get_week_range,
    is_on_login_page,
)

logger = logging.getLogger("dms_report")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"
))
logger.addHandler(_handler)

# ==================== 配置 ====================

USER_DATA_DIR = Path.home() / ".dms_browser_data"


def configure_logging(verbose: bool = False) -> None:
    """根据 --verbose 标志配置日志级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    _handler.setLevel(level)


# ==================== 终端摘要 ====================


def print_summary(
    start_time: datetime,
    start_date: str, end_date: str,
    flow_ids: list[str] | None = None,
    records: list[FlowRecord] | None = None,
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
    """完整模式主流程：登录 → 筛选 → 提取 → 检查下单 → 生成报表。"""
    from core.orders_checker import check_orders_parallel
    from core.excel_generator import generate_excel

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

            # 3. 并行提取详情
            # 注意：不提前关闭 page。persistent_context 中关闭最后一个 page
            # 可能导致浏览器进程退出，影响后续 context.new_page() 调用。
            # page 会在 finally 中被 context.close() 一并清理。
            all_details = await extract_all_parallel(context, flow_ids, args.workers)
            if not all_details:
                logger.info("未能提取到任何详情")
                return

            # 4. 下单检查（通过 API 批量拉取，无需额外安装依赖）
            all_details = await check_orders_parallel(
                context, all_details, start_date, end_date,
            )
            records = all_details

            # 5. 生成 Excel
            query_range = f"{start_date} ~ {end_date}"
            excel_path, rows_data = generate_excel(
                all_details, output_dir,
                query_range=query_range,
                timestamp_str=timestamp_str,
            )

            # 6. 生成 HTML 报表（不影响主流程）
            try:
                from generate_html_report import generate_html_report as _gen_html
                html_path = os.path.join(output_dir, f"询价周报报表_{timestamp_str}.html")
                _gen_html(rows_data, query_range, html_path)
                logger.info("HTML 报表已生成: %s", html_path)
            except Exception as html_e:
                logger.warning("HTML 报表生成失败（不影响 Excel）: %s", html_e, exc_info=False)

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
    """仅统计模式主流程：读取已有 Excel → 按日期筛选 → 更新统计 Sheet。"""
    from core.excel_generator import (
        generate_excel, _update_summary_sheet, _fill_date_helper_column,
        _create_date_query_sheet_v2, _create_report_dashboard,
    )
    import openpyxl
    from excel_styles import (
        FONT_HEADER, FILL_HEADER, THIN_BORDER, ALIGN_HEADER,
    )
    from column_definitions import HEADERS

    output_dir = args.output_dir or os.getcwd()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 如果显式指定了输入文件，直接使用；否则自动查找
    if args.input_xlsx:
        file_path = os.path.abspath(args.input_xlsx)
    else:
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

    # 确保列头完整
    for col in range(1, len(HEADERS) + 1):
        existing = data_ws.cell(row=1, column=col).value
        header_value = HEADERS[col - 1]
        if existing is None or existing != header_value:
            cell = data_ws.cell(row=1, column=col, value=header_value)
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.border = THIN_BORDER
            cell.alignment = ALIGN_HEADER

    # 清除旧数据并补充辅助列
    import re
    for r in range(2, data_ws.max_row + 1):
        for c in range(15, 20):
            data_ws.cell(row=r, column=c).value = None
    _fill_date_helper_column(data_ws)

    # 按日期范围筛选
    filtered_rows: list = []
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

    # 更新 Sheet
    _update_summary_sheet(wb, data_ws, query_range, filtered_rows=filtered_rows)
    _fill_date_helper_column(data_ws)
    _create_date_query_sheet_v2(wb)
    _create_report_dashboard(wb)

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
    if total_module > 0:
        print(f"  组件总功率     {total_module:.2f} kW")
    if total_inverter > 0:
        print(f"  逆变器总功率   {total_inverter:.2f} kW")
    if total_battery > 0:
        print(f"  电池总容量     {total_battery:.2f} kWh")
    ratio_display = f"{total_module / total_inverter:.2f}" if total_inverter > 0 else "--"
    print(f"  容配比         {ratio_display}")
    print("")
    logger.info("统计 Sheet 已更新，保存至: %s", save_path)


# ==================== CLI ====================


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
    parser.add_argument("--input-xlsx", type=str, default=None,
                        help="仅统计模式下显式指定输入的询价汇总 Excel 文件路径（默认自动查找）")
    parser.add_argument("--this-month", action="store_true",
                        help="快捷统计本月（配合 --stats-only 使用）")
    args = parser.parse_args()

    configure_logging(args.verbose)

    if args.stats_only:
        stats_from_excel(args)
    else:
        import asyncio
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
