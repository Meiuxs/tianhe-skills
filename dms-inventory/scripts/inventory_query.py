#!/usr/bin/env python3
"""Role: 查询引擎 — 加载 Excel 库存文件，提供组件/逆变器/并网箱的底层查询和聚合函数。
被编排器、逆变器配置器和快捷查询脚本共同依赖。

库存查询脚本 - 快速查询组件、逆变器、并网箱库存。

用法：
  # 查询组件
  python inventory_query.py --type 组件 --power 715

  # 查询逆变器（天合原装专用）
  python inventory_query.py --type 逆变器 --brand 天合 --power 50

  # 查询并网箱
  python inventory_query.py --type 并网箱 --power 50

  # 输出JSON格式
  python inventory_query.py --type 逆变器 --brand 天合 --json

  # 输出到文件（避免管道中文乱码）
  python inventory_query.py --type 组件 --power 730 --json --aggregate --output-file result.json
"""

import argparse
import glob
import json
import os
import sys

import pandas as pd

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

# 库存文件目录
INVENTORY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_latest_inventory_file() -> str:
    """查找 assets/ 下的库存文件。

    匹配模式: 组件、逆变器、并网箱可用库存统计*.xlsx
    文件名含日期后缀，按修改时间取最新。

    Returns:
        库存文件完整路径

    Raises:
        FileNotFoundError: 未找到匹配的库存文件
    """
    assets_dir = os.path.join(INVENTORY_DIR, "assets")
    pattern = os.path.join(assets_dir, "组件、逆变器、并网箱可用库存统计*.xlsx")
    files = glob.glob(pattern)
    if files:
        return max(files, key=os.path.getmtime)

    raise FileNotFoundError(
        f"未找到库存文件\n"
        f"  搜索目录: {assets_dir}\n"
        f"  匹配模式: 组件、逆变器、并网箱可用库存统计*.xlsx\n"
        f"  请将库存文件放在 {assets_dir} 目录下"
    )


# 默认库存文件路径（惰性初始化）
_DEFAULT_FILE_CACHE = None

def _get_default_file():
    """惰性获取默认库存文件。"""
    global _DEFAULT_FILE_CACHE
    if _DEFAULT_FILE_CACHE is None:
        try:
            _DEFAULT_FILE_CACHE = _find_latest_inventory_file()
        except FileNotFoundError:
            _DEFAULT_FILE_CACHE = None
    return _DEFAULT_FILE_CACHE

# 向后兼容：DEFAULT_INVENTORY_FILE 依然可用
DEFAULT_INVENTORY_FILE = None


def load_inventory(file_path: str = None, sheet_name: str = None) -> dict:
    """加载库存数据。

    Args:
        file_path: Excel文件路径
        sheet_name: 指定读取的工作表名称（如'组件'、'逆变器'、'并网箱'），
                    为 None 时读取全部标准 sheet

    Returns:
        {"组件": DataFrame, "逆变器": DataFrame, "并网箱": DataFrame}
        或指定 sheet 时的 {"<sheet_name>": DataFrame}
    """
    if file_path is None:
        file_path = _get_default_file()
        if file_path is None:
            raise FileNotFoundError("未找到库存文件，请检查 assets/ 目录")

    # 如果指定了单一 sheet，直接读取
    if sheet_name:
        print(f"[读取] 正在读取工作表: {sheet_name}", file=sys.stderr)
        df = pd.read_excel(file_path, sheet_name=sheet_name, engine='calamine')
        return {sheet_name: df}

    print("[读取] 正在读取Excel文件...", file=sys.stderr)

    # 读取各sheet
    try:
        df_comp = pd.read_excel(file_path, sheet_name='组件', engine='calamine', skiprows=1)
    except ValueError:
        print("[警告] Excel文件中未找到'组件'工作表，跳过", file=sys.stderr)
        df_comp = pd.DataFrame()
    try:
        df_inv = pd.read_excel(file_path, sheet_name='逆变器', engine='calamine', skiprows=1)
    except ValueError:
        print("[警告] Excel文件中未找到'逆变器'工作表，跳过", file=sys.stderr)
        df_inv = pd.DataFrame()
    try:
        df_box = pd.read_excel(file_path, sheet_name='并网箱', engine='calamine', skiprows=1)
    except ValueError:
        print("[警告] Excel文件中未找到'并网箱'工作表，跳过", file=sys.stderr)
        df_box = pd.DataFrame()

    # 预处理：前向填充合并单元格
    for col in ['物料编号', '物料编码', '功率', '物料名称']:
        if col in df_comp.columns:
            df_comp[col] = df_comp[col].ffill()
        if col in df_inv.columns:
            df_inv[col] = df_inv[col].ffill()
        if col in df_box.columns:
            df_box[col] = df_box[col].ffill()
    if '厂家' in df_inv.columns:
        df_inv['厂家'] = df_inv['厂家'].ffill()
    if '并网箱类型' in df_box.columns:
        df_box['并网箱类型'] = df_box['并网箱类型'].ffill()

    # 重命名列
    df_inv = df_inv.rename(columns={'价格排序（数字越大则越贵）': '价格排序'})

    data = {
        "组件": df_comp,
        "逆变器": df_inv,
        "并网箱": df_box
    }

    return data


