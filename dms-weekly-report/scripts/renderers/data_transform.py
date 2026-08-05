"""Excel 原始数据行 → 有名字典列表的数据映射层。

架构定位：
  本模块是 generate_html_report.py 的纯函数拆分，职责仅为
  「将原始行列表（list[list[Any]]）转换为前端可用的命名 dict 列表」。

  所有列索引仅在此模块中出现一次，新增字段只需在此添加。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, TypedDict

from column_definitions import (
    COL_FLOW_ID, COL_PROJECT_NAME, COL_PROVINCE, COL_SALESPERSON,
    COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH,
    COL_SUBMIT_TIME, COL_IS_VALID, COL_FLOW_STATUS,
    COL_NEGOTIATION_PROCESSOR, COL_NEGOTIATION_STATUS,
    COL_REGION_TECH_PROCESSOR, COL_REGION_TECH_STATUS, COL_REGION_TECH_APPROVAL_TIME,
    COL_PROVINCE_PROCESSOR, COL_PROVINCE_STATUS,
    COL_FINAL_APPROVAL_TIME,
    FLOW_ID_PATTERN,
)


class RowDetail(TypedDict):
    """单条询价数据行的类型定义，对应前端 ROWS_DETAIL 数组元素。

    注意：实际输出使用 camelCase 键（与前端 JS 保持一致），
    此处 TypedDict 也使用 camelCase 以匹配实际数据。
    """
    flowId: str
    projectName: str
    province: str
    salesperson: str
    modulePower: float
    inverterPower: float
    batteryCapacity: float
    isValid: str
    isInvalid: bool
    submitDate: str
    finalDate: str
    negotiationApprover: str
    negotiationStatus: str
    regionTechApprover: str
    regionTechStatus: str
    regionTechApprovalTime: str
    provinceApprover: str
    provinceStatus: str
    flowStatus: str


# ==================== 工具函数 ====================


def _format_datetime(value: Any) -> str:
    """将单元格日期值格式化为 YYYY-MM-DD HH:MM:SS 字符串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    s = str(value)
    # 尝试截取常见日期时间格式 (YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DDTHH:MM:SS)
    if len(s) >= 19 and s[4] == "-" and s[7] == "-":
        return s[:19].replace("T", " ")
    return s


def _clean(row: list[Any], col: int) -> str:
    """安全地取单元格字符串值：越界保护 + 判空 + 去除 "--" 占位符。

    返回空串表示无有效值（列缺失、空、或为占位符）。
    """
    if col < 0 or col >= len(row):
        return ""
    v = row[col]
    if v is None or v == "--":
        return ""
    return str(v)


def _safe_float(value: Any) -> float:
    """安全地将单元格值转为 float，处理字符串 "无" 等非数字值。"""
    if isinstance(value, (int, float)):
        result = float(value)
        if math.isinf(result) or math.isnan(result):
            return 0.0
        return result
    if isinstance(value, str):
        try:
            result = float(value)
            if math.isinf(result) or math.isnan(result):
                return 0.0
            return result
        except ValueError:
            return 0.0
    return 0.0


# ==================== 数据映射（唯一列索引引用点）====================


# ==================== 聚合统计 ====================


