"""从 xlsx 数据生成 HTML 周报报表。

用法：
    # 命令行
    python generate_html_report.py --xlsx 询价汇总.xlsx --output 报告.html --range "2026-06-01 ~ 2026-06-07"

    # 作为模块
    from generate_html_report import generate_html_report
    generate_html_report(rows_data, "2026-06-01 ~ 2026-06-07", "report.html")
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any


# ==================== 模板替换 ====================


def _simple_replace(template: str, replacements: dict[str, str]) -> str:
    """将模板中的 {{KEY}} 替换为对应的 value。"""
    result = template
    for key, value in replacements.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


def _replace_json_field(template: str, field_name: str, data: Any) -> str:
    """将模板中的 {{FIELD_NAME_JSON}} 替换为 JSON 字符串。"""
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return template.replace("{{" + field_name + "_JSON}}", json_str)


# ==================== 数据读取 ====================


def read_rows_from_xlsx(xlsx_path: str) -> list[list[Any]]:
    """从 xlsx 的「询价汇总」Sheet 读取数据行（跳过表头）。"""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb["询价汇总"]
    rows: list[list[Any]] = []
    for r in range(2, ws.max_row + 1):
        row: list[Any] = []
        for c in range(1, 20):
            row.append(ws.cell(r, c).value)
        rows.append(row)
    return rows


# ==================== 数据统计 ====================


def compute_kpis(rows: list[list[Any]]) -> dict[str, Any]:
    """从 rows_data 计算 KPI 指标，返回模板替换字典。"""
    total_module = 0.0
    total_inverter = 0.0
    total_battery = 0.0
    total_projects = 0
    ordered_count = 0
    not_ordered_count = 0
    salesperson_set: set[str] = set()

    for row in rows:
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

    ratio = round(total_module / total_inverter, 2) if total_inverter > 0 else 0

    return {
        "total_projects": total_projects,
        "total_salespersons": len(salesperson_set),
        "ordered_count": ordered_count,
        "not_ordered_count": not_ordered_count,
        "module_power": f"{total_module:,.2f}" if total_module > 0 else "0",
        "inverter_power": f"{total_inverter:,.2f}" if total_inverter > 0 else "0",
        "battery_capacity": f"{total_battery:,.2f}" if total_battery > 0 else "0",
        "ratio": f"{ratio:.2f}" if total_inverter > 0 else "--",
    }


def compute_period_data(rows: list[list[Any]]) -> dict[str, dict[str, float | int]]:
    """计算 5 个时间段的统计数据（全部/本周/本月/上月/本季度）。"""
    from datetime import date as dt_date

    def _excel_serial(d: dt_date) -> int:
        return d.toordinal() - 693594

    def _parse_date(l_val: Any) -> int | None:
        if l_val:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(l_val))
            if m:
                return _excel_serial(dt_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        return None

    today = dt_date.today()
    wd = today.weekday()
    m_start = dt_date(today.year, today.month, 1)

    periods: dict[str, tuple[int, int]] = {}
    periods["全部"] = (_excel_serial(dt_date(2000, 1, 1)), _excel_serial(dt_date(2099, 12, 31)))
    periods["本周"] = (_excel_serial(dt_date.fromordinal(today.toordinal() - wd)), _excel_serial(today))
    periods["本月"] = (_excel_serial(m_start), _excel_serial(today))
    if today.month == 1:
        periods["上月"] = (_excel_serial(dt_date(today.year - 1, 12, 1)), _excel_serial(dt_date(today.year - 1, 12, 31)))
    else:
        lm = dt_date(today.year, today.month - 1, 1)
        lme = dt_date(today.year, today.month, 1) - dt_date.resolution
        periods["上月"] = (_excel_serial(lm), _excel_serial(lme))
    qs = (today.month - 1) // 3 * 3 + 1
    periods["本季度"] = (_excel_serial(dt_date(today.year, qs, 1)), _excel_serial(today))

    result: dict[str, dict[str, float | int]] = {}
    for name, (s, e) in periods.items():
        cnt = 0
        mod = 0.0
        inv = 0.0
        bat = 0.0
        for row in rows:
            fid = str(row[0]) if row[0] else ""
            if not re.match(r"^\d{15,}$", fid):
                continue
            o = _parse_date(row[11] if len(row) > 11 else None)
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
        result[name] = {
            "count": cnt,
            "module": round(mod, 2),
            "inverter": round(inv, 2),
            "battery": round(bat, 2),
            "ratio": ratio,
        }
    return result


def compute_daily_data(rows: list[list[Any]]) -> dict[str, dict[str, int | float]]:
    """按日期统计每日询价项目数和容量，用于每日趋势折线图。"""
    from collections import defaultdict

    daily: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"count": 0, "module": 0.0, "inverter": 0.0, "battery": 0.0}
    )
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        m = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
        if m:
            date_str = m.group(1)
        else:
            continue

        daily[date_str]["count"] += 1
        if len(row) > 6 and isinstance(row[6], (int, float)):
            daily[date_str]["module"] += float(row[6])
        if len(row) > 7 and isinstance(row[7], (int, float)):
            daily[date_str]["inverter"] += float(row[7])
        if len(row) > 8 and isinstance(row[8], (int, float)):
            daily[date_str]["battery"] += float(row[8])

    sorted_dates = sorted(daily.keys())
    result: dict[str, dict[str, int | float]] = {}
    for date_str in sorted_dates:
        d = daily[date_str]
        result[date_str] = {
            "count": d["count"],
            "module": round(d["module"], 2),
            "inverter": round(d["inverter"], 2),
            "battery": round(d["battery"], 2),
        }
    return result


def compute_wangjian_stats(rows: list[list[Any]]) -> dict[str, Any]:
    """统计王剑采购审批情况。"""
    approved = 0
    total = 0
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        proc = str(row[16] if len(row) > 16 and row[16] else "")
        status_val = str(row[17] if len(row) > 17 and row[17] else "")
        if "王剑" in proc:
            total += 1
            if "审批通过" in status_val:
                approved += 1
    rate = f"{int(approved / total * 100)}%" if total > 0 else "--"
    return {"approved": approved, "total": total, "rate": rate}


def compute_province_ranking(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """按省公司统计询价次数和组件功率，降序排列。"""
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        pv = str(row[4] if len(row) > 4 and row[4] else "")
        if pv in ("--", "无", ""):
            continue
        g = float(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else 0
        if pv not in stats:
            stats[pv] = {"cnt": 0, "module": 0.0}
        stats[pv]["cnt"] += 1
        stats[pv]["module"] += g

    sorted_prov = sorted(stats.items(), key=lambda x: -x[1]["cnt"])
    ranking: list[dict[str, Any]] = []
    for rank, (pv, data) in enumerate(sorted_prov, 1):
        ranking.append({
            "rank": rank,
            "province": pv,
            "count": data["cnt"],
            "module": round(data["module"], 2),
        })
    return ranking


def compute_approval_days(rows: list[list[Any]]) -> dict[str, Any]:
    """计算询价到审批完成的平均/最短/最长天数。"""
    days_list: list[int] = []
    for row in rows:
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

    return {
        "avg": round(sum(days_list) / len(days_list), 1) if days_list else 0,
        "min": min(days_list) if days_list else 0,
        "max": max(days_list) if days_list else 0,
        "sample_count": len(days_list),
    }


def compute_approval_by_dimension(
    rows: list[list[Any]], dimension_col: int
) -> list[dict[str, Any]]:
    """按指定维度（省公司=4 或 业务员=5）统计审批耗时对比数据。"""
    from datetime import datetime as dt_dt

    stats: dict[str, list[int]] = {}
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        key = str(row[dimension_col] if len(row) > dimension_col and row[dimension_col] else "")
        if key in ("--", "无", ""):
            continue
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        final_time = str(row[18] if len(row) > 18 and row[18] else "")
        if submit_time in ("--", "") or final_time in ("--", ""):
            continue
        sm = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
        fm = re.match(r"(\d{4}-\d{2}-\d{2})", final_time)
        if sm and fm:
            try:
                sd = dt_dt.strptime(sm.group(1), "%Y-%m-%d")
                fd = dt_dt.strptime(fm.group(1), "%Y-%m-%d")
                delta = (fd - sd).days
                if delta >= 0:
                    if key not in stats:
                        stats[key] = []
                    stats[key].append(delta)
            except ValueError:
                pass

    result: list[dict[str, Any]] = []
    for key, days in stats.items():
        result.append({
            "name": key,
            "avg": round(sum(days) / len(days), 1),
            "min": min(days),
            "max": max(days),
            "count": len(days),
        })
    result.sort(key=lambda x: -x["avg"])
    return result


def compute_approver_list(rows: list[list[Any]]) -> list[str]:
    """提取所有唯一的采购审批人列表。"""
    approvers: set[str] = set()
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        proc = str(row[16] if len(row) > 16 and row[16] else "")
        if proc and proc not in ("--", "无", ""):
            approvers.add(proc)
    return sorted(approvers)


def compute_rows_detail(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """将原始数据行转为可供前端表格展示的字典列表（明细下钻用）。"""
    detail: list[dict[str, Any]] = []
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        detail.append({
            "flowId": fid,
            "projectName": str(row[1]) if row[1] else "",
            "province": str(row[4]) if row[4] else "",
            "salesperson": str(row[5]) if row[5] else "",
            "modulePower": float(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else 0,
            "inverterPower": float(row[7]) if len(row) > 7 and isinstance(row[7], (int, float)) else 0,
            "batteryCapacity": float(row[8]) if len(row) > 8 and isinstance(row[8], (int, float)) else 0,
            "ordered": str(row[13]) if row[13] else "否",
            "submitDate": submit_time[:10] if len(submit_time) >= 10 else submit_time,
            "provinceApprover": str(row[14]) if len(row) > 14 and row[14] and row[14] != "--" else "",
            "procurementApprover": str(row[16]) if len(row) > 16 and row[16] and row[16] != "--" else "",
            "approvalStatus": str(row[17]) if len(row) > 17 and row[17] and row[17] != "--" else "",
        })
    return detail


def compute_approver_stats(
    rows: list[list[Any]], approver_name: str | None = None
) -> dict[str, Any]:
    """统计指定审批人的采购审批情况。approver_name 为 None 时统计全部。"""
    approved = 0
    total = 0
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        proc = str(row[16] if len(row) > 16 and row[16] else "")
        status_val = str(row[17] if len(row) > 17 and row[17] else "")
        if approver_name and approver_name not in proc:
            continue
        total += 1
        if "审批通过" in status_val:
            approved += 1
    rate = f"{int(approved / total * 100)}%" if total > 0 else "--"
    return {"approved": approved, "total": total, "rate": rate, "name": approver_name or "全部"}


# ==================== 主函数 ====================


def generate_html_report(
    rows_data: list[list[Any]],
    query_range: str,
    output_path: str,
    template_path: str | None = None,
) -> str:
    """从 rows_data 生成 HTML 报表文件，返回输出路径。

    Args:
        rows_data: 询价数据行，每行 19 列。
        query_range: 查询范围文本（如 "2026-06-01 ~ 2026-06-07"）。
        output_path: 输出 HTML 文件路径。
        template_path: 模板文件路径，默认使用 references/report_template.html。

    Returns:
        输出文件的路径。
    """
    if template_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, "..", "references", "report_template.html")

    # 读取模板
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # 计算所有统计数据
    kpis = compute_kpis(rows_data)
    period_data = compute_period_data(rows_data)
    wangjian = compute_wangjian_stats(rows_data)
    province_ranking = compute_province_ranking(rows_data)
    approval_days = compute_approval_days(rows_data)
    daily_data = compute_daily_data(rows_data)
    approval_by_province = compute_approval_by_dimension(rows_data, 4)
    approval_by_salesperson = compute_approval_by_dimension(rows_data, 5)
    approver_list = compute_approver_list(rows_data)
    rows_detail = compute_rows_detail(rows_data)
    default_approver = "王剑"
    default_approver_stats = compute_approver_stats(rows_data, default_approver)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 构建替换映射
    replacements = {
        "REPORT_DATE_RANGE": query_range,
        "REPORT_GENERATED_AT": f"生成于 {now_str}",
        "KPI_TOTAL_PROJECTS": str(kpis["total_projects"]),
        "KPI_TOTAL_SALESPERSONS": str(kpis["total_salespersons"]),
        "KPI_ORDERED_COUNT": str(kpis["ordered_count"]),
        "KPI_NOT_ORDERED_COUNT": str(kpis["not_ordered_count"]),
        "KPI_MODULE_POWER": str(kpis["module_power"]),
        "KPI_INVERTER_POWER": str(kpis["inverter_power"]),
        "KPI_BATTERY_CAPACITY": str(kpis["battery_capacity"]),
        "KPI_RATIO": str(kpis["ratio"]),
        "DATA_SCOPE_TEXT": f"数据范围：{query_range} | 统计截止：{datetime.now().strftime('%Y-%m-%d')}",
        "WANGJIAN_APPROVED": str(wangjian["approved"]),
        "WANGJIAN_TOTAL": str(wangjian["total"]),
        "WANGJIAN_RATE": wangjian["rate"],
        "DAYS_AVG": str(approval_days["avg"]),
        "DAYS_MIN": str(approval_days["min"]),
        "DAYS_MAX": str(approval_days["max"]),
        "DAYS_SAMPLE_COUNT": str(approval_days["sample_count"]),
        "FOOTER_TEXT": "询价周报报表 · 数据来源：DMS 流程中心 · 仅供内部参考",
    }

    # 执行替换
    html = _simple_replace(template, replacements)
    html = _replace_json_field(html, "PERIOD_DATA", period_data)
    html = _replace_json_field(html, "PROVINCE_DATA", province_ranking)
    html = _replace_json_field(html, "DAILY_DATA", daily_data)
    html = _replace_json_field(html, "APPROVAL_BY_PROVINCE", approval_by_province)
    html = _replace_json_field(html, "APPROVAL_BY_SALESPERSON", approval_by_salesperson)
    html = _replace_json_field(html, "APPROVER_LIST", approver_list)
    html = _replace_json_field(html, "ROWS_DETAIL", rows_detail)

    # 构造图表需要的 KPI 原始数值（不含千分位，JS 端做格式化）
    kpi_data = {
        "orderedCount": kpis["ordered_count"],
        "notOrderedCount": kpis["not_ordered_count"],
        "modulePower": float(kpis["module_power"].replace(",", "")) if isinstance(kpis["module_power"], str) and kpis["module_power"] != "0" else 0,
        "inverterPower": float(kpis["inverter_power"].replace(",", "")) if isinstance(kpis["inverter_power"], str) and kpis["inverter_power"] != "0" else 0,
        "batteryCapacity": float(kpis["battery_capacity"].replace(",", "")) if isinstance(kpis["battery_capacity"], str) and kpis["battery_capacity"] != "0" else 0,
        "wangjianApproved": wangjian["approved"],  # 保留旧 key 兼容
        "wangjianTotal": wangjian["total"],
        "approverApproved": default_approver_stats["approved"],
        "approverTotal": default_approver_stats["total"],
        "approverRate": default_approver_stats["rate"],
        "approverName": default_approver_stats["name"],
        "daysAvg": approval_days["avg"],
        "daysMin": approval_days["min"],
        "daysMax": approval_days["max"],
    }
    html = _replace_json_field(html, "KPI_DATA", kpi_data)

    # 输出
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


# ==================== CLI 入口 ====================


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="从 xlsx 生成 HTML 周报报表")
    parser.add_argument("--xlsx", required=True, help="输入的 xlsx 文件路径")
    parser.add_argument("--output", default="", help="输出的 html 文件路径（默认自动带时间戳）")
    parser.add_argument("--range", default="", help="查询范围文本，如 '2026-06-01 ~ 2026-06-07'")
    args = parser.parse_args()

    rows = read_rows_from_xlsx(args.xlsx)
    query_range = args.range or f"{datetime.now().strftime('%Y-%m-%d')} 数据"
    if not args.output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"./询价周报报表_{ts}.html"
    output = generate_html_report(rows, query_range, args.output)
    print(f"HTML 报表已生成：{output}")


if __name__ == "__main__":
    main()
