"""DMS 周报核心业务模块。

该包包含以下模块：
  - dms_browser: Playwright 浏览器自动化（登录、筛选、提取）
  - bom_parser: BOM 物料解析（功率、容量计算）
  - approval_parser: 审批链信息解析
  - orders_checker: 下单检查和查询
  - excel_generator: Excel 报表生成
"""

__all__ = [
    "dms_browser",
    "bom_parser",
    "approval_parser",
    "orders_checker",
    "excel_generator",
]
