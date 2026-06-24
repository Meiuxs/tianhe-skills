"""HTML 周报报表渲染器。

架构定位：
  本模块是生成 HTML 报表的核心编排类（Renderer 模式）。
  封装了：数据映射 → 上下文构建 → Jinja2 渲染 → 文件输出 的完整管道。

用法：
    from renderers.renderer import HtmlReportRenderer

    renderer = HtmlReportRenderer()
    renderer.render(rows_data, "2026-06-01 ~ 2026-06-07", "report.html")
"""

from __future__ import annotations

import html
import os
import sys
from typing import Any

from column_definitions import COL_FLOW_ID
from renderers.context_builder import ReportContextBuilder
from renderers.data_transform import compute_rows_detail
from renderers.template_engine import render_template as _render_template


class HtmlReportRenderer:
    """HTML 周报报表渲染器。

    Attributes:
        context_builder: 渲染上下文构建器。
        template_name: Jinja2 模板文件名（默认 index.html）。
    """

    def __init__(
        self,
        context_builder: ReportContextBuilder | None = None,
        template_name: str = "index.html",
    ):
        self.context_builder = context_builder or ReportContextBuilder()
        self.template_name = template_name

    # ── 空数据处理 ──

    @staticmethod
    def _write_minimal_html(output_path: str, query_range: str) -> str:
        """无有效数据时输出最小 HTML。返回 output_path。"""
        minimal_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>询价周报报表</title></head>
<body style="font-family: sans-serif; padding: 48px; text-align: center; color: #666;">
<h2>询价周报报表</h2>
<p>暂无数据</p>
<p style="font-size: 0.9em; color: #999;">数据范围：{html.escape(query_range)}</p>
</body>
</html>"""
        output_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(minimal_html)
        return output_path

    # ── 流程编号精度警告 ──

    @staticmethod
    def _warn_float_fids(rows_data: list[list[Any]]) -> None:
        """检查是否有 float 类型的流程编号，打印精度丢失提醒。"""
        float_fids = sum(
            1 for row in rows_data
            if isinstance(row[COL_FLOW_ID], float)
        )
        if float_fids > 0:
            print(
                f"[提醒] 有 {float_fids} 行的流程编号以数字格式存储在 Excel 中。"
                "超过 15 位的编号可能已丢失精度（建议在 Excel 中将该列设为「文本」后重新导出）。",
                file=sys.stderr,
            )

    # ── 核心渲染 ──

    def render(
        self,
        rows_data: list[list[Any]],
        query_range: str,
        output_path: str,
    ) -> str:
        """从 rows_data 生成 HTML 报表文件，返回输出路径。

        Args:
            rows_data: 询价数据行，每行 21 列。
            query_range: 查询范围文本（如 "2026-06-01 ~ 2026-06-07"）。
            output_path: 输出 HTML 文件路径。

        Returns:
            输出文件的路径。
        """
        # 1. 数据映射：Excel 原始行 → 有名字典列表
        rows_detail = compute_rows_detail(rows_data)

        # 2. 空数据场景防御
        if not rows_detail:
            return self._write_minimal_html(output_path, query_range)

        # 3. 流程编号精度警告
        self._warn_float_fids(rows_data)

        # 4. 构建 Jinja2 渲染上下文
        context = self.context_builder.build(rows_detail, query_range)

        # 5. Jinja2 渲染（处理 extends/include + {{PLACEHOLDER}}）
        html_content = _render_template(
            template_name=self.template_name,
            context=context,
        )

        # 6. 输出文件
        output_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path
