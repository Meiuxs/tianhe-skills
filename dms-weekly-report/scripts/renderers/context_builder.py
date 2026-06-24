"""Jinja2 模板渲染上下文构建器。

职责：
  将业务数据（rows_detail、query_range 等）转换为 Jinja2 模板上下文 dict。
  所有 {{PLACEHOLDER}} 在此统一映射，由 HtmlReportRenderer.render() 的
  render_template(context=…) 一次性注入。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from renderers.data_transform import RowDetail, compute_aggregations


def _serialize_rows_detail(rows_detail: list[RowDetail]) -> str:
    """将 ROWS_DETAIL 序列化为安全的 JSON 字符串（XSS 防护）。"""
    json_str = json.dumps(rows_detail, ensure_ascii=False, separators=(",", ": "))
    json_str = json_str.replace("<", "\\u003c").replace(">", "\\u003e").replace("/", "\\u002f")
    return json_str


def _serialize_aggregations(rows_detail: list[RowDetail]) -> str:
    """预计算聚合统计并序列化为安全 JSON。"""
    aggs = compute_aggregations(rows_detail)
    json_str = json.dumps(aggs, ensure_ascii=False, separators=(",", ": "))
    json_str = json_str.replace("<", "\\u003c").replace(">", "\\u003e").replace("/", "\\u002f")
    return json_str


class ReportContextBuilder:
    """构建 Jinja2 模板渲染上下文。

    用法：
        builder = ReportContextBuilder()
        context = builder.build(rows_detail, "2026-06-01 ~ 2026-06-07")
    """

    def build(
        self,
        rows_detail: list[RowDetail],
        query_range: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """构建完整渲染上下文。

        Args:
            rows_detail: compute_rows_detail 的输出。
            query_range: 查询范围文本（如 "2026-06-01 ~ 2026-06-07"）。
            now: 当前时间，默认 datetime.now()（便于测试注入）。

        Returns:
            Jinja2 模板上下文字典。
        """
        if now is None:
            now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M")

        # 从 query_range 解析起止日期（格式 "2026-06-08 ~ 2026-06-12"）
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})', query_range)
        query_start = date_match.group(1) if date_match else ''
        query_end = date_match.group(2) if date_match else ''

        return {
            # 文本占位符
            "REPORT_DATE_RANGE": query_range,
            "REPORT_GENERATED_AT": f"生成于 {now_str}",
            "DATA_SCOPE_TEXT": f"数据范围：{query_range} | 统计截止：{now.strftime('%Y-%m-%d')}",
            "FOOTER_TEXT": "询价周报报表 · 数据来源：DMS 流程中心 · 仅供内部参考",
            "SERVER_TIMESTAMP": now.isoformat(),
            "QUERY_START_DATE": query_start,
            "QUERY_END_DATE": query_end,
            # JSON 数据源（预序列化 + XSS 转义）
            "ROWS_DETAIL_JSON": _serialize_rows_detail(rows_detail),
            # 预计算聚合统计（供模板直接使用，减轻前端 JS 负担）
            "AGGREGATIONS_JSON": _serialize_aggregations(rows_detail),
        }
