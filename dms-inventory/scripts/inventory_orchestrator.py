#!/usr/bin/env python3
"""Role: 编排器（核心入口）— 统一的确定性库存分析入口。LLM 只需调用此脚本，传入结构化 JSON 参数，读取 JSON 分析结果。
整合查询、备注过滤、聚合、组合计算、排序为一站式调用。

库存编排器 - 统一入口脚本。

LLM 传入结构化 JSON 参数，脚本执行所有确定性查询/过滤/计算，
输出结构化 JSON analysis 供 LLM 分析决策。

用法：
  # 从参数传入
  python inventory_orchestrator.py --params '{"requirements":{"components":{"power":715,"qty":800}},"preferences":{}}'

  # 从文件传入
  python inventory_orchestrator.py --params-file ./input.json

  # 指定库存文件
  python inventory_orchestrator.py --params-file ./input.json --file /path/to/stock.xlsx

  # 输出到文件
  python inventory_orchestrator.py --params-file ./input.json --output-file analysis.json

输入 JSON 结构（--params / --params-file）：
{
  "requirements": {
    "components": {"power": 715, "qty": 800},           // 组件功率(W)和数量
    "inverters": {                                        // 逆变器（可选）
      "existing": [                                        // 已有逆变器
        {"model": "...", "power_kw": 40, "qty": 1, "brand": "上能"}
      ]
    },
    "combiner_boxes": {                                    // 并网柜（可选）
      "existing": [{"power_kw": 50, "qty": 2}]
    }
  },
  "preferences": {
    "prefer_brand": "上能",                                // 首选品牌（厂家名）
    "exclude_project_specific": true,                      // 排除项目专用
    "exclude_unlisted": true,                              // 排除未上架
    "prefer_non_original": true,                           // 优先非原厂机
    "dc_ac_ratio_range": [1.1, 1.2]                       // DC/AC 比范围
  },
  "options": {
    "max_combinations": 5                                  // 最多返回组合数
  }
}

输出 JSON：
{
  "version": "1.0",
  "summary": { ... },          // 关键参数汇总
  "components": { ... },        // 组件查询结果
  "inverters": { ... },         // 逆变器查询结果
  "combiner_boxes": { ... }     // 并网柜查询结果
}
"""

import argparse
import copy
import json
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

from inventory_query import (
    load_inventory, query_components, query_inverters, query_boxes,
    aggregate_stock, INVENTORY_DIR
)
from inverter_config import (
    calculate_inverter_range, find_inverter_combinations, format_combination
)

# ── 备注过滤规则 ──────────────────────────────────────────────

# 关键词 → (严重级别, 原因标签)
REMARK_RULES = {
    # 直接排除
    '项目专用': ('excluded', '项目专用物料，不可用于其他项目'),
    '华电': ('excluded', '项目专用物料（华电项目），不可用于其他项目'),
    '未上架': ('excluded', '未上架不可售'),
    # 警告（需LLM判断）
    '原厂机': ('warning', '原厂机交期长，非项目强制要求尽量不用'),
    '特价组件': ('warning', '特价组件，可正常使用'),
    '小包装': ('warning', '小包装组件，仅限特定场景使用'),
    # 常规
    '常规备货': ('normal', '常规备货，库存可能需关注'),
}

# ── 辅助函数 ──────────────────────────────────────────────────

def _parse_remark(remark: str) -> dict:
    """解析备注字段，返回匹配的规则和严重级别。"""
    if pd.isna(remark) or not str(remark).strip():
        return {'level': 'none', 'reason': None, 'matched_rule': None}
    remark_str = str(remark)
    for keyword, (level, reason) in REMARK_RULES.items():
        if keyword in remark_str:
            return {'level': level, 'reason': reason, 'matched_rule': keyword}
    return {'level': 'unknown', 'reason': f'备注内容: {remark_str}', 'matched_rule': None}


def _get_stock(row) -> int:
    """从行中获取库存数量，兼容聚合前后列名。"""
    for col in ('库存总量', '可用库存'):
        val = row.get(col)
        if pd.notna(val) and val is not None:
            return int(val)
    return 0


