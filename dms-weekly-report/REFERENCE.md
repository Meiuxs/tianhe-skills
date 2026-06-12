# DMS 非标询价周报自动化脚本

## 📋 项目概述

DMS 非标询价周报自动化脚本用于从 DMS 系统自动提取本周/指定时间范围内的已办询价数据，生成结构化的 Excel 报表（4 个 Sheet）和 HTML 看板。支持并行提取、下单状态检查和仅统计重跑模式。

---

## 🏗️ 架构设计

```
scripts/
├── run_weekly_report.py       # 编排层 — 主入口（170 行）
├── column_definitions.py      # 列定义 + 常量集中管理
├── excel_styles.py            # Excel 样式主题配置
├── dms_credentials.py         # 凭据管理（环境变量/文件）
├── generate_html_report.py    # HTML 报表生成
├── resolve_date_range.py      # 中文时段标签 → 起止日期
├── _compat.py                 # Windows 终端中文编码修复
├── core/
│   ├── dms_browser.py         # 浏览器自动化（登录/筛选/提取）
│   ├── bom_parser.py          # BOM 物料解析（功率/容量计算）
│   ├── approval_parser.py     # 审批链信息解析
│   ├── orders_checker.py      # 下单检查
│   └── excel_generator.py     # Excel 报表生成（4 Sheet）
└── tests/
    ├── __init__.py
    ├── fixtures.py             # 共享测试数据和 Mock 工具
    ├── test_bom_parser.py      # BOM 解析测试（31 个）
    ├── test_approval_parser.py # 审批链解析测试（5 个）
    ├── test_orders_checker.py  # 下单检查测试（3 个）
    ├── test_run_weekly_report.py   # 集成/纯函数测试（49 个）
    ├── test_column_definitions.py  # 列定义测试（6 个）
    ├── test_excel_styles.py        # 样式测试（15 个）
    └── test_resolve_date_range.py  # 日期解析测试（15 个）
```

### 架构设计原则

| 原则 | 说明 |
|------|------|
| **单一职责** | 每个模块只负责一个功能维度，`run_weekly_report.py` 仅编排 |
| **集中配置** | 列定义、超时参数等集中到 `column_definitions.py` |
| **依赖反转** | 业务模块从共享模块导入常量，而非硬编码 |
| **样式隔离** | 所有 Excel 样式集中于 `excel_styles.py` |
| **可测试性** | 纯函数与 Playwright 操作分离，支持 Mock 测试 |

---

## 🚀 快速开始

### 环境要求

```bash
# Python 3.10+
pip install playwright openpyxl
playwright install chromium
```

### 完整运行

```bash
# 本周数据（4 并发）
python run_weekly_report.py

# 指定周数
python run_weekly_report.py --weeks 1

# 自定义日期范围 + 8 并发
python run_weekly_report.py --start-date 2026-06-01 --end-date 2026-06-30 --workers 8

# 无头模式（不显示浏览器）
python run_weekly_report.py --headless --verbose
```

### 仅统计模式

从已生成的 Excel 重新统计，不启动浏览器：

```bash
# 统计本周
python run_weekly_report.py --stats-only

# 统计本月
python run_weekly_report.py --stats-only --this-month

# 统计指定日期范围
python run_weekly_report.py --stats-only --start-date 2026-06-01 --end-date 2026-06-30

# 指定输入文件
python run_weekly_report.py --stats-only --input-xlsx "询价汇总_20260601_090000.xlsx" --start-date 2026-06-01 --end-date 2026-06-30
```

### 日期解析

```bash
# 解析日期段标签
python resolve_date_range.py "本周"
python resolve_date_range.py "上月" --json
python resolve_date_range.py "上个月12号到现在" --json
python resolve_date_range.py "2026-06-01 ~ 2026-06-07"
```

> 支持的完整格式列表详见 `references/date_parser.md`（含：相对月+日、中文数字、至今后缀等）。

---

## 📊 Excel 输出结构

生成的 `.xlsx` 文件包含 4 个 Sheet：