def compute_aggregations(rows_detail: list[RowDetail]) -> dict[str, Any]:
    """预计算常用聚合统计，减轻前端 JS 计算负担。

    返回的 dict 包含：
      - totalProjects: 总项目数
      - validProjects: 有效询价数
      - invalidProjects: 无效/作废询价数
      - totalModuleKw: 组件总功率
      - totalInverterKw: 逆变器总功率
      - totalBatteryKwh: 电池总容量
      - moduleToInverterRatio: 容配比
      - provinceSummary: 按省份聚合 {省份名: {count, moduleKw, inverterKw, batteryKwh}}
    """
    total = len(rows_detail)
    valid = sum(1 for r in rows_detail if r["isValid"] == "是")
    invalid = total - valid
    module_kw = sum(r["modulePower"] for r in rows_detail)
    inverter_kw = sum(r["inverterPower"] for r in rows_detail)
    battery_kwh = sum(r["batteryCapacity"] for r in rows_detail)

    province_summary: dict[str, dict[str, Any]] = {}
    for r in rows_detail:
        p = r["province"] or "未知"
        if p not in province_summary:
            province_summary[p] = {"count": 0, "moduleKw": 0.0, "inverterKw": 0.0, "batteryKwh": 0.0}
        province_summary[p]["count"] += 1
        province_summary[p]["moduleKw"] += r["modulePower"]
        province_summary[p]["inverterKw"] += r["inverterPower"]
        province_summary[p]["batteryKwh"] += r["batteryCapacity"]

    # 省份值四舍五入
    for p_data in province_summary.values():
        p_data["moduleKw"] = round(p_data["moduleKw"], 2)
        p_data["inverterKw"] = round(p_data["inverterKw"], 2)
        p_data["batteryKwh"] = round(p_data["batteryKwh"], 2)

    return {
        "totalProjects": total,
        "validProjects": valid,
        "invalidProjects": invalid,
        "totalModuleKw": round(module_kw, 2),
        "totalInverterKw": round(inverter_kw, 2),
        "totalBatteryKwh": round(battery_kwh, 2),
        "moduleToInverterRatio": round(module_kw / inverter_kw, 2) if inverter_kw else 0.0,
        "provinceSummary": dict(sorted(province_summary.items(), key=lambda x: -x[1]["count"])),
    }


def compute_rows_detail(rows: list[list[Any]]) -> list[RowDetail]:
    """将原始数据行转为有名字典列表，供前端 ROWS_DETAIL 使用。

    所有列索引仅在此函数中出现一次，新增字段只需在此添加。
    """
    detail: list[RowDetail] = []
    for row in rows:
        raw_fid = row[COL_FLOW_ID]
        if raw_fid is None:
            continue
        if isinstance(raw_fid, float):
            # Excel 以 IEEE 754 双精度（约 15-16 位有效数字）存储数值型单元格。
            # 当流程编号 > 2^53（~9e15）时，最后几位不再精确。
            # 例如：12345678901234567890（20位）→ int(float) → 12345678901234567168。
            # 修复方法：在 Excel 中将该列格式设为「文本」后重新导出 xlsx。
            try:
                fid = str(int(raw_fid))
            except (ValueError, OverflowError):
                continue
        else:
            fid = str(raw_fid)
        if not re.match(FLOW_ID_PATTERN, fid):
            continue
        submit_time = _format_datetime(row[COL_SUBMIT_TIME])
        final_raw = _format_datetime(row[COL_FINAL_APPROVAL_TIME])
        is_valid = str(row[COL_IS_VALID]) if row[COL_IS_VALID] else "否"
        # len(row) > COL_FLOW_STATUS 等价于 len(row) >= COL_FLOW_STATUS + 1（索引从0开始）
        flow_status = str(row[COL_FLOW_STATUS]) if len(row) > COL_FLOW_STATUS and row[COL_FLOW_STATUS] else ""
        detail.append({
            "flowId": fid,
            "projectName": str(row[COL_PROJECT_NAME]) if row[COL_PROJECT_NAME] else "",
            "province": str(row[COL_PROVINCE]) if row[COL_PROVINCE] else "",
            "salesperson": str(row[COL_SALESPERSON]) if row[COL_SALESPERSON] else "",
            "modulePower": _safe_float(row[COL_MODULE_KW]),
            "inverterPower": _safe_float(row[COL_INVERTER_KW]),
            "batteryCapacity": _safe_float(row[COL_BATTERY_KWH]),
            "isValid": is_valid,
            "isInvalid": "作废" in flow_status,
            "submitDate": submit_time[:10] if len(submit_time) >= 10 else submit_time,
            "finalDate": final_raw[:10] if len(final_raw) >= 10 and final_raw not in ("--", "无", "") else "",
            "negotiationApprover": _clean(row, COL_NEGOTIATION_PROCESSOR),
            "negotiationStatus": _clean(row, COL_NEGOTIATION_STATUS),
            "regionTechApprover": _clean(row, COL_REGION_TECH_PROCESSOR),
            "regionTechStatus": _clean(row, COL_REGION_TECH_STATUS),
            "regionTechApprovalTime": _clean(row, COL_REGION_TECH_APPROVAL_TIME),
            "provinceApprover": _clean(row, COL_PROVINCE_PROCESSOR),
            "provinceStatus": _clean(row, COL_PROVINCE_STATUS),
            "flowStatus": flow_status,
        })
    return detail