def _filter_by_remark(items: pd.DataFrame, preferences: dict) -> dict:
    """按备注过滤物料，返回 {'available': DataFrame, 'excluded': [dict], 'warnings': [dict]}。"""
    result = {'available': [], 'excluded': [], 'warnings': []}

    if items.empty:
        result['available'] = pd.DataFrame()
        return result

    exclude_project = preferences.get('exclude_project_specific', True)
    exclude_unlisted = preferences.get('exclude_unlisted', True)
    available_rows = []
    for _, row in items.iterrows():
        remark = row.get('备注', None)
        parsed = _parse_remark(remark)
        stock = _get_stock(row)

        if parsed['level'] == 'excluded':
            # 检查是否应该排除
            rule = parsed['matched_rule']
            should_exclude = False
            if rule in ('项目专用', '华电') and exclude_project:
                should_exclude = True
            elif rule == '未上架' and exclude_unlisted:
                should_exclude = True
            elif rule == '原厂机':
                should_exclude = True  # 默认排除

            if should_exclude:
                result['excluded'].append({
                    'code': row.get('物料编号', ''),
                    'name': _safe_str(row.get('物料名称')),
                    'power': _safe_str(row.get('功率')),
                    'stock': stock,
                    'reason': parsed['reason'],
                    'remark': _safe_str(remark)
                })
                continue

        if parsed['level'] == 'warning':
            # 不排除，但记录警告
            result['warnings'].append({
                'code': row.get('物料编号', ''),
                'name': _safe_str(row.get('物料名称')),
                'power': _safe_str(row.get('功率')),
                'stock': stock,
                'reason': parsed['reason'],
                'remark': _safe_str(remark)
            })

        available_rows.append(row)

    if available_rows:
        result['available'] = pd.DataFrame(available_rows)
    else:
        result['available'] = pd.DataFrame()
    return result


def _extract_power_num(power_str) -> int:
    """从功率字符串提取数字，如 '715W' → 715, '50KW三相' → 50。"""
    if pd.isna(power_str):
        return 0
    match = re.search(r'(\d+)', str(power_str))
    return int(match.group(1)) if match else 0


def _safe_str(val, default: str = '') -> str:
    """安全地将值转为字符串，NaN/None 返回默认值。"""
    if pd.isna(val) or val is None:
        return default
    return str(val)


def _calc_dc_ac_ratio(component_kw: float, inverter_kw: float) -> float:
    """计算 DC/AC 比值，保留3位小数。"""
    if inverter_kw <= 0:
        return 0
    return round(component_kw / inverter_kw, 3)


def _calc_existing_kw(existing_list: list) -> float:
    """从已有逆变器列表计算总功率，兼容 power_kw / power+unit 格式。

    支持字段格式：
    - {"power_kw": 40}                    # 直接数字
    - {"power": 40, "unit": "kW"}         # power+unit 分离
    - {"power": "40kW", "unit": "kW"}     # power 为带单位字符串
    - {"power": 40}                        # 仅 power，无 unit

    Args:
        existing_list: 已有设备列表 [{model, power_kw, qty, brand}, ...]

    Returns:
        总功率（kW）
    """
    total = 0.0
    for item in existing_list:
        qty = item.get('qty', 1)
        power = item.get('power_kw')
        if power is None:
            power = item.get('power', 0)
        # 处理字符串格式如 "40kW" 或 "40"
        if isinstance(power, str):
            match = re.search(r'(\d+\.?\d*)', power)
            power = float(match.group(1)) if match else 0
        total += float(power) * qty
    return total


def _serializable(obj):
    """将 pandas 类型转换为 JSON 可序列化的 Python 原生类型。"""
    if isinstance(obj, (pd.Series, pd.DataFrame)):
        return obj.to_dict(orient='records') if isinstance(obj, pd.DataFrame) else obj.to_dict()
    try:
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
    except ImportError:
        pass
    return obj


# ── 核心查询函数 ──────────────────────────────────────────────

