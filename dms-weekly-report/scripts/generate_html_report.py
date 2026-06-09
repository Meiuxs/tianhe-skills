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
from datetime import datetime
from typing import Any


# ==================== 列索引常量（集中定义，唯一引用点）====================
COL_FLOW_ID = 0            # 流程编号
COL_PROJECT_NAME = 1       # 项目名称
COL_PROVINCE = 4           # 省公司
COL_SALESPERSON = 5        # 业务员
COL_MODULE_POWER = 6       # 组件功率
COL_INVERTER_POWER = 7     # 逆变器功率
COL_BATTERY_CAPACITY = 8   # 电池容量
COL_SUBMIT_DATE = 11       # 提交日期
COL_ORDERED = 13           # 是否下单
COL_PROVINCE_APPROVER = 14 # 省公司审批人
COL_APPROVER = 16          # 采购审批人
COL_APPROVAL_STATUS = 17   # 审批状态
COL_FINAL_DATE = 18        # 最终审批日期


# ==================== 工具函数 ====================


def _safe_float(value: Any) -> float:
    """安全地将单元格值转为 float，处理字符串 "无" 等非数字值。"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


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
    if "询价汇总" not in wb.sheetnames:
        avail = ", ".join(wb.sheetnames)
        raise ValueError(
            f"工作簿中找不到「询价汇总」Sheet。可用 Sheet：{avail}"
        )
    ws = wb["询价汇总"]
    rows: list[list[Any]] = []
    for r in range(2, ws.max_row + 1):
        row: list[Any] = []
        for c in range(1, 20):
            row.append(ws.cell(r, c).value)
        rows.append(row)
    return rows


# ==================== 数据映射（唯一列索引引用点）====================


def compute_rows_detail(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """将原始数据行转为有名字典列表，供前端 ROWS_DETAIL 使用。

    所有列索引仅在此函数中出现一次，新增字段只需在此添加。
    """
    detail: list[dict[str, Any]] = []
    for row in rows:
        # 处理 float 类型的流程编号（Excel 数字格式存储），避免科学计数法
        raw_fid = row[COL_FLOW_ID]
        if raw_fid is None:
            continue
        if isinstance(raw_fid, float):
            try:
                fid = str(int(raw_fid))
            except (ValueError, OverflowError):
                continue
        else:
            fid = str(raw_fid)
        if not re.match(r"^\d{15,}$", fid):
            continue
        submit_time = str(row[COL_SUBMIT_DATE]) if row[COL_SUBMIT_DATE] else ""
        final_raw = str(row[COL_FINAL_DATE]) if len(row) > COL_FINAL_DATE and row[COL_FINAL_DATE] else ""
        detail.append({
            "flowId": fid,
            "projectName": str(row[COL_PROJECT_NAME]) if row[COL_PROJECT_NAME] else "",
            "province": str(row[COL_PROVINCE]) if row[COL_PROVINCE] else "",
            "salesperson": str(row[COL_SALESPERSON]) if row[COL_SALESPERSON] else "",
            "modulePower": _safe_float(row[COL_MODULE_POWER]) if len(row) > COL_MODULE_POWER else 0,
            "inverterPower": _safe_float(row[COL_INVERTER_POWER]) if len(row) > COL_INVERTER_POWER else 0,
            "batteryCapacity": _safe_float(row[COL_BATTERY_CAPACITY]) if len(row) > COL_BATTERY_CAPACITY else 0,
            "ordered": str(row[COL_ORDERED]) if row[COL_ORDERED] else "否",
            "submitDate": submit_time[:10] if len(submit_time) >= 10 else submit_time,
            "finalDate": final_raw[:10] if len(final_raw) >= 10 and final_raw not in ("--", "无", "") else "",
            "provinceApprover": (
                str(row[COL_PROVINCE_APPROVER])
                if len(row) > COL_PROVINCE_APPROVER
                and row[COL_PROVINCE_APPROVER]
                and row[COL_PROVINCE_APPROVER] != "--"
                else ""
            ),
            "procurementApprover": (
                str(row[COL_APPROVER])
                if len(row) > COL_APPROVER
                and row[COL_APPROVER]
                and row[COL_APPROVER] != "--"
                else ""
            ),
            "approvalStatus": (
                str(row[COL_APPROVAL_STATUS])
                if len(row) > COL_APPROVAL_STATUS
                and row[COL_APPROVAL_STATUS]
                and row[COL_APPROVAL_STATUS] != "--"
                else ""
            ),
        })
    return detail


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

    # 数据映射：Excel 原始行 → 有名字典列表
    rows_detail = compute_rows_detail(rows_data)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 替换纯文本标记（仅展示性字段，不涉及统计数据）
    replacements = {
        "REPORT_DATE_RANGE": query_range,
        "REPORT_GENERATED_AT": f"生成于 {now_str}",
        "DATA_SCOPE_TEXT": f"数据范围：{query_range} | 统计截止：{datetime.now().strftime('%Y-%m-%d')}",
        "FOOTER_TEXT": "询价周报报表 · 数据来源：DMS 流程中心 · 仅供内部参考",
    }
    html = _simple_replace(template, replacements)

    # 注入 ROWS_DETAIL（唯一数据源，前端实时派生所有聚合）
    html = _replace_json_field(html, "ROWS_DETAIL", rows_detail)

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
