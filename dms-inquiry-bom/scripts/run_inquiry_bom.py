#!/usr/bin/env python3
"""BOM清单Excel生成脚本。

支持单个或批量生成BOM清单文件，格式匹配产品物料导入模板。

用法：
  # 单个BOM
  python run_inquiry_bom.py --name "覃建发" --components 30 --items '[["6B001492",30],["AA001653",1]]'

  # 批量BOM
  python run_inquiry_bom.py --bom-list '[
    {"name": "覃建发", "components": 30, "items": [["6B001492",30],["AA001653",1]]},
    {"name": "蔡敏捷", "components": 185, "items": [["6B001492",185],["AB001347",2],["AB001067",1]]}
  ]' --output-dir "."
"""

import argparse
import json
import os
import sys
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side
import pandas as pd

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402


def validate_items(items: list, inventory_file: str) -> dict:
    """验证物料清单中的物料编号是否存在于库存文件中。

    Args:
        items: [[物料编号, 数量], ...]
        inventory_file: 库存 Excel 文件路径

    Returns:
        {
            "valid": [[物料编号, 数量, 物料名称], ...],
            "invalid": [物料编号, ...],
            "total": 总物料种类数,
            "valid_count": 存在的物料数,
            "invalid_count": 不存在的物料数
        }
    """
    material_ids = [item[0] for item in items]
    print(f"[验证] 正在验证 {len(material_ids)} 个物料编号...", file=sys.stderr)

    # 读取库存文件中所有物料编号
    known_materials = {}  # 物料编号 -> 物料名称
    try:
        xls = pd.ExcelFile(inventory_file, engine='calamine')
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(inventory_file, sheet_name=sheet_name, engine='calamine')
            for col in df.columns:
                if '物料编号' in str(col) or '物料编码' in str(col) or '编码' in str(col):
                    codes = df[col].astype(str).str.strip()
                    name_col = None
                    for nc in df.columns:
                        if '物料名称' in str(nc) or '名称' in str(nc):
                            name_col = nc
                            break
                    for idx, code in codes.items():
                        if code and code != 'nan':
                            name = str(df.iloc[idx].get(name_col, '')) if name_col else ''
                            if name == 'nan':
                                name = ''
                            known_materials[code] = name
                    break
    except Exception as e:
        print(f"[警告] 读取库存文件失败: {e}", file=sys.stderr)
        return {"valid": [], "invalid": material_ids, "total": len(material_ids),
                "valid_count": 0, "invalid_count": len(material_ids), "error": str(e)}

    valid = []
    invalid = []
    for code, qty in items:
        code_str = str(code).strip()
        if code_str in known_materials:
            valid.append([code, qty, known_materials[code_str]])
        else:
            invalid.append(code)
            print(f"  ❌ {code} — 未在库存文件中找到", file=sys.stderr)

    for code, qty, name in valid:
        name_display = f" ({name})" if name else ""
        print(f"  ✅ {code}{name_display} — 库存中存在", file=sys.stderr)

    print(f"[验证] 结果: {len(valid)} 个存在, {len(invalid)} 个不存在", file=sys.stderr)
    return {
        "valid": valid,
        "invalid": invalid,
        "total": len(material_ids),
        "valid_count": len(valid),
        "invalid_count": len(invalid)
    }


def generate_bom(name: str, components: int, items: list, output_dir: str = ".",
                 project: str = None) -> str:
    """生成单个BOM清单Excel文件。

    Args:
        name: 业务员姓名
        components: 组件总块数
        items: [[物料编号, 数量], ...]
        output_dir: 输出目录
        project: 项目名称（可选，用于文件命名）

    Returns:
        生成的文件路径
    """
    today = date.today().strftime("%Y%m%d")
    # 截取项目名称的关键部分（去掉"分布式光伏发电项目"等后缀）
    if project:
        # 提取项目简称（取前15个字符或到"分布式"/"光伏"等关键词前）
        project_short = project
        for keyword in ['分布式', '光伏', '发电', '项目']:
            idx = project_short.find(keyword)
            if idx > 0:
                project_short = project_short[:idx]
                break
        project_short = project_short[:15].rstrip('县市区镇村')  # 限制长度
        filename = f"{name}{components}块组件{project_short}{today}.xlsx"
    else:
        filename = f"{name}{components}块组件{today}.xlsx"
    filepath = os.path.join(output_dir, filename)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    header_font = Font(bold=True)
    header_align = Alignment(horizontal="center")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    ws["A1"] = "物料编号"
    ws["B1"] = "数量"
    ws["A1"].font = header_font
    ws["B1"].font = header_font
    ws["A1"].border = thin_border
    ws["B1"].border = thin_border
    ws["A1"].alignment = header_align
    ws["B1"].alignment = header_align

    for i, (material_id, qty) in enumerate(items, start=2):
        ws[f"A{i}"] = material_id
        ws[f"B{i}"] = qty
        ws[f"A{i}"].border = thin_border
        ws[f"B{i}"].border = thin_border
        ws[f"B{i}"].alignment = header_align

    ws.column_dimensions["A"].width = 15
    ws.column_dimensions["B"].width = 10

    wb.save(filepath)
    return filepath


