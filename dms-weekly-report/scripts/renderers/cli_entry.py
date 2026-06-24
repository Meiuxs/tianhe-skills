"""命令行入口模块。

架构定位：
  本模块是 generate_html_report.py 的 CLI 入口拆分。
  数据读取逻辑已移交 renderers/data_reader.py。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from renderers.data_reader import read_rows_from_xlsx


def main() -> None:
    """CLI 入口：从 xlsx 读取数据 → 生成 HTML 报表。"""
    import argparse

    from generate_html_report import generate_html_report

    parser = argparse.ArgumentParser(description="从 xlsx 生成 HTML 周报报表")
    parser.add_argument("--xlsx", required=True, help="输入的 xlsx 文件路径")
    parser.add_argument("--output", default="", help="输出的 html 文件路径（默认自动带时间戳）")
    parser.add_argument("--range", default="", help="查询范围文本，如 '2026-06-01 ~ 2026-06-07'")
    args = parser.parse_args()

    rows = read_rows_from_xlsx(args.xlsx)
    now = datetime.now()
    query_range = args.range or f"{now.strftime('%Y-%m-%d')} 数据"
    if not args.output:
        xlsx_dir = os.path.dirname(os.path.abspath(args.xlsx))
        args.output = f"{xlsx_dir}/询价周报报表_{now.strftime('%Y%m%d_%H%M%S')}.html"
    output = generate_html_report(rows, query_range, args.output)
    print(f"HTML 报表已生成：{output}")


if __name__ == "__main__":
    main()
