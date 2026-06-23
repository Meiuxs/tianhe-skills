# DMS 非标询价周报生成器 — 重新设计方案

> **日期：** 2026-06-23
> **状态：** ✅ 已完成（2026-06-23）
> **范围：** `dms-weekly-report` skill — Excel 列结构调整、下单逻辑去除、HTML 报表开关

---

## 一、背景与目标

### 1.1 背景

当前周报生成器存在以下问题：

1. **「是否下单」列无实际意义** — 当前所有询价流程下单检查均为 0，下单率始终为 0%，该列占用列宽且无参考价值
2. **采购审批人不是核心关注点** — 业务方更关注「项目管理部核价」节点的审批情况，当前采购审批人列位置被占用
3. **无法区分有效/无效询价** — 没有明确标识哪些询价流程真正完成了项目管理部核价审批
4. **HTML 报表无法灵活切换数据范围** — 作废流程始终被排除，无法查看全量数据

### 1.2 目标

1. 将「是否下单」列替换为「是否有效」列，判断标准为项目管理部核价节点是否审核通过
2. 将「采购审批人/状态」列替换为「项目管理部核价审批人/状态/时间」列
3. 去除下单检查逻辑（代码注释保留，后续可能恢复）
4. HTML 报表右上角新增「包含作废流程」开关，切换后所有统计联动更新

---

## 二、Excel「询价汇总」Sheet 改动

### 2.1 列定义调整（19 列 → 19 列）

**原列定义（19 列）：**

```
 0. 流程编号
 1. 项目名称
 2. 代理商编号
 3. 代理商名称
 4. 省公司
 5. 业务员
 6. 组件总功率(kW)
 7. 逆变器总功率(kW)
 8. 电池总容量(kWh)
 9. 瓦单价(元/瓦)
10. 总价(元)
11. 流程发起人提交审核时间
12. 备注
13. 是否下单              ← 去掉
14. 省总审批人
15. 省总审批状态
16. 采购审批人
17. 采购审批状态
18. 审批完成时间
```

**新列定义（21 列）：**

```
 0. 流程编号
 1. 项目名称
 2. 代理商编号
 3. 代理商名称
 4. 省公司
 5. 业务员
 6. 组件总功率(kW)
 7. 逆变器总功率(kW)
 8. 电池总容量(kWh)
 9. 瓦单价(元/瓦)
10. 总价(元)
11. 流程发起人提交审核时间
12. 备注
13. 是否有效                    ← 新增：项目管理部核价审批节点审核通过为"是"，否则"否"
14. 省总审批人                  ← 保持原内容，移到核价审批前面
15. 省总审批状态                ← 保持原内容
16. 项目管理部核价审批人        ← 原"采购审批人"列位置
17. 项目管理部核价审批状态      ← 原"采购审批状态"列位置
18. 项目管理部核价审批时间      ← 新增
19. 审批完成时间                ← 保持原内容
20. 流程状态                    ← 新增：流程的当前状态（如审批通过、作废等）
```

> **说明：** 去掉「是否下单」(-1)，新增「是否有效」(+1)、「项目管理部核价审批时间」(+1)、「流程状态」(+1)，净增加 2 列，共 21 列。

> **列顺序调整说明：** 省总审批（14-15）移到项目管理部核价审批（16-18）前面，因为省总审批在流程上先于核价审批。最后新增「流程状态」列（20），记录流程当前状态。

### 2.2 流程筛选逻辑变化

| 原逻辑 | 新逻辑 |
|--------|--------|
| API 筛选时跳过 `statusName` 含「作废」的记录 | **默认包含全部流程**（不过滤作废） |
| HTML 解析时跳过 `status_text` 含「作废」的记录 | **默认包含全部流程**（不过滤作废） |
| `skipped_invalid` 仅用于日志 | `skipped_invalid` 仍记录作废数（用于终端摘要），但不影响 `flow_ids` |

