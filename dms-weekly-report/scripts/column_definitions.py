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
    "是否有效",
    "项目管理部核价审批人",
    "项目管理部核价审批状态",
    "项目管理部核价审批时间",
    "省总审批人",
    "省总审批状态",
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
# COL_ORDERED = HEADERS.index("是否下单")  # 已废弃，后续可能恢复使用
# 以下列在 HEADERS 中已移除，但代码中仍有引用，保留常量用于兼容
# TODO: 后续可能恢复使用采购审批列
COL_PURCHASE_PROCESSOR = -1  # 已废弃
COL_PURCHASE_STATUS = -1     # 已废弃

COL_IS_VALID = HEADERS.index("是否有效")  # 13
COL_NEGOTIATION_PROCESSOR = HEADERS.index("项目管理部核价审批人")  # 14
COL_NEGOTIATION_STATUS = HEADERS.index("项目管理部核价审批状态")  # 15
COL_NEGOTIATION_TIME = HEADERS.index("项目管理部核价审批时间")  # 16
COL_PROVINCE_PROCESSOR = HEADERS.index("省总审批人")  # 17
COL_PROVINCE_STATUS = HEADERS.index("省总审批状态")  # 18
COL_FINAL_APPROVAL_TIME = HEADERS.index("审批完成时间")  # 19

# ==================== Playwright 超时配置 ====================

NAV_TIMEOUT = 30_000       # 页面导航超时（ms）
LOAD_TIMEOUT = 15_000      # networkidle 等待超时（ms）
WAIT_SHORT = 1000          # 短等待，用于 DOM 渲染后稳定（ms）
WAIT_MEDIUM = 2000         # 中等等待，用于分页/查询后数据加载（ms）

# ==================== 重试配置 ====================

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 秒，指数退避基数

# ==================== DMS 配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"
LOGIN_CHECK_DOMAIN = "iauth.trinapower.com"

# 流程筛选常量
TARGET_FLOW_TYPE = "户用小型工商业询价流程"
FILTER_PAGE_SIZE = 10        # DOM 翻页每页条数（与 DMS 页面一致）
API_FILTER_PAGE_SIZE = 500   # API 筛选每页条数，增大以减少请求次数

# API 端点
DMS_API_BASE = "https://apigw.trinablue.com"
DMS_FLOW_LIST_API = f"{DMS_API_BASE}/dms-admin/newFlow/newFlowList"
DMS_FLOW_DETAILS_API = f"{DMS_API_BASE}/dms-admin/newFlow/flowDetails"

# ==================== 下单检查配置 ====================

ORDER_CHECK_EXTEND_DAYS = 14  # 下单检查日期范围扩展天数（覆盖审批周期）

# ==================== 功率累加函数 ====================


def accumulate_power(rows, cols=None):
    """累加数据行中指定列的功率/容量值，跳过占位符。

    Args:
        rows: 数据行列表，每行为 tuple/list。
        cols: (组件列索引, 逆变器列索引, 电池列索引)，默认 (6, 7, 8)。

    Returns:
        (total_module, total_inverter, total_battery) 三元组。
    """
    if cols is None:
        cols = (COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH)
    col_mk, col_ik, col_bk = cols
    totals = [0.0, 0.0, 0.0]  # [mk, ik, bk]
    for row in rows:
        for idx, col in enumerate((col_mk, col_ik, col_bk)):
            val = row[col]
            if isinstance(val, (int, float)):
                totals[idx] += float(val)
            elif isinstance(val, str) and val not in ("无", "--", ""):
                try:
                    totals[idx] += float(val)
                except ValueError:
                    pass
    return totals[0], totals[1], totals[2]


# ==================== 状态常量 ====================
STATUS_ORDERED = "已下单"
STATUS_NOT_ORDERED = "未下单"
STATUS_CHECK_FAILED = "检查失败"
STATUS_YES = "是"
STATUS_NO = "否"
STATUS_NONE = "无"
STATUS_DASH = "--"
SHEET_DATA = "询价汇总"

# ==================== 魔法数字常量 ====================
FLOW_ID_MIN_LEN = 15  # 流程编号最小长度（15 位数字）
FLOW_ID_PATTERN = r"^\d{15,}$"  # 流程编号正则（15 位及以上数字）
EXCEL_SERIAL_OFFSET = 693594  # Excel 日期序列号偏移量（1899-12-30 以来的天数）