def query_components_section(data: dict, requirements: dict, preferences: dict) -> dict:
    """查询组件库存并过滤。"""
    result = {
        'specified': None,
        'specified_detail': [],
        'zero_stock_candidates': [],
        'alternatives': [],
        'excluded': [],
        'warnings': []
    }

    comp_req = requirements.get('components', {})
    if not comp_req:
        return result

    target_power = comp_req.get('power', 0)
    target_qty = comp_req.get('qty', 0)

    if target_power <= 0:
        return result

    df = data.get('组件', pd.DataFrame())
    if df.empty:
        return result

    # 1. 查询指定功率的组件（含零库存，用于展示零库存候选物料）
    all_items = query_components(df, power=target_power, has_stock=False)
    items_with_stock = all_items[all_items['可用库存'].notna() & (all_items['可用库存'] > 0)]

    agg = aggregate_stock(items_with_stock, qty_col='可用库存')

    # 记录全部明细（含零库存）和零库存候选物料
    # ⚠️ zero_stock_candidates 只包含「其他条件都满足，唯独库存为0」的物料
    #    排除备注含「项目专用」「华电」「未上架」等不可用物料
    detail_rows = []
    zero_stock_rows = []
    for _, row in all_items.iterrows():
        stock = _get_stock(row)
        remark_raw = row.get('备注', None)
        remark_str = _safe_str(remark_raw) or None
        parsed = _parse_remark(remark_raw) if pd.notna(remark_raw) else {'level': 'none'}
        entry = {
            'code': row.get('物料编号', ''),
            'name': _safe_str(row.get('物料名称')),
            'stock': stock,
            'remark': remark_str,
            'warehouse': _safe_str(row.get('仓库名称'))
        }
        detail_rows.append(entry)
        # 零库存且未被备注排除 → 作为候选
        if stock == 0 and parsed['level'] != 'excluded':
            zero_stock_rows.append(entry)

    result['specified_detail'] = detail_rows
    result['zero_stock_candidates'] = zero_stock_rows

    # 过滤备注
    filtered = _filter_by_remark(agg, preferences)

    # 可用总量
    available_stock = int(filtered['available']['库存总量'].sum()) if not filtered['available'].empty else 0

    # 判断状态
    if available_stock >= target_qty:
        status = 'sufficient'
    elif available_stock > 0:
        status = 'insufficient'
    else:
        status = 'no_stock'

    total_kw = round(target_power * target_qty / 1000, 2)

    result['specified'] = {
        'power': target_power,
        'qty': target_qty,
        'total_kw': total_kw,
        'available_stock': available_stock,
        'status': status,
        'shortfall': max(0, target_qty - available_stock)
    }
    result['excluded'] = filtered['excluded']
    result['warnings'] = filtered['warnings']

    # 2. 查询所有可替代的组件规格（排除指定功率的）
    all_powers = sorted(df['功率'].unique(),
                        key=lambda x: _extract_power_num(x))
    all_power_nums = [_extract_power_num(p) for p in all_powers]

    for pn in sorted(all_power_nums, reverse=True):
        if pn == target_power:
            continue
        alt_items = query_components(df, power=pn)
        alt_agg = aggregate_stock(alt_items, qty_col='可用库存')
        alt_filtered = _filter_by_remark(alt_agg, preferences)
        alt_available = alt_filtered['available']

        alt_total_stock = int(alt_available['库存总量'].sum()) if not alt_available.empty else 0

        alt_entry = {
            'power': pn,
            'total_stock': alt_total_stock,
            'status': 'sufficient' if alt_total_stock >= target_qty else 'insufficient' if alt_total_stock > 0 else 'no_stock',
        }

        if not alt_available.empty:
            # 取库存最多的物料
            best = alt_available.iloc[0]
            alt_entry['best_code'] = _safe_str(best.get('物料编号'))
            alt_entry['best_name'] = _safe_str(best.get('物料名称'))[:80]

        result['alternatives'].append(alt_entry)

    return result


