"""BOM 物料解析模块。

从 DMS 物料名称中提取功率、容量等参数，
计算组件总功率、逆变器总功率、电池总容量。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class BOMItem:
    """BOM 清单条目——从 DMS 详情页的物料表格中提取。"""
    code: str
    name: str
    qty: float | int
    unit: str


_RE_POWER_UNDERSCORE = re.compile(r"_(\d+(?:\.\d+)?)_?([kK]?[Ww])\s*_")
_RE_POWER_FALLBACK = re.compile(r"(\d+(?:\.\d+)?)\s*(k?W)(?![a-zA-Z])", re.IGNORECASE)
_RE_CAPACITY_UNDERSCORE = re.compile(r"_(\d+(?:\.\d+)?)_?([kK]?[Ww][Hh])\s*_")
_RE_CAPACITY_FALLBACK = re.compile(r"(\d+(?:\.\d+)?)\s*(k?Wh)(?![a-zA-Z])", re.IGNORECASE)


def extract_power(name: str) -> float | None:
    """从物料名称中提取功率（kW）。"""
    if not name:
        return None

    m = _RE_POWER_UNDERSCORE.search(name)
    if m:
        unit_lower = m.group(2).lower()
        if unit_lower == "w" or unit_lower == "kw":
            val = float(m.group(1))
            return val / 1000 if unit_lower == "w" else val

    m = _RE_POWER_FALLBACK.search(name)
    if m and "h" not in m.group(2).lower():
        val = float(m.group(1))
        return val / 1000 if m.group(2).lower() == "w" else val

    return None


def extract_capacity(name: str) -> float | None:
    """从物料名称中提取容量（kWh）。"""
    if not name:
        return None

    m = _RE_CAPACITY_UNDERSCORE.search(name)
    if m:
        val = float(m.group(1))
        return val / 1000 if m.group(2).lower() == "wh" else val

    m = _RE_CAPACITY_FALLBACK.search(name)
    if m:
        val = float(m.group(1))
        return val / 1000 if m.group(2).lower() == "wh" else val

    return None


def calc_module_power(items: list[BOMItem]) -> float:
    total = 0.0
    for item in items:
        name_lower = item.name.lower()
        is_module = any(x in item.name for x in ["销售组件", "组件", "panel"]) or \
                   any(x in name_lower for x in ["module", "pv"])
        if is_module:
            kw = extract_power(item.name)
            if kw is not None:
                total += kw * item.qty
    return round(total, 2)


def calc_inverter_power(items: list[BOMItem]) -> float:
    total = 0.0
    for item in items:
        if "逆变器" in item.name or "inverter" in item.name.lower():
            kw = extract_power(item.name)
            if kw is not None:
                total += kw * item.qty
    return round(total, 2)


def calc_battery_capacity(items: list[BOMItem]) -> float:
    total = 0.0
    for item in items:
        if "电池" in item.name or "储能" in item.name or "battery" in item.name.lower():
            kwh = extract_capacity(item.name)
            if kwh is not None:
                total += kwh * item.qty
    return round(total, 2)


def build_remark(items: list[BOMItem]) -> str:
    has_grid_cabinet = any("并网柜" in item.name for item in items)
    has_grid_box = any("并网箱" in item.name for item in items)
    has_hybrid_inverter = any("光储逆变器" in item.name for item in items)
    has_dc_cable = any(("直流电缆" in item.name or "直流线" in item.name) for item in items)
    remarks: list[str] = []
    if has_hybrid_inverter:
        remarks.append("光储逆变器")
    if has_grid_cabinet:
        remarks.append("有并网柜")
    elif has_grid_box:
        remarks.append("有并网箱")
    if has_dc_cable:
        remarks.append("有直流线")
    return "; ".join(remarks) if remarks else "无"