def query_components(df: pd.DataFrame, power: int = None, has_stock: bool = True) -> pd.DataFrame:
    """查询组件库存。

    Args:
        df: 组件DataFrame
        power: 功率（如715），为空则返回全部

    Returns:
        筛选后的DataFrame
    """
    result = df.copy()
    if power is not None:
        if not isinstance(power, (int, float)):
            raise TypeError(f"power must be int or float, got {type(power).__name__}")
        result = result[result['功率'].astype(str).str.contains(rf'(?<!\d){power}(?!\d)')]
    if has_stock:
        result = result[result['可用库存'].notna() & (result['可用库存'] > 0)]
    cols = ['物料编号', '物料名称', '功率', '可用库存']
    if '备注' in result.columns:
        cols.append('备注')
    if '仓库名称' not in result.columns:
        result['仓库名称'] = ''
    cols.append('仓库名称')
    return result[cols]


def query_inverters(df: pd.DataFrame, power: int = None, brand: str = None,
                    has_stock: bool = True) -> pd.DataFrame:
    """查询逆变器库存。

    Args:
        df: 逆变器DataFrame
        power: 功率（如50），为空则返回全部
        brand: 品牌关键词（如"天合"），为空则返回全部
        has_stock: 是否只显示有库存的

    Returns:
        筛选后的DataFrame
    """
    result = df.copy()

    # 品牌筛选（按厂家列或物料名称列的天合原装专用）
    if brand:
        # 天合品牌特殊处理：天合原装专用标识在物料名称列
        if '天合' in brand:
            result = result[
                result['厂家'].astype(str).str.contains(brand, na=False, regex=False)
                | result['物料名称'].astype(str).str.contains('天合原装专用', na=False, regex=False)
            ]
        else:
            result = result[result['厂家'].astype(str).str.contains(brand, na=False, regex=False)]

    # 功率筛选（支持给定功率或模式）
    if power is not None:
        result = result[result['功率'].astype(str).str.contains(rf'(?<!\d){power}(?!\d)')]

    # 库存筛选
    if has_stock:
        result = result[result['可用库存'].notna() & (result['可用库存'] > 0)]

    return result[['厂家', '功率', '物料编号', '物料名称', '可用库存', '备注', '价格排序']]


