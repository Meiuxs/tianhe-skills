"""报表渲染模块包。

包含：
  - data_reader:       XlsxDataReader — xlsx 数据源读取
  - data_transform:    Excel 原始行 → 有名字典列表 + 聚合统计
  - context_builder:   Jinja2 模板渲染上下文构建器
  - renderer:          HtmlReportRenderer 核心渲染器
  - template_engine:   Jinja2 引擎封装
  - cli_entry:         命令行入口
"""

from renderers.context_builder import ReportContextBuilder
from renderers.data_reader import XlsxDataReader, read_rows_from_xlsx
from renderers.data_transform import (
    RowDetail,
    _format_datetime,
    _safe_float,
    compute_aggregations,
    compute_rows_detail,
)
from renderers.renderer import HtmlReportRenderer

__all__ = [
    "RowDetail",
    "XlsxDataReader",
    "ReportContextBuilder",
    "HtmlReportRenderer",
    "compute_rows_detail",
    "compute_aggregations",
    "read_rows_from_xlsx",
    "_format_datetime",
    "_safe_float",
]