def generate_multiple(bom_list: list, output_dir: str = ".") -> list:
    """批量生成BOM清单Excel文件。

    Args:
        bom_list: [{"name": "...", "components": N, "items": [[...], ...], "project": "..."}, ...]
        output_dir: 输出目录

    Returns:
        生成的文件路径列表
    """
    paths = []
    for spec in bom_list:
        name = spec["name"]
        components = spec["components"]
        items = spec["items"]
        project = spec.get("project")  # 可选的项目名称
        path = generate_bom(name, components, items, output_dir, project)
        paths.append(path)
        print(f"  {path}", file=sys.stderr)
    return paths


def parse_items(items_str: str) -> list:
    """解析items参数，支持两种格式：
    1. JSON数组格式: [["6B001492",30],["AA001653",1]]
    2. 简洁格式: 6B001492:30,AA001653:1

    Returns:
        [[物料编号, 数量], ...]
    """
    items_str = items_str.strip()

    # 尝试JSON格式
    if items_str.startswith('['):
        return json.loads(items_str)

    # 简洁格式: code:qty,code:qty
    items = []
    for pair in items_str.split(','):
        pair = pair.strip()
        if ':' in pair:
            code, qty = pair.split(':', 1)
            items.append([code.strip(), int(qty.strip())])
        elif 'x' in pair.lower():
            code, qty = pair.lower().split('x', 1)
            items.append([code.strip(), int(qty.strip())])

    return items


def main():
    parser = argparse.ArgumentParser(description="生成BOM清单Excel")
    parser.add_argument("--name", help="业务员姓名（单个模式）")
    parser.add_argument("--components", type=int, help="组件总块数（单个模式）")
    parser.add_argument("--items", help='物料清单，支持两种格式：\n'
                                         '  JSON: [["6B001492",30],["AA001653",1]]\n'
                                         '  简洁: 6B001492:30,AA001653:1')
    parser.add_argument("--project", help="项目名称（可选，用于文件命名）")
    parser.add_argument("--bom-list", help='批量模式：JSON数组，每项含 name/components/items/project')
    parser.add_argument("--output-dir", default=".", help="输出目录")
    parser.add_argument("--validate", action="store_true",
                        help="验证模式：检查物料编号是否存在于库存文件中（不生成BOM）")
    parser.add_argument("--inventory-file", help="库存Excel文件路径（用于 --validate 模式）")
    args = parser.parse_args()

    # --validate 模式：仅验证物料，不生成 BOM
    if args.validate:
        if not args.items:
            print("[错误] --validate 模式需要 --items 参数", file=sys.stderr)
            raise SystemExit(1)
        if not args.inventory_file:
            # 尝试自动查找库存文件
            skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for search_dir in [os.path.join(skill_dir, "assets"), skill_dir]:
                pattern = os.path.join(search_dir, "组件、逆变器、并网箱可用库存统计*.xlsx")
                import glob
                files = glob.glob(pattern)
                if files:
                    args.inventory_file = max(files, key=os.path.getmtime)
                    break
        if not args.inventory_file:
            print("[错误] --validate 模式需要 --inventory-file 参数指定库存文件路径", file=sys.stderr)
            raise SystemExit(1)

        items = parse_items(args.items)
        result = validate_items(items, args.inventory_file)
        # stdout 输出 JSON 结果供上层读取
        print(json.dumps(result, ensure_ascii=False))
        return

    os.makedirs(args.output_dir, exist_ok=True)

    if args.bom_list:
        # 批量模式
        bom_list = json.loads(args.bom_list)
        print(f"[BOM] 批量生成 {len(bom_list)} 个文件:", file=sys.stderr)
        paths = generate_multiple(bom_list, args.output_dir)
        # stdout输出文件路径列表（供Claude读取）
        print(json.dumps(paths, ensure_ascii=False))
    elif args.name and args.components is not None and args.items:
        # 单个模式
        items = parse_items(args.items)
        path = generate_bom(args.name, args.components, items, args.output_dir, args.project)
        print(f"[BOM] 已生成: {path}", file=sys.stderr)
        print(path)
    else:
        print("[错误] 请提供 --name/--components/--items（单个模式）或 --bom-list（批量模式）", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