def query_inverters_section(data: dict, requirements: dict, preferences: dict) -> dict:
    """查询逆变器库存、过滤、计算组合方案。"""
    result = {
        'existing': [],
        'zero_stock_candidates': [],
        'brands': [],
        'combinations': [],
        'excluded': [],
        'warnings': []
    }

    inv_req = requirements.get('inverters')
    if inv_req is None:
        return result

    # 已有逆变器
    existing_inverters = inv_req.get('existing', [])
    existing_kw = _calc_existing_kw(existing_inverters)
    result['existing'] = copy.deepcopy(existing_inverters)
    result['existing_total_kw'] = existing_kw

    # 校验警告：传入了已有设备但功率解析为 0
    if existing_inverters and existing_kw <= 0:
        model_hint = '、'.join(
            i.get('model', '?') for i in existing_inverters[:3]
        )
        example_kw = '{"power_kw": 40}'
        example_pu = '{"power": 40, "unit": "kW"}'
        print(
            f"[警告] 已传入 {len(existing_inverters)} 台已有逆变器"
            f"（{model_hint}...），但解析功率和为 0。\n"
            f"        请使用 power_kw 字段（如 {example_kw}）"
            f"或 power+unit 格式（如 {example_pu}）。",
            file=sys.stderr
        )

    df = data.get('逆变器', pd.DataFrame())
    if df.empty:
        return result

    # 查询逆变器库存 — 品牌偏好作为优先展示而非硬性过滤
    items = query_inverters(df, has_stock=True, brand=None)
    if items.empty:
        return result

    # 查询零库存逆变器候选（匹配但库存为0的型号，供用户自筹选择）
    # ⚠️ 只包含「其他条件都满足，唯独库存为0」的物料，排除备注不可用的
    required_new = inv_req.get('required_new', [])
    zero_stock_inverters = []
    def _is_usable(row) -> bool:
        """检查物料是否因备注被排除（excluded 级别不可用作候选）。"""
        remark_raw = row.get('备注', None)
        if pd.isna(remark_raw) or not remark_raw:
            return True
        parsed = _parse_remark(remark_raw)
        return parsed['level'] != 'excluded'

    if required_new:
        for req_inv in required_new:
            req_power = req_inv.get('power_kw', 0)
            req_brand = req_inv.get('brand')
            zero_items = query_inverters(df, power=req_power, brand=req_brand, has_stock=False)
            if not zero_items.empty:
                agg_zero = aggregate_stock(zero_items, qty_col='可用库存', keep_zero=True)
                for _, row in agg_zero.iterrows():
                    stock_val = _get_stock(row)
                    if stock_val == 0 and _is_usable(row):
                        zero_stock_inverters.append({
                            'code': row.get('物料编号', ''),
                            'name': _safe_str(row.get('物料名称')),
                            'power': _safe_str(row.get('功率')),
                            'power_num': _extract_power_num(row.get('功率', '')),
                            'brand': _safe_str(row.get('厂家'), default=''),
                            'remark': _safe_str(row.get('备注')) or None,
                        })
    # 也查一下首选品牌型号的零库存情况（未指定 required_new 时）
    if not zero_stock_inverters and preferences.get('prefer_brand'):
        zero_items = query_inverters(df, brand=preferences.get('prefer_brand'), has_stock=False)
        if not zero_items.empty:
            agg_zero = aggregate_stock(zero_items, qty_col='可用库存', keep_zero=True)
            for _, row in agg_zero.iterrows():
                stock_val = _get_stock(row)
                if stock_val == 0 and _is_usable(row):
                    zero_stock_inverters.append({
                        'code': row.get('物料编号', ''),
                        'name': _safe_str(row.get('物料名称')),
                        'power': _safe_str(row.get('功率')),
                        'power_num': _extract_power_num(row.get('功率', '')),
                        'brand': _safe_str(row.get('厂家'), default=''),
                        'remark': _safe_str(row.get('备注')) or None,
                    })
    result['zero_stock_candidates'] = zero_stock_inverters

    agg = aggregate_stock(items, qty_col='可用库存')
    if agg.empty:
        return result

    # 过滤备注并分组
    filtered = _filter_by_remark(agg, preferences)
    result['excluded'] = filtered['excluded']
    result['warnings'] = filtered['warnings']

    available = filtered['available']
    if available.empty:
        return result

    # ── 品牌分组（用原始 items DataFrame，aggregate_stock 会丢弃 厂家 等列） ──
    avail_codes = set(available['物料编号'].values)

    # 从原始 items 反查可用物料的完整行（含 厂家/功率/备注/价格排序 等列）
    raw_items = items[items['物料编号'].isin(avail_codes)]
    # 从聚合数据构建库存总量查询表 {物料编号: 库存总量}
    stock_lookup = dict(zip(available['物料编号'], available['库存总量']))

    # ── 物料偏好过滤（前置筛子，如"天合原装专用"） ──
    # 只影响后续组合的候选物料范围，不改变品牌分组逻辑
    prefer_material = preferences.get('prefer_material')
    raw_items_filtered = raw_items  # 默认不筛选
    if prefer_material:
        keyword = prefer_material
        matched_codes = set()
        for _, row in raw_items.iterrows():
            name = _safe_str(row.get('物料名称'))
            if keyword in name:
                matched_codes.add(row['物料编号'])
        if matched_codes:
            raw_items_filtered = raw_items[raw_items['物料编号'].isin(matched_codes)]
            result['preferred_material'] = {
                'keyword': keyword,
                'total_count': len(matched_codes),
            }

    brand_groups = {}
    if '厂家' in raw_items_filtered.columns:
        for _, row in raw_items_filtered.iterrows():
            code = row.get('物料编号', '')
            brand = _safe_str(row.get('厂家'), default='未知')
            if brand not in brand_groups:
                brand_groups[brand] = []
            item = {
                'code': code,
                'power': _extract_power_num(row.get('功率', '')),
                'power_label': _safe_str(row.get('功率')),
                'name': _safe_str(row.get('物料名称'))[:60],
                'stock': int(stock_lookup.get(code, 0)),
                'price_rank': row.get('价格排序', None),
                'remark': _safe_str(row.get('备注')) or None,
                'brand': brand,
            }
            # 同品牌同物料只保留一条（取首个仓库行）
            existing_codes = {m['code'] for m in brand_groups[brand]}
            if code not in existing_codes:
                brand_groups[brand].append(item)

    # 所有品牌平等待遇（不再有 preferred_brand 特权）
    for brand, models in sorted(brand_groups.items()):
        result['brands'].append({'name': brand, 'models': models})

    # 计算逆变器组合方案
    component_kw = result.get('component_power_kw', 0)
    if component_kw <= 0:
        # 从 requirements 中拿组件总功率
        comp_req = requirements.get('components', {})
        if comp_req:
            component_kw = round(comp_req.get('power', 0) * comp_req.get('qty', 0) / 1000, 2)

    # ── 组合生成（所有品牌各自 same_brand → 不足时混合兜底） ──
    all_combos = []

    if component_kw > 0 and existing_kw >= 0:
        ratio_range = preferences.get('dc_ac_ratio_range', [1.1, 1.2])
        ratio_min, ratio_max = ratio_range[0], ratio_range[1]

        need_min, need_max, (_, _) = calculate_inverter_range(
            component_kw, existing_kw, ratio_min, ratio_max
        )

        target_power = (need_min + need_max) / 2
        options = preferences.get('options', {})
        max_combos = options.get('max_combinations', 5)
        tolerance = options.get('tolerance', 0.15)

        stock_sufficient = preferences.get('stock_sufficient', True)

        # 使用 raw_items_filtered（来自前置过滤）作为组合搜索数据源
        avail_codes_for_combo = set(raw_items_filtered['物料编号'].values)
        combo_data = items[items['物料编号'].isin(avail_codes_for_combo)].copy()
        if '价格排序' not in combo_data.columns:
            combo_data['价格排序'] = 999

        # 第 1 段：同品牌组合（所有品牌平等待遇）
        for brand_entry in result.get('brands', []):
            brand_name = brand_entry['name']
            brand_raw = combo_data[combo_data['厂家'] == brand_name]
            if brand_raw.empty:
                continue
            combos = find_inverter_combinations(
                brand_raw, target_power, tolerance,
                max_combos, same_brand=True,
                stock_sufficient=stock_sufficient,
            )
            for combo_data_item in combos:
                formatted = format_combination(combo_data_item)
                all_combos.append(formatted)

        # 第 2 段：混合品牌兜底（仅当同品牌无任何方案时）
        if not all_combos:
            combos = find_inverter_combinations(
                combo_data, target_power, tolerance,
                max_combos, same_brand=False,
                stock_sufficient=stock_sufficient,
            )
            for combo_data_item in combos:
                formatted = format_combination(combo_data_item)
                all_combos.append(formatted)

    # 增强组合信息
    if all_combos:
        for combo in all_combos:
            total_inv = existing_kw + combo['total_power']
            combo['dc_ac_ratio'] = _calc_dc_ac_ratio(component_kw, total_inv)
            combo['total_inverter_kw'] = total_inv
            combo['total_units'] = sum(item['quantity'] for item in combo['items'])
            combo['avg_price_per_kw'] = round(
                combo['total_price_rank'] / combo['total_power'], 2
            ) if combo['total_power'] > 0 else 999

        # 排序：台数少优先 → 同台数时价格低优先
        all_combos.sort(key=lambda c: (c['total_units'], c['total_price_rank']))

        # 添加方案标签
        for i, combo in enumerate(all_combos, 1):
            combo['plan_label'] = f"方案{i}"

        result['combinations'] = all_combos

    return result