**新增参数：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--include-invalid` | 包含作废流程（默认行为） | True |
| `--exclude-invalid` | 排除作废流程（旧逻辑） | — |

> **注意：** 为保持向后兼容，默认行为改为包含全部流程。用户如需排除作废流程，传 `--exclude-invalid`。

### 2.3 审批链解析新增「项目管理部核价」节点

#### 2.3.1 节点匹配规则

在 `approval_parser.py` 和 `api_parser.py` 中新增匹配：

```python
# 审批链节点匹配规则（按审批流程顺序排列）
# 注意：「项目管理部核价」是完整角色名，精确匹配
if "流程发起人" in node and "提交审核" in status_val:
    result["submit_time"] = time_text
elif "项目管理部核价" in node:                          # 新增：核价节点
    result["negotiation_processor"] = processor           # 新增
    result["negotiation_status"] = status_val             # 新增
    result["negotiation_time"] = time_text                # 新增
elif "省总" in node or "省公司" in node:
    result["province_processor"] = processor
    result["province_status"] = status_val
elif "采购" in node or "商务" in node:
    result["purchase_processor"] = processor
    result["purchase_status"] = status_val
```

> **匹配说明：** 使用精确匹配 `"项目管理部核价" in node`，不使用模糊匹配（如 `"核价" in node`），避免误匹配其他含「核价」的节点。

#### 2.3.2 FlowRecord 新增字段

```python
@dataclass
class FlowRecord:
    # ... 现有字段 ...
    ordered: str = "否"                    # 废弃，保留但不再使用
    negotiation_processor: str = "--"      # 项目管理部核价审批人（新增）
    negotiation_status: str = "--"        # 项目管理部核价审批状态（新增）
    negotiation_time: str = "--"          # 项目管理部核价审批时间（新增）
    is_valid: str = "否"                  # 是否有效（新增）
```

#### 2.3.3 「是否有效」判断逻辑

```python
def compute_is_valid(negotiation_status: str) -> str:
    """判断询价是否有效：项目管理部核价节点审核通过即为有效"""
    if negotiation_status and "通过" in negotiation_status:
        return "是"
    return "否"
```

---

## 三、下单检查逻辑去除

### 3.1 代码处理策略

| 文件 | 处理方式 |
|------|----------|
| `core/orders_checker.py` | **保留文件和内容**，所有函数添加 `# TODO: 后续可能恢复使用` 注释标记 |
| `run_weekly_report.py` | 移除 `_extract_and_check` 中并发下单查询、`ordered` 字段标注 |
| `core/excel_generator.py` | `_build_rows_data` 去掉 `r.ordered` 字段 |
| `column_definitions.py` | 保留 `STATUS_ORDERED` 等常量（注释标记废弃），去掉 `COL_ORDERED` |
| `core/dms_browser.py` | `FlowRecord.ordered` 字段保留但注释标记为废弃 |
| `generate_html_report.py` | `compute_rows_detail` 去掉 `ordered` 字段映射 |
| 测试文件 | 同步更新相关测试用例 |

### 3.2 需要修改的代码位置

#### `run_weekly_report.py`

| 行号 | 改动 |
|------|------|
| 214-232 | 移除 `_extract_and_check` 函数中 `fetch_ordered_flow_ids` 并发调用 |
| 339-344 | 移除 `ordered` 字段标注逻辑 |
| 107-144 | `print_summary` 中去掉已下单/未下单计数，改为有效/无效计数 |
| 46-51 | 去掉 `COL_ORDERED` 导入 |

#### `core/excel_generator.py`

| 行号 | 改动 |
|------|------|
| 27 | 去掉 `COL_ORDERED` 导入 |
| 150-163 | `_build_rows_data` 中去掉 `r.ordered`，新增项目管理部核价审批字段 |
| 236-257 | `_update_summary_sheet` 中去掉 ordered/not_ordered 统计 |

#### `generate_html_report.py`

| 行号 | 改动 |
|------|------|
| 36 | 去掉 `COL_ORDERED` 导入 |
| 141-202 | `compute_rows_detail` 中去掉 `ordered` 字段映射 |
| 296 | `exportToExcel` 中去掉 `已下单` 列 |