| Sheet | 内容 | 用途 |
|-------|------|------|
| **询价汇总** | 原始数据表（19 列） | 原始数据导出 |
| **询价统计** | KPI 仪表盘 | 询价概览、功率容量统计 |
| **日期查询** | 下拉交互式报表 | 分时段（本周/本月/上月等）数据对比 |
| **数据看板** | 管理报表 | 审批人统计、省公司排名、审批天数 |

### 列定义（19 列）

| 索引 | 列名 | 说明 | 来源 |
|------|------|------|------|
| 0 | 流程编号 | 系统流程 ID | DMS 表单 |
| 1 | 项目名称 | 项目名称 | DMS 表单 |
| 2 | 代理商编号 | 代理商编码 | DMS 表单 |
| 3 | 代理商名称 | 代理商全称 | DMS 表单 |
| 4 | 省公司 | 所属省份 | DMS 表单 |
| 5 | 业务员 | 业务员姓名 | DMS 表单 |
| 6 | 组件总功率(kW) | 组件功率×数量 | BOM 解析 |
| 7 | 逆变器总功率(kW) | 逆变器功率×数量 | BOM 解析 |
| 8 | 电池总容量(kWh) | 电池容量×数量 | BOM 解析 |
| 9 | 瓦单价(元/瓦) | 单价 | DMS 表单 |
| 10 | 总价(元) | 总价 | DMS 表单 |
| 11 | 提交审核时间 | 流程发起时间 | 审批链 |
| 12 | 备注 | BOM 特性备注 | BOM 分析 |
| 13 | 是否下单 | 是/否/检查失败 | 订单检查 |
| 14 | 省总审批人 | 省总名称 | 审批链 |
| 15 | 省总审批状态 | 已批准/驳回等 | 审批链 |
| 16 | 采购审批人 | 采购人员 | 审批链 |
| 17 | 采购审批状态 | 已批准/驳回等 | 审批链 |
| 18 | 审批完成时间 | 最终审批时间 | 审批链 |

---

## 🧪 测试

```bash
# 运行所有测试
cd scripts/
python -m pytest tests/ -v

# 运行特定模块测试
python -m pytest tests/test_bom_parser.py -v

# 带覆盖率
python -m pytest tests/ --cov=. --cov-report=html
```

测试统计（当前 119 个测试，全部通过）：

| 测试文件 | 数量 | 覆盖内容 |
|----------|------|----------|
| `test_run_weekly_report.py` | 49 | 工具函数、HTML 生成、重试逻辑 |
| `test_bom_parser.py` | 31 | 功率/容量提取、聚合计算、备注生成 |
| `test_resolve_date_range.py` | 15 | 中文/英文/日期范围/边界情况 |
| `test_excel_styles.py` | 15 | 颜色、字体、填充、样式应用函数 |
| `test_column_definitions.py` | 6 | 列索引一致性、无重复越界 |
| `test_approval_parser.py` | 5 | 审批链提取、默认值、时间排序 |
| `test_orders_checker.py` | 3 | 下单搜索、结果判断 |

---

## 🔧 核心模块详解

### 📁 `core/dms_browser.py` — 浏览器自动化

Playwright 驱动的 DMS 浏览器操作：

```python
# 关键函数
is_on_login_page(url)              # 判断是否为登录页
ensure_logged_in(page, target_url)  # 自动登录
do_login(page)                      # 表单填写 + 提交
filter_and_get_flow_ids(...)        # 按日期筛选流程（支持多页翻页）
extract_detail_by_url(...)          # 打开详情页提取单条数据
extract_all_parallel(...)           # 并行提取所有流程
_extract_bom(page)                  # 提取 BOM 物料清单
_extract_from_html(html, label)     # HTML 字段提取
_split_agent(raw)                   # 拆分代理商编号和名称
```

### 📁 `core/bom_parser.py` — BOM 解析

从物料名称中提取功率和容量参数：

```python
extract_power(name)         # 提取功率（kW）
extract_capacity(name)      # 提取容量（kWh）
calc_module_power(items)    # 计算组件总功率
calc_inverter_power(items)  # 计算逆变器总功率
calc_battery_capacity(items) # 计算电池总容量
build_remark(items)         # 构建备注（光储逆变器/并网柜等）
```