def query_boxes_section(data: dict, requirements: dict, preferences: dict) -> dict:
    """查询并网柜库存。"""
    result = {
        'existing': [],
        'available': [],
        'excluded': [],
        'warnings': [],
    }

    box_req = requirements.get('combiner_boxes', {})
    existing_boxes = box_req.get('existing', [])
    result['existing'] = existing_boxes

    df = data.get('并网箱', pd.DataFrame())
    if df.empty:
        return result

    box_power = box_req.get('power', 50)
    items = query_boxes(df, power=box_power, has_stock=True)
    if items.empty:
        return result

    agg = aggregate_stock(items, qty_col='可用库存')
    if agg.empty:
        return result

    # 备注过滤（与组件/逆变器一致）
    filtered = _filter_by_remark(agg, preferences)
    result['excluded'] = filtered['excluded']
    result['warnings'] = filtered['warnings']

    available = filtered['available']
    if available.empty:
        return result

    for _, row in available.iterrows():
        result['available'].append({
            'type': _safe_str(row.get('并网箱类型')),
            'code': row.get('物料编号', ''),
            'name': _safe_str(row.get('物料名称'))[:60],
            'stock': int(row['库存总量']),
            'total_stock': int(row['库存总量']),
        })

    return result


# ── 主流程 ────────────────────────────────────────────────────

