# 审批角色切换重构设计文档

## 背景

Tab 2「审批与时效流转」目前硬编码为采购审批人数据。后续需要快速扩展支持省总审批、财务审批等多角色，且角色与审批人/状态字段的映射关系需可配置化。

## 设计决定

- 定义可扩展的 `APPROVAL_ROLES` 配置数组，新增角色只需加一行
- 角色切换下拉框 + 审批人下拉框联动
- 所有统计函数改为接收 `roleId` 参数，按角色读取对应的审批人和状态字段

## 角色配置数据结构

```javascript
var APPROVAL_ROLES = [
  { id: 'procurement', label: '采购审批', approverField: 'procurementApprover', statusField: 'procurementStatus' },
  { id: 'province', label: '省总审批', approverField: 'provinceApprover', statusField: 'provinceStatus' },
];
```

- `id`：用于函数查找的唯一标识
- `label`：下拉显示文本
- `approverField`：审批人字段名（对应 `ROWS_DETAIL` 中的 key）
- `statusField`：审批状态字段名

## HTML 改动

Tab 2 的 filter-bar 中增加角色选择器，审批人下拉保持不变：

```html
<div class="filter-bar">
  <label for="approval-role-select">👤 审批角色：</label>
  <select id="approval-role-select" class="form-control" style="min-width:100px;"></select>
  <label for="approver-select">审批人：</label>
  <select id="approver-select" class="form-control" style="min-width:150px;">
    <option value="全部">全部审批人</option>
  </select>
  <span class="filter-result" id="approver-filter-result"></span>
</div>
```

## JS 函数改动

### `extractApproverList(rows)` → `extractApproverList(rows, roleId)`

根据角色 ID 从配置中查找对应的审批人字段，提取唯一值列表。

### `computeApproverStats(rows, roleId, approverName)`

根据角色 ID 查找审批人字段和状态字段，按角色统计。

### `populateApproverList()`

读取当前选中的角色 ID，动态填充审批人下拉列表。

### `initApprovalCharts()`

读取当前角色 ID，传入 `extractApproverList` 和 `computeApproverStats`。

### 新增 `initRoleSelect()`

初始化时根据 `APPROVAL_ROLES` 数组填充角色下拉框，绑定 change 事件。

## 角色切换联动

```
角色切换 ↓
  → 清空审批人选中值（回退到"全部"）
  → populateApproverList() 重新填充对应的审批人
  → initApprovalCharts() 按新角色重新计算
  → KPI + 图表刷新
```

## 不变的部分

- `computeApprovalDays()` — 按提交+完成日期计算，与角色无关
- `computeApprovalByDimension()` — 按省公司维度统计耗时，与角色无关
- `renderApproverKPI()` — 仅接收 stats 显示数字
- 所有 Tab 1 / Tab 3 代码不变
- 所有 LAYER 1 过滤层代码不变

## 扩展新角色流程

1. 后端 Excel 增加对应列（如 `财务审批人`、`财务审批状态`）
2. `column_definitions.py` 增加列索引
3. `generate_html_report.py` 的 `compute_rows_detail` 增加映射
4. 前端 `APPROVAL_ROLES` 加一行
5. 完成，无需改其他逻辑
