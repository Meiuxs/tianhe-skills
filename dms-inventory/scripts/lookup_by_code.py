#!/usr/bin/env python3
"""Role: 快捷查询 — 独立于编排器的按物料编号/名称快速定位库存工具。支持跨品类搜索和仓库聚合。

按物料编号或物料名称快速查询库存。

支持跨品类搜索（组件/逆变器/并网箱），聚合仓库库存，JSON/文本双输出。

用法：
  # 精确物料编号查询
  python lookup_by_code.py --code 6B001492

  # 物料名称/型号关键词模糊查询
  python lookup_by_code.py --name "730W"
  python lookup_by_code.py --name "天合原装"

  # 限定品类
  python lookup_by_code.py --name "天合原装" --category 逆变器

  # 聚合仓库总量 + JSON 输出
  python lookup_by_code.py --code AB001347 --aggregate --json
  python lookup_by_code.py --code AB001347 --aggregate --json --output-file result.json
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


# ── 查询函数 ────────────────────────────────────────────────────

def lookup_by_code(df: pd.DataFrame, code: str, meta: dict) -> pd.DataFrame:
    """按物料编号精确查询。

    Args:
        df: 该品类的 DataFrame
        code: 物料编号（如 "6B001492"）
        meta: 品类元信息

    Returns:
        匹配的 DataFrame（可能有多行 = 多个仓库）
    """
    code_col = meta['code_col']
    if code_col not in df.columns:
        return pd.DataFrame()
    return df[df[code_col].astype(str).str.strip() == code.strip()].copy()


def lookup_by_name(df: pd.DataFrame, keyword: str, meta: dict) -> pd.DataFrame:
    """按物料名称关键词模糊查询。

    Args:
        df: 该品类的 DataFrame
        keyword: 搜索关键词（如 "730W"、"天合"）
        meta: 品类元信息

    Returns:
        匹配的 DataFrame
    """
    name_col = meta['name_col']
    if name_col not in df.columns:
        return pd.DataFrame()
    return df[df[name_col].astype(str).str.contains(keyword, case=False, na=False)].copy()


def lookup_by_code_or_name(df: pd.DataFrame, code: str = None,
                           name: str = None, meta: dict = None) -> pd.DataFrame:
    """按编码或名称查询，同时传入时取并集。"""
    if code:
        result = lookup_by_code(df, code, meta)
        if name:
            name_result = lookup_by_name(df, name, meta)
            result = pd.concat([result, name_result]).drop_duplicates()
    elif name:
        result = lookup_by_name(df, name, meta)
    else:
        return pd.DataFrame()
    return result


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
        # 聚合各仓库库存
        agg = aggregate_stock(df, material_col=code_col, name_col=name_col,
                              qty_col=stock_col, warehouse_col=warehouse_col)

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
            if remark_col in df.columns:
                vals = df[remark_col].dropna()
                rec['备注'] = _safe_val(vals.iloc[0]) if not vals.empty else None
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


def format_text(results: dict, code: str = None, name: str = None) -> str:
    """格式化为人类可读文本。"""
    lines = []
    if code:
        lines.append(f"\n=== 按物料编号查询 [{code}] ===")
    if name:
        lines.append(f"\n=== 按物料名称查询 [{name}] ===")

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
        description="按物料编号或名称快速查询库存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --code 6B001492                  # 精确编码
  %(prog)s --name "730W"                     # 名称关键词
  %(prog)s --name "天合原装" --category 逆变器  # 限定品类
  %(prog)s --code AB001347 --aggregate --json # 聚合+JSON
  %(prog)s --code AB001347 --aggregate --json --output-file result.json
        """,
    )
    parser.add_argument('--code', help='物料编号（精确查询）')
    parser.add_argument('--name', help='物料名称/型号关键词（模糊查询）')
    parser.add_argument('--category', choices=VALID_CATEGORIES,
                        help='限定查询品类（不传则查全部）')
    parser.add_argument('--aggregate', action='store_true',
                        help='按物料编号聚合所有仓库的库存总量')
    parser.add_argument('--json', action='store_true',
                        help='JSON 格式输出')
    parser.add_argument('--output-file', help='输出到文件（默认输出到终端）')
    parser.add_argument('--file', help='库存文件路径（不传则自动查找最新）')
    args = parser.parse_args()

    if not args.code and not args.name:
        parser.print_help()
        print("\n[错误] 请提供 --code 或 --name", file=sys.stderr)
        sys.exit(1)

    # 加载数据（用 calamine 引擎，避免 openpyxl 报错）
    data = load_inventory(args.file)

    # 确定查询品类
    categories = [args.category] if args.category else VALID_CATEGORIES

    # 逐品类查询
    results = {}
    for cat in categories:
        meta = CATEGORY_META[cat]
        df = data.get(cat, pd.DataFrame())
        if df.empty:
            continue

        matched = lookup_by_code_or_name(df, args.code, args.name, meta)
        if matched.empty:
            results[cat] = None
            continue

        records = _build_category_result(matched, meta, args.aggregate)
        results[cat] = records

    # 输出
    if args.json:
        output = json.dumps(results, ensure_ascii=False, indent=2)
    else:
        output = format_text(results, args.code, args.name)

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