支持的物料命名格式：
- `销售组件_550kW_单晶` → 550 kW ✅
- `销售组件_500W_单晶` → 0.5 kW ✅
- `逆变器_33.3kW_三相` → 33.3 kW ✅
- `电池_9.8kWh_储能` → 9.8 kWh ✅
- `电池_9800_Wh_` → 9.8 kWh ✅

### 📁 `core/approval_parser.py` — 审批链解析

从 DMS 详情页提取审批链信息：

```python
extract_approval_info(page) -> dict
    # "submit_time"           → "--"
    # "province_processor"     → "李四"
    # "province_status"        → "已批准"
    # "purchase_processor"     → "王五"
    # "purchase_status"        → "已批准通过"
    # "final_approval_time"    → "2026-06-05 09:00"
```

### 📁 `core/orders_checker.py` — 下单检查

在订单历史页面搜索流程编号：

```python
search_order_for_flow(context, flow_id, sem)  # 返回 "是"/"否"
check_single_order(context, flow_id, sem)      # 带重试，失败返回 "检查失败"
check_orders_parallel(context, records, workers) # 并行检查所有记录
```

### 📁 `core/excel_generator.py` — Excel 生成

```python
generate_excel(records, output_dir, query_range, timestamp_str) -> (filepath, rows)
```

内部调用：
- `_update_summary_sheet()` — 询价统计 Sheet
- `_create_date_query_sheet_v2()` — 日期查询 Sheet
- `_create_report_dashboard()` — 数据看板 Sheet
- `_build_rows_data()` — 构建 19 列行数据
- `_fill_date_helper_column()` — 日期辅助列

---

## ⚙️ 配置说明

### `column_definitions.py`

```python
HEADERS             # 19 列表头定义
COL_*               # 列索引常量（COL_FLOW_ID = 0, COL_PROJECT_NAME = 1...）
NAV_TIMEOUT         # 导航超时（ms）
LOAD_TIMEOUT        # 加载超时（ms）
WAIT_SHORT/MEDIUM   # 等待时间（ms）
MAX_RETRIES         # 重试次数
DMS_URL             # DMS 系统地址
LOGIN_CHECK_DOMAIN  # 登录页域名
```

### `excel_styles.py`

```
Colors.DARK_BLUE       # 1F4E79 — 深蓝主色
Colors.ACCENT_BLUE     # 4472C4 — 强调蓝
Colors.DARK_GRAY       # 2D3436 — 正文文字
Colors.MID_GRAY        # 636E72 — 辅助文字
Colors.RED_ACCENT      # D73026 — 警告红
Colors.GREEN_ACCENT    # 27A745 — 成功绿
```

---

## 🔐 凭据管理

凭据由 `dms_credentials.py` 管理，查找顺序：

1. **进程环境变量** `DMS_USER` / `DMS_PASSWORD`（优先）
2. **Git Bash Profile** `/etc/profile.d/dms.sh`
3. **PowerShell Profile** 中的环境变量

---

## 🛠️ 故障排除

| 问题 | 可能原因 | 解决方法 |
|------|---------|---------|
| 浏览器登录失败 | 凭据过期 | 更新 `DMS_USER`/`DMS_PASSWORD` 环境变量 |
| 提取数据为空 | 日期范围无数据 | 检查 `--start-date` / `--end-date` 是否合理 |
| BOM 解析返回 None | 物料命名格式不匹配 | 查看 `bom_parser.py` 支持的正则模式 |
| Escel 被占用 | 文件已打开 | 脚本自动使用 `_v2.xlsx` 备用文件名 |
| 翻页只处理第 1 页 | 翻页点击超时 | 增加 `WAIT_MEDIUM` 时间 |
| 中文显示乱码（终端） | Windows 编码 | `_compat.py` 自动修复大部分情况 |

---

## 📈 近期改进记录

| 版本 | 改进内容 |
|------|---------|
| v3 | 架构拆分（核心模块 → `core/`），TDD 重构，119 个测试 |
| v2.1 | 日期验证改进，异常处理加强，常量集中管理 |
| v2.0 | Excel 样式升级为现代企业风格 |
| v1.5 | 新增审批链提取，HTML 报表 |
| v1.0 | 初始版本，单文件 1554 行 |