def query_boxes(df: pd.DataFrame, power: int = None, box_type: str = None,
                has_stock: bool = True) -> pd.DataFrame:
    """查询并网箱库存。

    Args:
        df: 并网箱DataFrame
        power: 功率（如50），为空则返回全部
        box_type: 并网箱类型关键词，为空则返回全部
        has_stock: 是否只显示有库存的

    Returns:
        筛选后的DataFrame
    """
    result = df.copy()

    # 类型筛选
    if box_type:
        result = result[result['并网箱类型'].astype(str).str.contains(box_type, na=False)]

    # 功率筛选
    if power is not None:
        result = result[result['功率'].astype(str).str.contains(rf'(?<!\d){power}(?!\d)')]

    # 库存筛选
    if has_stock:
        result = result[result['可用库存'].notna() & (result['可用库存'] > 0)]

    cols = ['并网箱类型', '功率', '物料编号', '物料名称', '可用库存']
    if '备注' in result.columns:
        cols.append('备注')
    if '仓库名称' not in result.columns:
        result['仓库名称'] = ''
    cols.append('仓库名称')
    return result[cols]


def format_inverter_by_brand(df: pd.DataFrame) -> str:
    """按品牌分组格式化逆变器库存。"""

    if df.empty:
        return "[结果] 未找到匹配的逆变器库存"

    lines = ["\n=== 逆变器库存查询结果（按品牌分组）==="]

    # 按品牌分组
    if '厂家' in df.columns:
        grouped = df.groupby('厂家')
        for manufacturer, group in grouped:
            lines.append(f"\n【{manufacturer}】")
            for _, row in group.iterrows():
                stock = row.get('可用库存', 0)
                stock_str = f"{int(stock)}台" if pd.notna(stock) and stock > 0 else "无库存"
                power = row.get('功率', '未知')
                code = row.get('物料编号', '')
                name = row.get('物料名称', '')
                # 提取简短名称（去掉前缀）
                short_name = name.split('_')[-1] if pd.notna(name) and '_' in name else (name if pd.notna(name) else '未知')
                price_rank = row.get('价格排序', '')
                price_str = f" (价格排序:{int(price_rank)})" if pd.notna(price_rank) else ""
                lines.append(f"  {power} | {code} | 库存:{stock_str}{price_str}")
    else:
        # 没有厂家列，直接输出
        lines.append(df.to_string(index=False))

    lines.append(f"\n共 {len(df)} 条记录")
    return "\n".join(lines)


def aggregate_stock(df: pd.DataFrame, material_col: str = '物料编号',
                    name_col: str = '物料名称', qty_col: str = '可用库存',
                    warehouse_col: str = '仓库名称',
                    keep_zero: bool = False) -> pd.DataFrame:
    """按物料编码聚合所有仓库的库存总量。

    Args:
        df: 库存 DataFrame
        material_col: 物料编码列名
        name_col: 物料名称列名
        qty_col: 可用库存列名
        warehouse_col: 仓库名称列名
        keep_zero: 是否保留库存为 0 的物料（默认 False，仅用于 lookup 场景）

    Returns:
        聚合后的 DataFrame，含 物料编号、物料名称、库存总量、仓库分布
    """
    if df.empty:
        return df

    result = df.copy()
    # 前向填充物料编码（处理 Excel merged cell 问题）
    result[material_col] = result[material_col].ffill()
    # 将 NaN 库存视为 0
    result[qty_col] = pd.to_numeric(result[qty_col], errors='coerce').fillna(0)

    agg_dict = {
        '库存总量': (qty_col, 'sum'),
        '物料名称': (name_col, 'first'),
    }

    # 按物料编码分组聚合
    agg = result.groupby(material_col, as_index=False, dropna=False).agg(**agg_dict)

    # 仓库分布 - 在 agg 外单独计算（agg lambda 无法获取分组 key，需用 apply）
    if warehouse_col and warehouse_col in result.columns:
        def _calc_dist(grp):
            parts = []
            for _, r in grp.iterrows():
                q = pd.to_numeric(r[qty_col], errors='coerce')
                if pd.notna(q) and q > 0:
                    parts.append(f"{r[warehouse_col]}({int(q)}台)")
                elif keep_zero:
                    parts.append(f"{r[warehouse_col]}({int(q) if pd.notna(q) else 0}台)")
            return ', '.join(parts)

        dist = result.groupby(material_col).apply(_calc_dist).reset_index()
        dist.columns = [material_col, '仓库分布']
        agg = agg.merge(dist, on=material_col, how='left')
        agg['仓库分布'] = agg['仓库分布'].fillna('')

    # 如果有多列，保留额外信息（如品牌、功率等）
    extra_cols = [c for c in df.columns if c not in [material_col, name_col, qty_col, warehouse_col]]
    extra_cols_present = [c for c in extra_cols if c in result.columns and c not in agg.columns]
        # 注意：同一物料编码可能有多个不同的额外列值，.first() 仅取第一个
    if extra_cols_present:
        extra = result.groupby(material_col, as_index=False, dropna=False)[extra_cols_present].first()
        agg = agg.merge(extra, on=material_col, how='left')

    # 排序：库存量降序
    agg = agg.sort_values('库存总量', ascending=False).reset_index(drop=True)
    # 只保留库存 > 0 的（除非 keep_zero=True）
    if not keep_zero:
        agg = agg[agg['库存总量'] > 0]

    return agg


