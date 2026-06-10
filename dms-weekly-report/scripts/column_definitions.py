"""Excel 列定义和常量集中管理。

架构定位：
  本模块是所有列索引、表头、常量的唯一真实源。
  被 run_weekly_report.py 和 generate_html_report.py 共享导入。
  修改列时仅需在此处更新，所有模块自动同步。
"""

# ==================== Excel 列定义 ====================

HEADERS = [
    "流程编号",
    "项目名称",
    "代理商编号",
    "代理商名称",
    "省公司",
    "业务员",
    "组件总功率(kW)",
    "逆变器总功率(kW)",
    "电池总容量(kWh)",
    "瓦单价(元/瓦)",
    "总价(元)",
    "流程发起人提交审核时间",
    "备注",
    "是否下单",
    "省总审批人",
    "省总审批状态",
    "采购审批人",
    "采购审批状态",
    "审批完成时间",
]

# 自动生成列索引常量
COL_FLOW_ID = HEADERS.index("流程编号")  # 0
COL_PROJECT_NAME = HEADERS.index("项目名称")  # 1
COL_AGENT_CODE = HEADERS.index("代理商编号")  # 2
COL_AGENT_NAME = HEADERS.index("代理商名称")  # 3
COL_PROVINCE = HEADERS.index("省公司")  # 4
COL_SALESPERSON = HEADERS.index("业务员")  # 5
COL_MODULE_KW = HEADERS.index("组件总功率(kW)")  # 6
COL_INVERTER_KW = HEADERS.index("逆变器总功率(kW)")  # 7
COL_BATTERY_KWH = HEADERS.index("电池总容量(kWh)")  # 8
COL_UNIT_PRICE = HEADERS.index("瓦单价(元/瓦)")  # 9
COL_TOTAL_PRICE = HEADERS.index("总价(元)")  # 10
COL_SUBMIT_TIME = HEADERS.index("流程发起人提交审核时间")  # 11
COL_REMARK = HEADERS.index("备注")  # 12
COL_ORDERED = HEADERS.index("是否下单")  # 13
COL_PROVINCE_PROCESSOR = HEADERS.index("省总审批人")  # 14
COL_PROVINCE_STATUS = HEADERS.index("省总审批状态")  # 15
COL_PURCHASE_PROCESSOR = HEADERS.index("采购审批人")  # 16
COL_PURCHASE_STATUS = HEADERS.index("采购审批状态")  # 17
COL_FINAL_APPROVAL_TIME = HEADERS.index("审批完成时间")  # 18

# ==================== Playwright 超时配置 ====================

NAV_TIMEOUT = 30_000       # 页面导航超时（ms）
LOAD_TIMEOUT = 30_000      # networkidle 等待超时（ms）
WAIT_SHORT = 1000          # 短等待，用于 DOM 渲染后稳定（ms）
WAIT_MEDIUM = 2000         # 中等等待，用于分页/查询后数据加载（ms）

# ==================== 重试配置 ====================

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 秒，指数退避基数

# ==================== DMS 配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"
LOGIN_CHECK_DOMAIN = "iauth.trinapower.com"
