"""从 xlsx 数据生成 HTML 周报报表 — 薄入口函数。

完整渲染逻辑在 renderers/ 包中（HtmlReportRenderer），
本文件仅提供向后兼容的导入入口和 CLI 入口。

用法：
    from generate_html_report import generate_html_report
    generate_html_report(rows_data, "2026-06-01 ~ 2026-06-07", "report.html")
"""

from __future__ import annotations

import json
from typing import Any

# 向后兼容导出（外部代码仍可 from generate_html_report import ...）
from renderers.data_transform import (
    RowDetail,
    _format_datetime,
    _safe_float,
    compute_rows_detail,
)
from renderers.data_reader import read_rows_from_xlsx
from renderers.renderer import HtmlReportRenderer


# ==================== 模板渲染工具（保留向后兼容）====================


def _simple_replace(template: str, replacements: dict[str, str]) -> str:
    """将模板中的 {{KEY}} 替换为对应的 value。"""
    result = template
    for key, value in replacements.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


def _replace_json_field(template: str, field_name: str, data: Any) -> str:
    """将模板中的 {{FIELD_NAME_JSON}} 替换为安全的 JSON 字符串。"""
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
    json_str = json_str.replace("<", "\\u003c").replace(">", "\\u003e").replace("/", "\\u002f")
    return template.replace("{{" + field_name + "_JSON}}", json_str)


# ==================== 主函数 ====================


def generate_html_report(
    rows_data: list[list[Any]],
    query_range: str,
    output_path: str,
    template_path: str | None = None,
) -> str:
    """从 rows_data 生成 HTML 报表文件，返回输出路径。

    委托给 HtmlReportRenderer.render()。

    Args:
        rows_data: 询价数据行，每行 20 列。
        query_range: 查询范围文本（如 "2026-06-01 ~ 2026-06-07"）。
        output_path: 输出 HTML 文件路径。
        template_path: （已废弃）兼容旧接口，不再影响渲染行为。

    Returns:
        输出文件的路径。
    """
    renderer = HtmlReportRenderer()
    return renderer.render(rows_data, query_range, output_path)


# ==================== CLI 入口 ====================


def main() -> None:
    """委托给 renderers/cli_entry.py 中的 CLI 实现。"""
    from renderers.cli_entry import main as _cli_main
    _cli_main()


if __name__ == "__main__":
    main()