---

## 四、HTML 报表改动

### 4.1 改动总览

HTML 模板共涉及 **12 处** 需要修改的位置，按模块逐一列出：

| # | 位置 | 行号 | 改动类型 | 说明 |
|---|------|------|----------|------|
| 1 | CSS 样式 | 494-500 | 删除 | 删除 `.kpi-card.warning` 样式（不再需要） |
| 2 | Header 开关 | 1111 附近 | 新增 | 右上角 global-filter 区域新增「包含作废流程」开关 |
| 3 | KPI 卡片 | 1173-1182 | 替换 | 「已下单」「未下单」→「有效询价」「无效询价」 |
| 4 | 饼图标题 | 1208 | 修改 | 「订单状态分布」→「询价有效性分布」 |
| 5 | 饼图 caption | 1212 | 修改 | 「已下单 vs 未下单 项目占比」→「有效 vs 无效 询价占比」 |
| 6 | 明细表格表头 | 1313-1315 | 修改 | 「已下单」→「是否有效」、「采购审批人」→「项目管理部核价审批人」 |
| 7 | 审批角色下拉 | 1348 | 修改 | 「采购审批」→「项目管理部核价审批」 |
| 8 | JS 数据字段 | 1457 附近 | 新增 | ROWS_DETAIL 每条记录新增 `isInvalid`、`isValid`、`negotiationApprover` 字段 |
| 9 | computeAggregates | 1880-1900 | 重写 | 去掉 ordered/notOrdered，新增 validCount/invalidCount |
| 10 | APPROVAL_ROLES | 1949-1952 | 修改 | 审批角色「采购审批」→「项目管理部核价审批」，字段名同步更新 |
| 11 | computePeriodSummaries | 2156-2199 | 重写 | 时段汇总中去掉 ordered，新增 valid |
| 12 | 明细表格渲染 | 2690-2692 | 修改 | 渲染 `item.isValid`、`item.negotiationApprover` |
| 13 | Excel 导出 | 2974-2976 | 修改 | 导出列去掉「已下单」「采购审批人」，新增「是否有效」「项目管理部核价审批人」 |

### 4.2 右上角新增「包含作废流程」开关

#### 4.2.1 UI 位置

在 header 右上角 `global-filter` 区域、日期范围选择器后面新增 toggle 开关：

```html
<label class="invalid-toggle">
  <input type="checkbox" id="include-invalid-toggle" checked>
  <span>包含作废流程</span>
</label>
```

#### 4.2.2 数据注入策略

- **作废流程数据始终注入** `ROWS_DETAIL`（后端生成 HTML 时包含全部流程）
- 每条记录新增以下字段：
  - `isInvalid` (bool) — 是否为作废流程
  - `isValid` (string) — "是"或"否"（项目管理部核价审批通过即为"是"）
  - `negotiationApprover` (string) — 项目管理部核价审批人
  - `negotiationStatus` (string) — 项目管理部核价审批状态
- 开关切换时前端 JS 实时过滤，无需重新生成 HTML

#### 4.2.3 前端过滤逻辑

```javascript
// 全局状态
var includeInvalid = true;  // 默认包含作废流程

// 过滤函数（替换原有 getFilteredRows）
function getFilteredRows() {
  var start = document.getElementById('date-start').value;
  var end = document.getElementById('date-end').value;
  
  return ROWS_DETAIL.filter(function(row) {
    // 作废流程过滤
    if (!includeInvalid && row.isInvalid) return false;
    // 日期范围过滤
    if (start && end) {
      return row.submitDate >= start && row.submitDate <= end;
    }
    return true;
  });
}

// 开关切换事件
document.getElementById('include-invalid-toggle').addEventListener('change', function() {
  includeInvalid = this.checked;
  onDateRangeChange();  // 触发全局刷新（已有函数，复用）
});
```

### 4.3 KPI 卡片调整

去掉「已下单」「未下单」卡片，新增「有效询价」「无效询价」卡片：

