#!/usr/bin/env python3
"""Role: 快捷查询 — 独立于编排器的多维度物料搜索工具。支持跨品类搜索和仓库聚合。

支持按物料编号、物料名称、功率等多条件搜索，多条件间为 AND（交集）关系。

用法：
  # 精确物料编号查询
  python quick_query.py --code 6B001492

  # 物料名称/型号关键词模糊查询
  python quick_query.py --name "730W"
  python quick_query.py --name "天合原装"

  # 按功率列搜索
  python quick_query.py --power "110KW"

  # 多条件交集（同时满足编码 + 名称 + 功率）
  python quick_query.py --name "天合原装" --power "110KW" --category 逆变器

  # 聚合仓库总量 + JSON 输出
  python quick_query.py --code AB001347 --aggregate --json
  python quick_query.py --code AB001347 --aggregate --json --output-file result.json
"""

import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

from inventory_query import (
    load_inventory,
    aggregate_stock,
)

# ── 品类元信息 ──────────────────────────────────────────────────
CATEGORY_META = {
    '组件': {
        'code_col': '物料编号',
        'name_col': '物料名称',
        'power_col': '功率',
        'stock_col': '可用库存',
        'warehouse_col': '仓库名称',
        'remark_col': '备注',
        'extra_cols': ['玻璃类型', '排产情况'],
    },
    '逆变器': {
        'code_col': '物料编号',
        'name_col': '物料名称',
        'power_col': '功率',
        'stock_col': '可用库存',
        'warehouse_col': '仓库名称',
        'remark_col': '备注',
        'extra_cols': ['厂家', '价格排序（数字越大则越贵）'],
    },
    '并网箱': {
        'code_col': '物料编号',
        'name_col': '物料名称',
        'power_col': '功率',
        'stock_col': '可用库存',
        'warehouse_col': '仓库名称',
        'remark_col': '备注',
        'extra_cols': ['并网箱类型'],
    },
}

VALID_CATEGORIES = list(CATEGORY_META.keys())


# ── 查询函数（单维度） ──────────────────────────────────────────

def _query_by_code(df: pd.DataFrame, code: str, meta: dict) -> pd.DataFrame:
    """按物料编号精确查询。"""
    code_col = meta['code_col']
    if code_col not in df.columns:
        return pd.DataFrame()
    return df[df[code_col].astype(str).str.strip() == code.strip()].copy()


def _query_by_name(df: pd.DataFrame, keyword: str, meta: dict) -> pd.DataFrame:
    """按物料名称关键词模糊查询。"""
    name_col = meta['name_col']
    if name_col not in df.columns:
        return pd.DataFrame()
    return df[df[name_col].astype(str).str.contains(keyword, case=False, na=False)].copy()


def _query_by_power(df: pd.DataFrame, power_keyword: str, meta: dict) -> pd.DataFrame:
    """按功率关键词模糊查询（在 功率 列中搜索）。"""
    power_col = meta.get('power_col')
    if not power_col or power_col not in df.columns:
        return pd.DataFrame()
    return df[df[power_col].astype(str).str.contains(power_keyword, case=False, na=False)].copy()


# ── 多条件交集查询 ──────────────────────────────────────────────

def query(df: pd.DataFrame, meta: dict,
          code: str = None, name: str = None, power: str = None) -> pd.DataFrame:
    """多条件交集（AND）查询。

    同时传入 --code、--name、--power 时，结果必须同时满足所有条件。

    Args:
        df: 该品类的 DataFrame
        meta: 品类元信息
        code: 物料编号（精确匹配）
        name: 物料名称关键词（模糊匹配）
        power: 功率关键词（模糊匹配）

    Returns:
        满足所有条件的 DataFrame
    """
    if not code and not name and not power:
        print("[警告] 至少需要提供一个查询条件（--code、--name 或 --power）", file=sys.stderr)
        return pd.DataFrame()

    masks = []
    if code:
        code_col = meta['code_col']
        if code_col in df.columns:
            masks.append(df[code_col].astype(str).str.strip() == code.strip())
    if name:
        name_col = meta['name_col']
        if name_col in df.columns:
            masks.append(df[name_col].astype(str).str.contains(name, case=False, na=False))
    if power:
        power_col = meta.get('power_col')
        if power_col and power_col in df.columns:
            masks.append(df[power_col].astype(str).str.contains(power, case=False, na=False))

    if not masks:
        return pd.DataFrame()

    # 所有条件取 AND（交集）
    combined_mask = masks[0]
    for m in masks[1:]:
        combined_mask = combined_mask & m
    return df[combined_mask].copy()


# ── 格式化输出 ──────────────────────────────────────────────────

def _safe_val(val):
    """处理 NaN/NaT 为 None。"""
    if pd.isna(val) or val is None or val == '':
        return None
    return val


