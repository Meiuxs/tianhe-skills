"""Excel 报表生成模块。

生成包含以下 4 个 Sheet 的 Excel 报表：
  - 询价汇总：原始数据表
  - 询价统计：KPI 仪表盘式汇总
  - 日期查询：下拉交互式分时段统计
  - 数据看板：审批人统计/省公司排名/审批天数
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date as dt_date, datetime, timedelta
from typing import Any

import openpyxl
from openpyxl.styles import Border, Font, PatternFill, Side

from column_definitions import HEADERS, accumulate_power
from excel_styles import COLUMN_WIDTHS
from excel_styles import (
    Colors,
    THIN_BORDER, BOTTOM_BORDER, CARD_BORDER,
    FONT_TITLE, FONT_SECTION, FONT_SUBSECTION, FONT_HEADER,
    FONT_DATA, FONT_LABEL, FONT_KPI_BIG, FONT_KPI_MED,
    FONT_HINT, FONT_VALUE, FONT_GREEN, FONT_ORANGE,
    FILL_HEADER, FILL_LIGHT, FILL_VERY_LIGHT, FILL_CARD, FILL_WHITE,
    ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, ALIGN_HEADER, ALIGN_DATA,
    ROW_HEIGHT_TITLE, ROW_HEIGHT_SECTION, ROW_HEIGHT_DATA, ROW_HEIGHT_HEADER,
    apply_header_style, apply_data_row, apply_accent_row, apply_status_cell,
    write_section_title, write_kpi_card,
)

logger = logging.getLogger("dms_report")


def generate_excel(
    records: list[Any],
    output_dir: str | None = None,
    query_range: str = "",
    timestamp_str: str | None = None,
) -> tuple[str, list[list[Any]]]:
    """生成格式化 Excel 文件（包含 4 个 Sheet）。

    Args:
        records: FlowRecord 对象列表。
        output_dir: 输出目录，默认当前工作目录。
        query_range: 查询范围字符串，如 "2026-06-01 ~ 2026-06-07"。
        timestamp_str: 时间戳字符串，默认自动生成。

    Returns:
        (文件路径, 行数据列表)
    """
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
    rows_data = _build_rows_data(records)

    if os.path.exists(file_path):
        try:
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
            rows_data = _deduplicate_rows(wb, rows_data)
            next_row = ws.max_row + 1
        except Exception as e:
            logger.warning("Excel 文件读取失败 (%s)，将重新创建: %s", file_path, e)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "询价汇总"
            apply_header_style(ws, 1, HEADERS)
            for i, w in enumerate(COLUMN_WIDTHS):
                ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
            ws.row_dimensions[1].height = ROW_HEIGHT_HEADER
            next_row = 2
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

    # 更新增强 Sheet
    _update_summary_sheet(wb, ws, query_range)
    _fill_date_helper_column(ws)
    _create_date_query_sheet_v2(wb)
    _create_report_dashboard(wb)

    try:
        wb.save(file_path)
    except PermissionError:
        backup_path = os.path.join(output_dir, f"询价汇总_{ts}_backup.xlsx")
        logger.warning("无法保存到 %s（文件被占用），尝试备用路径: %s", file_path, backup_path)
        wb.save(backup_path)
        file_path = backup_path
    except OSError as e:
        logger.error("保存 Excel 失败: %s", e)
        raise

    logger.info("Excel 已保存: %s (共 %d 条记录)", file_path, len(rows_data))
    return file_path, rows_data


# ==================== 辅助函数 ====================


def _build_rows_data(records: list) -> list[list[Any]]:
    """从 FlowRecord 列表构建 19 列行数据。"""
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
    return rows_data


def _deduplicate_rows(wb: openpyxl.Workbook, rows_data: list[list[Any]]) -> list[list[Any]]:
    """去重：读取已有流程编号，过滤掉重复行。"""
    ws = wb.active
    existing_ids: set[str] = set()
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0] and re.match(r"^\d{15,}$", str(row[0])):
            existing_ids.add(str(row[0]))

    new_rows = [r for r in rows_data if str(r[0]) not in existing_ids]
    skipped = len(rows_data) - len(new_rows)
    if skipped:
        logger.info("跳过 %d 条重复记录", skipped)
    return new_rows


def _fill_date_helper_column(ws: Any) -> None:
    """补充询价汇总Sheet的T列（日期序列号，供Excel公式使用），然后隐藏该列。"""
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


# ==================== 统计 Sheet ====================


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

    # 计算统计数据
    total_projects = 0
    ordered_count = 0
    not_ordered_count = 0
    salesperson_set: set[str] = set()
    valid_rows: list = []

    source_rows = filtered_rows if filtered_rows is not None else data_ws.iter_rows(min_row=2, values_only=True)

    for row in source_rows:
        flow_id = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", flow_id):
            continue
        total_projects += 1
        valid_rows.append(row)
        ordered = str(row[13] if row[13] else "")
        if ordered == "是":
            ordered_count += 1
        else:
            not_ordered_count += 1
        sp = str(row[5] if row[5] else "")
        if sp not in ("--", "无", ""):
            salesperson_set.add(sp)

    total_module, total_inverter, total_battery = accumulate_power(valid_rows)

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
    r = write_section_title(ws, r, 1, "询价概览", merge_end_col=3)

    kpis_1 = [
        ("询价项目总数", f"{total_projects}", "个", FONT_KPI_BIG),
        ("涉及业务员", f"{len(salesperson_set)}", "人" if salesperson_set else "", FONT_KPI_MED),
        ("已下单项目", f"{ordered_count}", "个", FONT_GREEN),
        ("未下单项目", f"{not_ordered_count}", "个", FONT_ORANGE),
    ]
    for i, (label, value, unit, vf) in enumerate(kpis_1):
        write_kpi_card(ws, r + i, 1, label, value, unit, vf)

    r += len(kpis_1) + 2

    # ---- 区域2：功率容量统计 —— 每个 KPI 一行，从 A 列开始 ----
    r = write_section_title(ws, r, 1, "功率容量统计", merge_end_col=3)

    module_display = f"{total_module:,.2f}" if total_module > 0 else "0"
    inverter_display = f"{total_inverter:,.2f}" if total_inverter > 0 else "0"
    battery_display = f"{total_battery:,.2f}" if total_battery > 0 else "0"
    ratio_display = f"{total_module / total_inverter:.2f}" if total_inverter > 0 else "--"

    kpis_2 = [
        ("组件总功率", module_display, "kW", FONT_KPI_BIG),
        ("逆变器总功率", inverter_display, "kW", FONT_KPI_MED),
        ("电池总容量", battery_display, "kWh", FONT_KPI_MED),
        ("容配比(组件/逆变器)", ratio_display, "", FONT_VALUE),
    ]
    for i, (label, value, unit, vf) in enumerate(kpis_2):
        write_kpi_card(ws, r + i, 1, label, value, unit, vf)

    r += len(kpis_2) + 2
    # 页脚说明
    ws.cell(r, 1, f"数据范围：全部历史数据 | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}").font = FONT_HINT
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)


# ==================== 日期查询 Sheet ====================


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
        cnt = 0
        mod = 0.0
        inv = 0.0
        bat = 0.0
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

    # 筛选标签和下拉（从 B2 开始）
    for c in range(1, 4):
        ws.cell(r, c).fill = FILL_WHITE
        ws.cell(r, c).border = THIN_BORDER
    ws.cell(r, 1, "时间段筛选：").font = FONT_LABEL
    ws.cell(r, 1).alignment = ALIGN_LEFT
    ws.cell(r, 2, "全部").font = Font(bold=True, size=10, color=Colors.PRIMARY_BLUE, name="微软雅黑")
    ws.cell(r, 2).border = Border(
        left=Side("medium", color=Colors.PRIMARY_BLUE),
        right=Side("medium", color=Colors.PRIMARY_BLUE),
        top=Side("medium", color=Colors.PRIMARY_BLUE),
        bottom=Side("medium", color=Colors.PRIMARY_BLUE),
    )
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
    r = write_section_title(ws, r, 1, "预计算结果", merge_end_col=7)

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
    r = write_section_title(ws, r, 1, "当前选择结果", merge_end_col=7)

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
        ws.cell(r, 2).font = Font(bold=True, size=10, color=Colors.TEXT_PRIMARY, name="微软雅黑")
        ws.cell(r, 2).border = THIN_BORDER
        ws.cell(r, 2).alignment = ALIGN_CENTER
        ws.cell(r, 2).number_format = nf
        ws.row_dimensions[r].height = ROW_HEIGHT_DATA
        r += 1

    r += 2
    # 使用说明
    r = write_section_title(ws, r, 1, "使用说明", merge_end_col=7)
    for tip in [
        "1. 点击 B2 → 从下拉选择预设时间段",
        "2. 预计算表格展示所有周期数据",
        "3. '当前选择结果' 随下拉实时变化",
        "4. 如需最新数据，重新运行周报脚本",
    ]:
        ws.cell(r, 1, tip).font = FONT_HINT
        r += 1


# ==================== 数据看板 Sheet ====================


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
    r = write_section_title(ws, r, 1, "王剑采购审批统计", merge_end_col=7)

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
        ("审批通过", wangjian_count, "次", FONT_GREEN),
        ("经手总次数", wangjian_total, "次", FONT_KPI_MED),
        ("通过率", rate, "", FONT_VALUE),
    ]
    for i, (label, value, unit, vf) in enumerate(cards):
        col = 1 + i * 2  # A(1), C(3), E(5) — 从 A 列开始
        write_kpi_card(ws, r, col, label, value, unit, vf, alt_fill=True)
    r += 2

    # ===== 区域2：省公司询价排名 =====
    r = write_section_title(ws, r, 1, "省公司询价排名", merge_end_col=7)

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
    r = write_section_title(ws, r, 1, "询价到审批完成天数", merge_end_col=7)

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
            try:
                sd = datetime.strptime(sm.group(1), "%Y-%m-%d")
                fd = datetime.strptime(fm.group(1), "%Y-%m-%d")
                delta = (fd - sd).days
                if delta >= 0:
                    days_list.append(delta)
            except ValueError:
                pass

    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0
    total_with_both = len(days_list)

    day_cards = [
        ("平均天数", avg_days, "天", FONT_VALUE),
        ("最短天数", min(days_list) if days_list else 0, "天", FONT_GREEN),
        ("最长天数", max(days_list) if days_list else 0, "天", FONT_ORANGE),
        ("统计样本数", total_with_both, "条", FONT_KPI_MED),
    ]
    for i, (label, value, unit, vf) in enumerate(day_cards):
        col = 1 + i * 2  # A(1), C(3), E(5), G(7)
        write_kpi_card(ws, r, col, label, value, unit, vf, alt_fill=True)
    r += 2

    # 说明
    r = write_section_title(ws, r, 1, "说明", merge_end_col=7)
    for tip in [
        "1. 王剑审批统计基于采购审批节点数据",
        "2. 省公司排名按询价次数降序排列",
        "3. 审批天数 = 审批完成时间 - 发起人提交审核时间",
        "4. 如需最新数据，重新运行周报脚本即可",
    ]:
        ws.cell(r, 1, tip).font = FONT_HINT
        r += 1