**HTML 改动（行 1173-1182）：**

```html
<!-- 原 -->
<div class="kpi-card green">
  <div class="label">已下单</div>
  <div class="value" id="kpi-ordered">--</div>
  <div class="unit">个</div>
</div>
<div class="kpi-card warning">
  <div class="label">未下单</div>
  <div class="value" id="kpi-not-ordered">--</div>
  <div class="unit">个</div>
</div>

<!-- 新 -->
<div class="kpi-card green">
  <div class="label">有效询价</div>
  <div class="value" id="kpi-valid">--</div>
  <div class="unit">个</div>
</div>
<div class="kpi-card orange">
  <div class="label">无效询价</div>
  <div class="value" id="kpi-invalid">--</div>
  <div class="unit">个</div>
</div>
```

> **注意：** `.kpi-card.warning` 样式类可保留（其他地方可能复用），但 KPI 卡片改用 `.orange` 样式。

### 4.4 饼图调整

#### 4.4.1 标题和 caption

| 位置 | 原内容 | 新内容 |
|------|--------|--------|
| 图表标题（行 1208） | 📊 订单状态分布 | 📊 询价有效性分布 |
| caption（行 1212） | 已下单 vs 未下单 项目占比 | 有效 vs 无效 询价占比 |

#### 4.4.2 JS 数据（行 2278-2305）

```javascript
// 原：订单状态饼图
let ordered = stats.orderedCount;
let notOrdered = stats.notOrderedCount;
// ...
labels: ['已下单', '未下单']
data: [ordered, notOrdered]

// 新：有效性分布饼图
let valid = stats.validCount;
let invalid = stats.invalidCount;
// ...
labels: ['有效询价', '无效询价']
data: [valid, invalid]
backgroundColor: [CHART_COLORS.green, CHART_COLORS.orange]
```

空数据提示同步修改：

```javascript
// 原
showNoData('chart-order-donut', '暂无订单数据', '📊');

// 新
showNoData('chart-order-donut', '暂无有效性数据', '📊');
```

### 4.5 审批角色下拉调整

**HTML 改动（行 1348）：**

```html
<!-- 原 -->
<option value="procurement">采购审批</option>

<!-- 新 -->
<option value="procurement">项目管理部核价审批</option>
```

**JS 配置（行 1949-1952）：**

```javascript
// 原
{ id: 'procurement', label: '采购审批', approverField: 'procurementApprover', statusField: 'procurementStatus' }

// 新
{ id: 'procurement', label: '项目管理部核价审批', approverField: 'negotiationApprover', statusField: 'negotiationStatus' }
```

### 4.6 computeAggregates 函数重写

**JS 改动（行 1880-1900）：**

```javascript
// 原
function computeAggregates(rows) {
  let total = 0, ordered = 0;
  // ...
  rows.forEach(function(row) {
    total++;
    if (row.ordered === '是') ordered++;
    // ...
  });
  return {
    totalProjects: total,
    orderedCount: ordered,
    notOrderedCount: total - ordered,
    // ...
  };
}

// 新
function computeAggregates(rows) {
  let total = 0, valid = 0;
  let modulePower = 0, inverterPower = 0, batteryCapacity = 0;
  let spSet = {};

  rows.forEach(function(row) {
    total++;
    if (row.isValid === '是') valid++;
    modulePower += row.modulePower || 0;
    inverterPower += row.inverterPower || 0;
    batteryCapacity += row.batteryCapacity || 0;
    if (row.salesperson && row.salesperson !== '--' && row.salesperson !== '无') {
      spSet[row.salesperson] = true;
    }
  });

  return {
    totalProjects: total,
    validCount: valid,
    invalidCount: total - valid,
    salespersons: Object.keys(spSet).length,
    modulePower: modulePower,
    inverterPower: inverterPower,
    batteryCapacity: batteryCapacity,
    ratio: inverterPower > 0 ? Math.round(modulePower / inverterPower * 100) / 100 : 0,
  };
}
```