def _build_category_result(df: pd.DataFrame, meta: dict,
                           aggregate: bool) -> list:
    """构建单个品类的查询结果字典列表。

    Returns:
        list[dict] 或 None（空结果时）
    """
    if df.empty:
        return None

    code_col = meta['code_col']
    name_col = meta['name_col']
    power_col = meta['power_col']
    stock_col = meta['stock_col']
    warehouse_col = meta['warehouse_col']
    remark_col = meta['remark_col']

    if aggregate:
        # 聚合各仓库库存（不过滤零库存 — 快捷查询应展示所有匹配物料）
        agg = aggregate_stock(df, material_col=code_col, name_col=name_col,
                              qty_col=stock_col, warehouse_col=warehouse_col,
                              keep_zero=True)

        records = []
        for _, row in agg.iterrows():
            rec = {
                '物料编号': str(row.get(code_col, '')),
                '物料名称': str(row.get(name_col, '')),
                '库存总量': int(row.get('库存总量', 0)),
                '仓库分布': str(row.get('仓库分布', '')),
            }
            for col in meta['extra_cols']:
                if col in df.columns:
                    rec[str(col)] = _safe_val(row.get(col))
            if power_col in df.columns:
                rec['功率'] = _safe_val(row.get(power_col))
            if remark_col in df.columns and remark_col in agg.columns:
                rec['备注'] = _safe_val(row.get(remark_col))
            records.append(rec)
        return records

    # 非聚合：逐仓库明细
    records = []
    for _, row in df.iterrows():
        rec = {
            '物料编号': str(row.get(code_col, '')),
            '物料名称': str(row.get(name_col, '')),
            '仓库名称': str(row.get(warehouse_col, '')),
            '可用库存': int(row.get(stock_col, 0)) if pd.notna(row.get(stock_col)) else 0,
        }
        if power_col in df.columns:
            rec['功率'] = _safe_val(row.get(power_col))
        if remark_col in df.columns:
            rec['备注'] = _safe_val(row.get(remark_col))
        for col in meta['extra_cols']:
            if col in df.columns:
                rec[str(col)] = _safe_val(row.get(col))
        records.append(rec)
    return records


def format_text(results: dict, code: str = None, name: str = None,
                power: str = None) -> str:
    """格式化为人类可读文本。"""
    lines = []
    if code:
        lines.append(f"\n=== 按物料编号查询 [{code}] ===")
    if name:
        lines.append(f"\n=== 按物料名称查询 [{name}] ===")
    if power:
        lines.append(f"\n=== 按功率查询 [{power}] ===")

    found_any = False
    for category, records in results.items():
        if not records:
            continue
        found_any = True
        lines.append(f"\n【{category}】共 {len(records)} 条记录")

        is_agg = '库存总量' in records[0] if records else False

        if is_agg:
            header = (
                f"{'物料编号':<12} {'物料名称':<50} "
                f"{'库存总量':>8} {'仓库分布':<40}"
            )
            lines.append(header)
            lines.append('-' * len(header))
            for rec in records:
                name_short = rec['物料名称'][:48] if rec['物料名称'] else ''
                remark = str(rec.get('备注', '') or '')
                lines.append(
                    f"{rec['物料编号']:<12} {name_short:<50} "
                    f"{rec['库存总量']:>8}  {rec['仓库分布']:<40}"
                )
                if remark:
                    lines.append(f"{'':>12} 备注: {remark}")
        else:
            header = (
                f"{'物料编号':<12} {'物料名称':<40} {'功率':<10} "
                f"{'仓库名称':<18} {'可用库存':>8} {'备注':<20}"
            )
            lines.append(header)
            lines.append('-' * len(header))
            for rec in records:
                name_short = rec['物料名称'][:38] if rec['物料名称'] else ''
                power = str(rec.get('功率', '') or '')
                remark = str(rec.get('备注', '') or '')
                lines.append(
                    f"{rec['物料编号']:<12} {name_short:<40} {power:<10} "
                    f"{rec['仓库名称']:<18} {rec['可用库存']:>8}  {remark:<20}"
                )

    if not found_any:
        lines.append("\n[结果] 未找到匹配的物料")
        if code:
            lines.append(f"  物料编号: {code}")
        if name:
            lines.append(f"  关键词: {name}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="快捷查询 — 按物料编号/名称/功率多维度搜索库存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --code 6B001492                  # 精确编码
  %(prog)s --name "730W"                     # 名称关键词
  %(prog)s --name "天合原装" --category 逆变器  # 限定品类
  %(prog)s --power "110KW"                   # 按功率列搜索
  %(prog)s --code AB001347 --aggregate --json # 聚合+JSON
  %(prog)s --code AB001347 --aggregate --json --output-file result.json

多条件同时使用时为 AND（交集）关系：
  %(prog)s --name "天合原装" --power "110KW"  # 天合原装 且 功率110KW
        """,
    )
    parser.add_argument('--code', help='物料编号（精确查询）')
    parser.add_argument('--name', help='物料名称/型号关键词（模糊查询）')
    parser.add_argument('--power', help='功率关键词（如 "110KW"、"730W"、"50"，在功率列中搜索）')
    parser.add_argument('--category', choices=VALID_CATEGORIES,
                        help='限定查询品类（不传则查全部）')
    parser.add_argument('--aggregate', action='store_true',
                        help='按物料编号聚合所有仓库的库存总量')
    parser.add_argument('--json', action='store_true',
                        help='JSON 格式输出')
    parser.add_argument('--output-file', help='输出到文件（默认输出到终端）')
    parser.add_argument('--file', help='库存文件路径（不传则自动查找最新）')
    args = parser.parse_args()

    if not args.code and not args.name and not args.power:
        parser.print_help()
        print("\n[错误] 请提供 --code、--name 或 --power", file=sys.stderr)
        sys.exit(1)

    # 加载数据
    data = load_inventory(args.file)

    # 确定查询品类
    categories = [args.category] if args.category else VALID_CATEGORIES

    # 逐品类查询（多条件 AND）
    results = {}
    for cat in categories:
        meta = CATEGORY_META[cat]
        df = data.get(cat, pd.DataFrame())
        if df.empty:
            continue

        matched = query(df, meta, args.code, args.name, args.power)

        if matched.empty:
            results[cat] = None
            continue

        records = _build_category_result(matched, meta, args.aggregate)
        results[cat] = records

    # 输出
    if args.json:
        output = json.dumps(results, ensure_ascii=False, indent=2)
    else:
        output = format_text(results, args.code, args.name, args.power)

    if args.output_file:
        out_path = os.path.abspath(args.output_file)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"[完成] 结果已写入: {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == '__main__':
    main()
