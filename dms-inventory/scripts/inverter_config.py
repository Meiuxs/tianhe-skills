#!/usr/bin/env python3
"""Role: 逆变器配置器 — DC/AC 容配比计算和多品牌组合搜索算法。被编排器导入，不单独调用。

逆变器自动配置脚本 - 根据组件功率自动计算最优逆变器配置。

用法：
  # 自动配置（交互式）
  python inverter_config.py --component-power 572 --existing 100

  # 指定品牌
  python inverter_config.py --component-power 572 --existing 100 --brand 天合

  # 输出JSON
  python inverter_config.py --component-power 572 --existing 100 --json

  # 指定比例范围
  python inverter_config.py --component-power 572 --existing 100 --ratio-min 1.1 --ratio-max 1.2
"""

import argparse
import json
import os
import sys

import pandas as pd

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

# 导入库存查询模块
from inventory_query import load_inventory, query_inverters


def calculate_inverter_range(component_power: float, existing_power: float,
                             ratio_min: float = 1.1, ratio_max: float = 1.2) -> tuple:
    """计算需要配置的逆变器功率范围。

    Args:
        component_power: 组件总功率(kW)
        existing_power: 已有逆变器功率(kW)
        ratio_min: 最小比例（组件/逆变器）
        ratio_max: 最大比例（组件/逆变器）

    Returns:
        (最小需要功率, 最大需要功率, 目标总功率范围)
    """
    # 逆变器总功率范围
    total_min = component_power / ratio_max  # 最小逆变器总功率
    total_max = component_power / ratio_min  # 最大逆变器总功率

    # 需要新增的功率
    need_min = max(0, total_min - existing_power)
    need_max = max(0, total_max - existing_power)

    return need_min, need_max, (total_min, total_max)