def main():
    parser = argparse.ArgumentParser(description="库存查询工具")
    parser.add_argument("--type", choices=["组件", "逆变器", "并网箱"], help="查询类型")
    parser.add_argument("--power", type=int, help="功率（如715、50）")
    parser.add_argument("--brand", help="品牌关键词（如天合）")
    parser.add_argument("--box-type", help="并网箱类型关键词")
    parser.add_argument("--no-stock", action="store_true", help="显示无库存的")
    parser.add_argument("--all", action="store_true", help="显示全部（包括无库存）")
    parser.add_argument("--json", action="store_true", help="输出JSON格式")
    parser.add_argument("--group-by-brand", action="store_true", help="按品牌分组显示（仅逆变器）")
    parser.add_argument("--aggregate", action="store_true",
                        help="按物料编码聚合所有仓库的库存总量（显示每个物料的合计库存和仓库分布）")
    parser.add_argument("--file", help="库存文件路径")
    parser.add_argument("--sheet", help="指定读取的工作表名称（默认自动读取对应类型的标准sheet）")
    parser.add_argument("--output-file", help="输出到文件（默认输出到标准输出），解决管道传输中文乱码问题")
    args = parser.parse_args()

    # --output-file 重定向 stdout
    _output_file = None
    if args.output_file:
        out_path = os.path.abspath(args.output_file)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        _output_file = open(out_path, 'w', encoding='utf-8')
        sys.stdout = _output_file

    try:

        # 加载数据
        data = load_inventory(args.file, sheet_name=args.sheet)

        if not args.type:
            parser.print_help()
            return

        # --all 和 --no-stock 均不过滤库存
        has_stock = not (args.all or args.no_stock)

        # 查询
        if args.type == "组件":
            result = query_components(data["组件"], args.power, has_stock=has_stock)
        elif args.type == "逆变器":
            result = query_inverters(data["逆变器"], args.power, args.brand, has_stock)
        elif args.type == "并网箱":
            result = query_boxes(data["并网箱"], args.power, args.box_type, has_stock)

        # 输出
        if args.aggregate:
            result = aggregate_stock(result)
            if args.json:
                print(result.to_json(orient='records', force_ascii=False))
            else:
                if result.empty:
                    print(f"[结果] 未找到匹配的{args.type}库存（或库存均为0）")
                else:
                    print(f"\n=== {args.type}库存聚合结果（按物料编码汇总）===")
                    print(result.to_string(index=False))
                    print(f"\n共 {len(result)} 条记录（已聚合所有仓库）")
            return

        if args.json:
            print(result.to_json(orient='records', force_ascii=False))
        elif args.type == "逆变器" and args.group_by_brand:
            # 逆变器按品牌分组显示
            print(format_inverter_by_brand(result))
        else:
            if result.empty:
                print(f"[结果] 未找到匹配的{args.type}库存")
            else:
                print(f"\n=== {args.type}库存查询结果 ===")
                print(result.to_string(index=False))
                print(f"\n共 {len(result)} 条记录")


    finally:
        if _output_file is not None:
            _output_file.close()
            if sys.stdout is _output_file:
                sys.stdout = sys.__stdout__


if __name__ == "__main__":
    main()