def run_analysis(params: dict) -> dict:
    """执行完整库存分析，返回结构化结果。"""
    requirements = params.get('requirements', {})
    preferences = params.get('preferences', {})

    # 确保 preferences 中有 options 子字典
    if 'options' not in preferences:
        preferences['options'] = params.get('options', {})

    # 加载库存数据
    data = load_inventory(params.get('file'))

    # 组件分析
    components = query_components_section(data, requirements, preferences)

    # 逆变器分析 - 需要组件总功率
    inverters = query_inverters_section(data, requirements, preferences)
    if components.get('specified'):
        inverters['component_power_kw'] = components['specified']['total_kw']

    # 并网柜分析
    combiner_boxes = query_boxes_section(data, requirements, preferences)

    # 汇总
    comp_spec = components.get('specified') or {}
    inv_existing = inverters.get('existing_total_kw', 0)
    comp_kw = comp_spec.get('total_kw', 0)

    need_min = need_max = 0
    if comp_kw > 0:
        ratio_range = preferences.get('dc_ac_ratio_range', [1.1, 1.2])
        _, _, (total_min, total_max) = calculate_inverter_range(
            comp_kw, inv_existing, ratio_range[0], ratio_range[1]
        )
        need_min = max(0, total_min - inv_existing)
        need_max = max(0, total_max - inv_existing)

    summary = {
        'component_power_kw': round(comp_kw, 2),
        'component_qty': comp_spec.get('qty', 0),
        'component_power_w': comp_spec.get('power', 0),
        'component_status': comp_spec.get('status', 'unknown'),
        'existing_inverter_kw': inv_existing,
        'inverter_need_min_kw': round(need_min, 1),
        'inverter_need_max_kw': round(need_max, 1),
        'total_inverter_target_kw': round((need_min + need_max) / 2, 1),
    }

    # 已有逆变器明细摘要（便于 LLM 快速诊断）
    existing_list = inverters.get('existing', [])
    if existing_list:
        summary['existing_inverter_detail'] = '; '.join(
            f"{i.get('model', '?')} x {i.get('qty', 1)}"
            for i in existing_list
        )

    result = {
        'version': '1.0',
        'timestamp': None,  # 调用方填充
        'summary': summary,
        'components': components,
        'inverters': inverters,
        'combiner_boxes': combiner_boxes,
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="库存编排器 - 统一查询/过滤/计算入口")
    parser.add_argument('--params', help='JSON 格式的参数（直接传字符串）')
    parser.add_argument('--params-file', help='JSON 参数文件路径')
    parser.add_argument('--file', help='库存文件路径（不传则自动查找）')
    parser.add_argument('--output-file', help='输出到文件（默认输出到 stdout）')
    args = parser.parse_args()

    # 读取参数
    if args.params_file:
        with open(args.params_file, 'r', encoding='utf-8') as f:
            params = json.load(f)
    elif args.params:
        params = json.loads(args.params)
    else:
        parser.print_help()
        print("\n[错误] 请提供 --params 或 --params-file")
        sys.exit(1)

    # 添加 file 到 params
    if args.file:
        params['file'] = args.file

    # 运行分析
    result = run_analysis(params)

    # 输出
    output = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    if args.output_file:
        out_path = os.path.abspath(args.output_file)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[完成] 分析结果已写入: {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == '__main__':
    try:
        import numpy as np
    except ImportError:
        np = type('np', (), {'integer': int, 'floating': float, 'bool_': bool})()
    main()