def find_inverter_combinations(inverters: pd.DataFrame, target_power: float,
                               tolerance: float = 0.1, max_combinations: int = 10,
                               same_brand: bool = True, stock_sufficient: bool = True) -> list:
    """查找满足目标功率的逆变器组合。

    Args:
        inverters: 逆变器库存DataFrame
        target_power: 目标功率(kW)
        tolerance: 容差比例（如0.1表示±10%）
        max_combinations: 最大返回组合数
        same_brand: 是否优先同品牌（默认True）
        stock_sufficient: 是否只返回库存充足的方案（默认True）

    Returns:
        组合列表，每项为 [(物料编号, 功率, 数量, 单价排序, 品牌), ...]
    """
    import re

    # 提取功率数值
    def extract_power(power_str):
        if pd.isna(power_str):
            return 0
        match = re.search(r'(\d+)', str(power_str))
        return int(match.group(1)) if match else 0

    # 提取品牌（从厂家列或物料名称）
    def extract_brand(row):
        if pd.notna(row.get('厂家')):
            return str(row['厂家']).strip()
        return '未知'

    # 准备数据
    inverter_list = []
    for _, row in inverters.iterrows():
        power = extract_power(row['功率'])
        if power > 0:
            inverter_list.append({
                'code': row['物料编号'],
                'power': power,
                'name': row['物料名称'],
                'stock': row['可用库存'] if pd.notna(row['可用库存']) else 0,
                'price_rank': row['价格排序'] if pd.notna(row['价格排序']) else 999,
                'brand': extract_brand(row)
            })

    if not inverter_list:
        return []

    # 按品牌分组
    brand_groups = {}
    for inv in inverter_list:
        brand = inv['brand']
        if brand not in brand_groups:
            brand_groups[brand] = []
        brand_groups[brand].append(inv)

    # 按功率分组，取价格排序最低的（同功率时取库存最充足的）
    def get_power_groups(inv_list):
        power_groups = {}
        for inv in inv_list:
            p = inv['power']
            if p not in power_groups:
                power_groups[p] = inv
            else:
                # 同功率：保留价格更低或库存更充足的
                existing = power_groups[p]
                if inv['price_rank'] < existing['price_rank']:
                    power_groups[p] = inv
                elif existing['stock'] <= 0 and inv['stock'] > 0:
                    # 现有物料无库存时，优先选择有库存的
                    power_groups[p] = inv
                elif inv['stock'] > existing['stock']:
                    power_groups[p] = inv
        return power_groups

    # 贪心算法：从大功率开始组合
    def find_combos_with_groups(power_groups, target, tol, max_combos, check_stock=True):
        sorted_powers = sorted(power_groups.keys(), reverse=True)
        combinations = []

        def find_combos(remaining, current_combo, start_idx):
            if len(combinations) >= max_combos:
                return
            if abs(remaining) <= target * tol:
                combinations.append(current_combo.copy())
                return
            if remaining <= 0 or start_idx >= len(sorted_powers):
                return

            for i in range(start_idx, len(sorted_powers)):
                power = sorted_powers[i]
                inv = power_groups[power]
                stock = int(inv['stock']) if inv['stock'] > 0 else 0

                # 如果需要检查库存，且库存为0则跳过
                if check_stock and stock <= 0:
                    continue

                max_qty = min(int(remaining / power) + 1, stock if check_stock else 999)

                for qty in range(max_qty, 0, -1):
                    if qty * power <= remaining + target * tol:
                        current_combo.append((inv['code'], power, qty, inv['price_rank'], inv['brand']))
                        find_combos(remaining - qty * power, current_combo, i + 1)
                        current_combo.pop()
                        if len(combinations) >= max_combos:
                            return

        find_combos(target, [], 0)
        combinations.sort(key=lambda x: sum(item[2] * item[3] for item in x))
        return combinations

    # 策略1: 尝试同品牌组合
    same_brand_combos = []
    if same_brand:
        for brand, brand_inverters in brand_groups.items():
            power_groups = get_power_groups(brand_inverters)
            combos = find_combos_with_groups(power_groups, target_power, tolerance, max_combinations, stock_sufficient)
            for combo in combos:
                same_brand_combos.append({
                    'combo': combo,
                    'brand': brand,
                    'is_same_brand': True
                })
        # 按价格排序
        same_brand_combos.sort(key=lambda x: sum(item[3] for item in x['combo']))

    # 策略2: 混合品牌组合
    all_power_groups = get_power_groups(inverter_list)
    mixed_combos = find_combos_with_groups(all_power_groups, target_power, tolerance, max_combinations,
                                           stock_sufficient)
    mixed_results = [{'combo': c, 'brand': '混合', 'is_same_brand': False} for c in mixed_combos]

    # 合并结果：同品牌优先
    if same_brand_combos:
        return same_brand_combos[:max_combinations]
    elif mixed_results:
        return mixed_results[:max_combinations]
    else:
        return []


def format_combination(combo_data: dict) -> dict:
    """格式化组合为易读的字典。

    Args:
        combo_data: {'combo': [(物料编号, 功率, 数量, 价格排序, 品牌), ...], 'brand': str, 'is_same_brand': bool}

    Returns:
        格式化的字典
    """
    combo = combo_data['combo']
    brand = combo_data['brand']
    is_same_brand = combo_data['is_same_brand']

    total_power = sum(p * q for _, p, q, _, _ in combo)
    items = []
    for code, power, qty, price_rank, item_brand in combo:
        items.append({
            'code': code,
            'power': power,
            'quantity': qty,
            'subtotal': power * qty,
            'price_rank': price_rank,
            'brand': item_brand
        })
    return {
        'total_power': total_power,
        'items': items,
        'total_price_rank': sum(item[2] * item[3] for item in combo),
        'brand': brand,
        'is_same_brand': is_same_brand
    }


