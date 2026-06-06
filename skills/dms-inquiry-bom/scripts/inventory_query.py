#!/usr/bin/env python3
"""库存查询脚本 - 快速查询组件、逆变器、并网箱库存。

支持缓存机制，首次读取后缓存到pickle文件，后续查询直接加载缓存，大幅提升速度。

用法：
  # 查询组件
  python inventory_query.py --type 组件 --power 715

  # 查询逆变器（天合原装专用）
  python inventory_query.py --type 逆变器 --brand 天合 --power 50

  # 查询并网箱
  python inventory_query.py --type 并网箱 --power 50

  # 刷新缓存
  python inventory_query.py --refresh

  # 输出JSON格式
  python inventory_query.py --type 逆变器 --brand 天合 --json
"""

import argparse
import json
import os
import pickle
import sys
from pathlib import Path

import pandas as pd

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

# 库存文件目录
INVENTORY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_latest_inventory_file() -> str:
    """自动查找目录下最新的库存文件。

    匹配模式: 组件、逆变器、并网箱可用库存统计*.xlsx
    按修改时间取最新文件。

    Returns:
        库存文件完整路径

    Raises:
        FileNotFoundError: 未找到匹配的库存文件
    """
    import glob
    pattern = os.path.join(INVENTORY_DIR, "组件、逆变器、并网箱可用库存统计*.xlsx")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(
            f"未找到库存文件（匹配模式: 组件、逆变器、并网箱可用库存统计*.xlsx）\n"
            f"请将库存文件放在: {INVENTORY_DIR}"
        )
    # 按修改时间降序，取最新文件
    latest = max(files, key=os.path.getmtime)
    return latest


# 默认库存文件路径（启动时自动查找最新文件）
try:
    DEFAULT_INVENTORY_FILE = _find_latest_inventory_file()
except FileNotFoundError:
    DEFAULT_INVENTORY_FILE = None

# 缓存文件路径
CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".inventory_cache.pkl"
)

# 缓存过期时间（秒）
CACHE_TTL = 3600  # 1小时


def load_inventory(file_path: str = None, force_refresh: bool = False) -> dict:
    """加载库存数据，支持缓存。

    Args:
        file_path: Excel文件路径
        force_refresh: 强制刷新缓存

    Returns:
        {"组件": DataFrame, "逆变器": DataFrame, "并网箱": DataFrame}
    """
    import time
    from datetime import datetime

    if file_path is None:
        file_path = _find_latest_inventory_file()

    # 检查缓存
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            cache_mtime = os.path.getmtime(CACHE_FILE)
            file_mtime = os.path.getmtime(file_path)
            cache_age = time.time() - cache_mtime

            if cache_age < CACHE_TTL and file_mtime <= cache_mtime:
                with open(CACHE_FILE, 'rb') as f:
                    cache_time = datetime.fromtimestamp(cache_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    age_minutes = int(cache_age / 60)
                    print(f"[缓存] 从缓存加载库存数据（更新时间: {cache_time}，已缓存{age_minutes}分钟）", file=sys.stderr)
                    if age_minutes > 30:
                        print(f"[提示] 缓存数据可能已过时，如需最新数据请使用 --refresh 参数", file=sys.stderr)
                    return pickle.load(f)
        except Exception:
            pass

    print("[读取] 正在读取Excel文件...", file=sys.stderr)

    # 读取各sheet
    df_comp = pd.read_excel(file_path, sheet_name='组件', engine='calamine', skiprows=1)
    df_inv = pd.read_excel(file_path, sheet_name='逆变器', engine='calamine', skiprows=1)
    df_box = pd.read_excel(file_path, sheet_name='并网箱', engine='calamine', skiprows=1)

    # 预处理：前向填充合并单元格
    df_inv['厂家'] = df_inv['厂家'].ffill()
    df_box['并网箱类型'] = df_box['并网箱类型'].ffill()

    # 重命名列
    df_inv = df_inv.rename(columns={'价格排序（数字越大则越贵）': '价格排序'})

    data = {
        "组件": df_comp,
        "逆变器": df_inv,
        "并网箱": df_box
    }

    # 保存缓存
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(data, f)
        print("[缓存] 库存数据已缓存", file=sys.stderr)
    except Exception as e:
        print(f"[警告] 缓存保存失败: {e}", file=sys.stderr)

    return data


def query_components(df: pd.DataFrame, power: int = None) -> pd.DataFrame:
    """查询组件库存。

    Args:
        df: 组件DataFrame
        power: 功率（如715），为空则返回全部

    Returns:
        筛选后的DataFrame
    """
    result = df.copy()
    if power:
        result = result[result['功率'].astype(str).str.contains(str(power))]
    return result[['物料编号', '物料名称', '功率', '可用库存', '仓库名称']]


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

    # 天合原装专用筛选
    if brand and '天合' in brand:
        result = result[result['物料名称'].astype(str).str.contains('天合原装专用')]

    # 功率筛选
    if power:
        result = result[result['功率'].astype(str).str.contains(f'{power}kW|{power}KW', case=False, na=False)]

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
    if power:
        result = result[result['功率'].astype(str).str.contains(f'{power}kW|{power}KW', case=False, na=False)]

    # 库存筛选
    if has_stock:
        result = result[result['可用库存'].notna() & (result['可用库存'] > 0)]

    return result[['并网箱类型', '功率', '物料编号', '物料名称', '可用库存', '仓库名称']]


def format_inverter_by_brand(df: pd.DataFrame) -> str:
    """按品牌分组格式化逆变器库存。"""
    import pandas as pd

    if df.empty:
        return "[结果] 未找到匹配的逆变器库存"

    lines = ["\n=== 逆变器库存查询结果（按品牌分组）==="]

    # 按品牌分组
    if '厂家' in df.columns:
        grouped = df.groupby('厂家')
        for brand, group in grouped:
            lines.append(f"\n【{brand}】")
            for _, row in group.iterrows():
                stock = row.get('可用库存', 0)
                stock_str = f"{int(stock)}台" if pd.notna(stock) and stock > 0 else "无库存"
                power = row.get('功率', '未知')
                code = row.get('物料编号', '')
                name = row.get('物料名称', '')
                # 提取简短名称（去掉前缀）
                short_name = name.split('_')[-1] if '_' in name else name
                price_rank = row.get('价格排序', '')
                price_str = f" (价格排序:{int(price_rank)})" if pd.notna(price_rank) else ""
                lines.append(f"  {power} | {code} | 库存:{stock_str}{price_str}")
    else:
        # 没有厂家列，直接输出
        lines.append(df.to_string(index=False))

    lines.append(f"\n共 {len(df)} 条记录")
    return "\n".join(lines)


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
    parser.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    parser.add_argument("--file", help="库存文件路径")
    args = parser.parse_args()

    # 加载数据
    data = load_inventory(args.file, args.refresh)

    if args.refresh and not args.type:
        print("[完成] 缓存已刷新", file=sys.stderr)
        return

    if not args.type:
        parser.print_help()
        return

    has_stock = not args.all and not args.no_stock

    # 查询
    if args.type == "组件":
        result = query_components(data["组件"], args.power)
    elif args.type == "逆变器":
        result = query_inverters(data["逆变器"], args.power, args.brand, has_stock)
    elif args.type == "并网箱":
        result = query_boxes(data["并网箱"], args.power, args.box_type, has_stock)

    # 输出
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


if __name__ == "__main__":
    main()
