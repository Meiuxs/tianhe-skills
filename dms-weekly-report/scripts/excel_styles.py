"""Excel 样式主题配置 — 专业报表风格（Corporate Blue）。

架构定位：
  本模块是所有 Excel 样式的唯一来源，被 run_weekly_report.py 导入。
  提供字体、填充、对齐、边框等共享样式常量和布局辅助函数。
  修改配色/字体只需在本模块调整，所有 Sheet 自动生效。

样式体系：
  Colors         — 调色板常量（主色、功能色、文字色）
  FONT_*         — 字体预设（标题、表头、数据、KPI 等）
  FILL_*         — 填充预设（深蓝表头、浅蓝底、卡片底色）
  ALIGN_*        — 对齐预设
  apply_*        — 快捷应用函数（apply_header_style, apply_data_row）
  write_*        — 写入函数（write_section_title, write_kpi_card）
"""

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# ==================== 通用边框 ====================

THIN_BORDER = Border(
    left=Side("thin"), right=Side("thin"),
    top=Side("thin"), bottom=Side("thin"),
)

BOTTOM_BORDER = Border(
    bottom=Side("medium", color="1F4E79"),
    left=Side("thin"), right=Side("thin"),
    top=Side("thin"),
)

# ==================== 调色板 ====================

class Colors:
    TITLE_BLUE = "1F4E79"       # 主标题
    ACCENT_BLUE = "4472C4"      # 强调蓝
    HEADER_FILL = "1F4E79"      # 表头背景（深蓝）
    LIGHT_FILL = "D6E4F0"       # 浅蓝底
    VERY_LIGHT_FILL = "F2F7FB"  # 极浅蓝底（交替行）
    WHITE = "FFFFFF"            # 白色
    RED_ACCENT = "C00000"       # KPI 红色强调
    GRAY_TEXT = "808080"        # 辅助文字
    DARK_TEXT = "333333"        # 正文文字
    CARD_FILL = "F5F5F5"        # 卡片底色

# ==================== 字体 ====================

FONT_TITLE = Font(bold=True, size=16, color=Colors.TITLE_BLUE)
FONT_SECTION = Font(bold=True, size=12, color=Colors.ACCENT_BLUE)
FONT_SUBSECTION = Font(bold=True, size=11, color=Colors.ACCENT_BLUE)
FONT_HEADER = Font(bold=True, size=11, color=Colors.WHITE)
FONT_DATA = Font(size=11, color=Colors.DARK_TEXT)
FONT_LABEL = Font(bold=True, size=11, color=Colors.DARK_TEXT)
FONT_KPI_BIG = Font(bold=True, size=20, color=Colors.RED_ACCENT)
FONT_KPI_MED = Font(bold=True, size=14, color=Colors.RED_ACCENT)
FONT_HINT = Font(size=9, color=Colors.GRAY_TEXT)
FONT_VALUE = Font(size=11, color=Colors.ACCENT_BLUE)

# ==================== 填充 ====================

FILL_HEADER = PatternFill(start_color=Colors.HEADER_FILL, end_color=Colors.HEADER_FILL, fill_type="solid")
FILL_LIGHT = PatternFill(start_color=Colors.LIGHT_FILL, end_color=Colors.LIGHT_FILL, fill_type="solid")
FILL_VERY_LIGHT = PatternFill(start_color=Colors.VERY_LIGHT_FILL, end_color=Colors.VERY_LIGHT_FILL, fill_type="solid")
FILL_CARD = PatternFill(start_color=Colors.CARD_FILL, end_color=Colors.CARD_FILL, fill_type="solid")

# ==================== 对齐 ====================

ALIGN_CENTER = Alignment(vertical="center", horizontal="center")
ALIGN_LEFT = Alignment(vertical="center", horizontal="left")
ALIGN_HEADER = Alignment(wrap_text=True, vertical="center", horizontal="center")
ALIGN_DATA = Alignment(vertical="center", horizontal="center")

# ==================== 行高 / 列宽 ====================

ROW_HEIGHT_TITLE = 40
ROW_HEIGHT_SECTION = 30
ROW_HEIGHT_DATA = 26
ROW_HEIGHT_HEADER = 32

# 询价汇总 Sheet 列宽
COLUMN_WIDTHS: list[int] = [
    22, 40, 16, 28, 16, 12, 16, 18, 18,
    14, 16, 24, 28, 12, 14, 14, 14, 14, 24,
]


def apply_header_style(ws, row: int, headers: list[str], start_col: int = 1) -> None:
    """给指定行应用深蓝表头样式。"""
    for col, h in enumerate(headers, start_col):
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = THIN_BORDER
        cell.alignment = ALIGN_HEADER


def apply_data_row(ws, row: int, values: list, start_col: int = 1, is_alt: bool = False) -> None:
    """给数据行应用标准样式，支持交替行色。"""
    fill = FILL_VERY_LIGHT if is_alt else None
    for col, val in enumerate(values, start_col):
        cell = ws.cell(row=row, column=col, value=val)
        cell.font = FONT_DATA
        cell.border = THIN_BORDER
        cell.alignment = ALIGN_CENTER
        if fill:
            cell.fill = fill


def write_section_title(ws, row: int, col: int, title: str, merge_end_col: int | None = None) -> int:
    """写入节标题，可选合并单元格，返回下一行号。"""
    cell = ws.cell(row=row, column=col, value=title)
    cell.font = FONT_SECTION
    cell.alignment = ALIGN_CENTER
    if merge_end_col:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=merge_end_col)
    ws.row_dimensions[row].height = ROW_HEIGHT_SECTION
    return row + 1


def write_kpi_card(ws, row: int, col: int, label: str, value, unit: str = "",
                   value_font=None, alt_fill: bool = False) -> None:
    """写入 KPI 卡片（label + value + 可选单位）。"""
    c1 = ws.cell(row=row, column=col, value=label)
    c1.font = FONT_LABEL
    c1.alignment = ALIGN_CENTER
    c1.border = THIN_BORDER
    if alt_fill:
        c1.fill = FILL_LIGHT

    c2 = ws.cell(row=row, column=col + 1, value=value)
    c2.font = value_font or FONT_KPI_BIG
    c2.alignment = ALIGN_CENTER
    c2.border = THIN_BORDER
    if alt_fill:
        c2.fill = FILL_LIGHT

    if unit:
        c3 = ws.cell(row=row, column=col + 2, value=unit)
        c3.font = FONT_DATA
        c3.alignment = ALIGN_CENTER
        c3.border = THIN_BORDER
        if alt_fill:
            c3.fill = FILL_LIGHT

    ws.row_dimensions[row].height = ROW_HEIGHT_DATA