def main():
    parser = argparse.ArgumentParser(description="逆变器自动配置工具")
    parser.add_argument("--component-power", type=float, required=True,
                        help="组件总功率(kW)")
    parser.add_argument("--existing", type=float, default=0,
                        help="已有逆变器功率(kW)")
    parser.add_argument("--ratio-min", type=float, default=1.1,
                        help="最小比例（组件/逆变器），默认1.1")
    parser.add_argument("--ratio-max", type=float, default=1.2,
                        help="最大比例（组件/逆变器），默认1.2")
    parser.add_argument("--brand", help="品牌关键词（如天合）")
    parser.add_argument("--same-brand", action="store_true", default=True,
                        help="优先同品牌组合（默认开启）")
    parser.add_argument("--no-same-brand", dest="same_brand", action="store_false",
                        help="允许混合品牌组合")
    parser.add_argument("--tolerance", type=float, default=0.1,
                        help="功率容差比例，默认0.1（±10%%）")
    parser.add_argument("--max-combos", type=int, default=5,
                        help="最大返回组合数，默认5")
    parser.add_argument("--stock-sufficient", action="store_true", default=True,
                        help="只返回库存充足的方案（默认开启）")
    parser.add_argument("--allow-insufficient", dest="stock_sufficient", action="store_false",
                        help="允许返回库存不足的方案")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")
    parser.add_argument("--file", help="库存文件路径")
    args = parser.parse_args()

    # 计算功率范围
    need_min, need_max, (total_min, total_max) = calculate_inverter_range(
        args.component_power, args.existing, args.ratio_min, args.ratio_max
    )

    if not args.json:
        print(f"\n=== 逆变器配置计算 ===")
        print(f"组件总功率: {args.component_power} kW")
        print(f"已有逆变器: {args.existing} kW")
        print(f"比例要求: {args.component_power}/{args.ratio_max} ~ {args.component_power}/{args.ratio_min}")
        print(f"逆变器总功率范围: {total_min:.1f} ~ {total_max:.1f} kW")
        print(f"需要新增功率: {need_min:.1f} ~ {need_max:.1f} kW")
        print(f"品牌要求: {'同品牌优先' if args.same_brand else '允许混合品牌'}")
        print()

    # 加载库存
    data = load_inventory(args.file)
    inverters = query_inverters(data["逆变器"], brand=args.brand or "天合", has_stock=True)

    if inverters.empty:
        print("[错误] 未找到符合条件的逆变器库存")
        return

    # 查找组合（以目标功率的中间值为目标）
    target_power = (need_min + need_max) / 2
    combinations = find_inverter_combinations(
        inverters, target_power, args.tolerance, args.max_combos, args.same_brand, args.stock_sufficient
    )

    if not combinations:
        if args.stock_sufficient:
            print("[警告] 未找到库存充足的逆变器组合")
            print("[提示] 使用 --allow-insufficient 参数可查看库存不足的方案")
        else:
            print("[警告] 未找到满足条件的逆变器组合")
        return

    # 格式化结果
    results = [format_combination(combo) for combo in combinations]

    # 检查是否有同品牌方案
    has_same_brand = any(r['is_same_brand'] for r in results)
    if args.same_brand and not has_same_brand:
        print("[提示] 未找到满足条件的同品牌方案，以下为混合品牌方案：\n")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"=== 推荐配置方案（共{len(results)}种）===\n")
        for i, result in enumerate(results, 1):
            ratio = args.component_power / (args.existing + result['total_power'])
            brand_tag = f" [{result['brand']}]" if result['brand'] != '混合' else " [混合品牌]"
            same_brand_tag = " ⭐同品牌" if result['is_same_brand'] else ""
            print(f"方案 {i}:{brand_tag}{same_brand_tag}")
            print(f"  新增总功率: {result['total_power']} kW")
            print(f"  逆变器总功率: {args.existing + result['total_power']} kW")
            print(f"  组件/逆变器比值: {ratio:.3f}")
            print(f"  配置明细:")
            for item in result['items']:
                # 查找库存信息
                stock_info = ""
                for _, row in inverters.iterrows():
                    if row['物料编号'] == item['code']:
                        stock = row['可用库存'] if pd.notna(row['可用库存']) else 0
                        if stock < item['quantity']:
                            stock_info = f" ⚠️ 库存不足: 需{item['quantity']}台，库存{int(stock)}台，缺口{item['quantity'] - int(stock)}台"
                        else:
                            stock_info = f" ✅ 库存充足: {int(stock)}台"
                        break
                print(
                    f"    - {item['code']}: {item['power']}kW × {item['quantity']}台 = {item['subtotal']}kW [{item['brand']}]{stock_info}")
            print()


if __name__ == "__main__":
    main()