### 4.7 updateOverviewKPIs 函数调整

**JS 改动（行 2218-2219）：**

```javascript
// 原
setText('kpi-ordered', stats.orderedCount);
setText('kpi-not-ordered', stats.notOrderedCount);

// 新
setText('kpi-valid', stats.validCount);
setText('kpi-invalid', stats.invalidCount);
```

### 4.8 computePeriodSummaries 函数重写

**JS 改动（行 2156-2199）：**

```javascript
// 原
buckets[sp.label] = { total: 0, ordered: 0, modulePower: 0, inverterPower: 0, batteryCapacity: 0, spSet: {} };
// ...
if (row.ordered === '是') b.ordered++;
// ...
orderedCount: b.ordered,
notOrderedCount: b.total - b.ordered,

// 新
buckets[sp.label] = { total: 0, valid: 0, modulePower: 0, inverterPower: 0, batteryCapacity: 0, spSet: {} };
// ...
if (row.isValid === '是') b.valid++;
// ...
validCount: b.valid,
invalidCount: b.total - b.valid,
```

### 4.9 明细表格调整

#### 4.9.1 表头（行 1313-1315）

```html
<!-- 原 -->
<th>已下单</th>
<th>采购审批人</th>

<!-- 新 -->
<th>是否有效</th>
<th>项目管理部核价审批人</th>
```

#### 4.9.2 渲染函数（行 2690-2692）

```javascript
// 原
tr.appendChild(createTableCell('td', item.ordered));
tr.appendChild(createTableCell('td', item.procurementApprover));

// 新
tr.appendChild(createTableCell('td', item.isValid));
tr.appendChild(createTableCell('td', item.negotiationApprover));
```

### 4.10 Excel 导出函数调整

**JS 改动（行 2974-2976）：**

```javascript
// 原
'已下单': row.ordered,
'采购审批人': row.procurementApprover,

// 新
'是否有效': row.isValid,
'项目管理部核价审批人': row.negotiationApprover,
```

### 4.11 联动更新范围

开关切换时，以下模块全部联动更新（通过 `onDateRangeChange()` 统一触发）：

| 模块 | 函数 | 更新内容 |
|------|------|----------|
| 项目与容量概览 KPI | `updateOverviewKPIs()` | 有效/无效数、功率容量 |
| 有效性分布饼图 | `initOverviewCharts()` | 有效/无效占比 |
| 省公司排名图表 + 表格 | `computeProvinceRanking()` + `renderProvinceTable()` | 按过滤后数据重新排名 |
| 审批效率分析 | `initApprovalCharts()` | 通过率、时效按过滤后数据重算 |
| 趋势分析图表 | `initDetailCharts()` → `computePeriodSummaries()` | 各时段汇总按过滤后数据重算 |
| 项目明细表格 | `renderDetailTable()` | 按过滤后数据重新渲染 |
| 审批人下拉列表 | `populateApproverList()` | 按过滤后数据重新提取审批人 |

### 4.12 CSS 样式调整

| 位置 | 改动 |
|------|------|
| 行 494-500 | `.kpi-card.warning` 样式可保留（不影响其他），KPI 卡片改用 `.orange` |
| 新增 `.invalid-toggle` 样式 | 开关 label 的样式，与 global-filter 风格一致 |

---

## 五、其他 Sheet 改动

### 5.1 「询价统计」Sheet

| 原统计项 | 新统计项 |
|----------|----------|
| 已下单项目 | 有效询价项目 |
| 未下单项目 | 无效询价项目 |
| 下单率 | 有效率 |

### 5.2 「日期查询」Sheet

- 统计逻辑保持不变（读取 Excel 数据行）
- 通过「是否有效」列区分有效/无效

### 5.3 「数据看板」Sheet

- 王剑审批统计 → 改为项目管理部核价审批统计（如适用）
- 其他统计逻辑保持不变

---

## 六、改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `column_definitions.py` | 修改 | 列定义调整、新增项目管理部核价审批列常量、标记废弃列 |
| `core/dms_browser.py` | 修改 | `FlowRecord` 新增项目管理部核价审批字段、标记 ordered 废弃 |
| `core/approval_parser.py` | 修改 | `extract_approval_info` 新增「项目管理部核价」节点匹配，提取 processor/status/time |
| `core/api_parser.py` | 修改 | `fill_approval_from_nodes` 新增「项目管理部核价」节点匹配，填充 negotiation 字段 |
| `core/excel_generator.py` | 修改 | `_build_rows_data` 调整列、统计逻辑去掉 ordered |
| `core/orders_checker.py` | 保留+注释 | 代码注释标记废弃 |
| `run_weekly_report.py` | 修改 | 移除下单检查、调整摘要输出 |
| `generate_html_report.py` | 修改 | 去掉 ordered 字段映射、新增 isInvalid/isValid/negotiationApprover 字段 |
| `references/report_template.html` | 修改 | 12 处改动：开关 UI、KPI 卡片、饼图、表格表头、审批角色下拉、computeAggregates、APPROVAL_ROLES、computePeriodSummaries、updateOverviewKPIs、明细表格渲染、Excel 导出、CSS 样式 |
| `SKILL.md` | 修改 | 更新文档说明 |

---

## 七、测试计划

### 7.1 单元测试

| 测试文件 | 测试内容 |
|----------|----------|
| `test_column_definitions.py` | 验证新列定义常量正确 |
| `test_approval_parser.py` | 验证项目管理部核价审批节点解析逻辑 |
| `test_api_parser.py` | 验证 fill_approval_from_nodes 项目管理部核价审批字段填充 |
| `test_excel_generator.py` | 验证新列顺序、统计逻辑 |

### 7.2 集成测试

| 测试场景 | 预期结果 |
|----------|----------|
| 运行完整模式生成 Excel | 列顺序正确（20 列）、项目管理部核价审批字段有值、无「是否下单」列 |
| 运行仅统计模式 | 统计 Sheet 正确反映有效/无效数、无「下单率」改为「有效率」 |
| 打开 HTML 报表 | 开关默认勾选（包含作废）、KPI 显示有效/无效数、无「已下单/未下单」卡片 |
| 切换开关（取消包含作废） | 所有图表联动更新、总数减少、审批人列表更新 |
| 切换开关（重新包含作废） | 数据恢复到包含全部流程的状态 |
| 饼图 | 显示「有效询价 vs 无效询价」分布，标题为「询价有效性分布」 |
| 明细表格 | 表头显示「是否有效」「项目管理部核价审批人」，无「已下单」「采购审批人」 |
| 导出 Excel | 导出列包含「是否有效」「项目管理部核价审批人」，无「已下单」「采购审批人」 |
| 审批角色下拉 | 选项一显示「项目管理部核价审批」（非「采购审批」） |
| 趋势分析 | 各时段统计不包含 ordered 相关计算 |

### 7.3 回归测试

| 测试场景 | 预期结果 |
|----------|----------|
| 日期范围筛选 | 更新时间后所有图表正常联动 |
| 快捷按钮（今日/本周/本月等） | 正常切换，KPI 和图表正确更新 |
| 审批人切换 | 审批效率分析图表正确联动 |
| 浏览器兼容性 | Chrome/Firefox/Edge 下样式和交互正常 |

---

## 八、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 项目管理部核价审批节点名称不匹配 | 项目管理部核价审批字段为空 | 使用精确匹配 `"项目管理部核价" in node`，如 DMS 系统节点名称有变化需同步更新 |
| 历史数据无项目管理部核价审批节点 | 全部显示"无效" | 符合预期，历史流程确实未经项目管理部核价审批 |
| HTML 数据量过大 | 加载变慢 | 作废流程通常占比 < 20%，影响可控 |

---

## 九、后续计划

- 下单检查逻辑保留在 `orders_checker.py` 中，后续如需恢复可通过参数 `--check-orders` 启用
- 项目管理部核价审批节点匹配规则可配置化（通过配置文件支持不同环境的节点名称差异）
