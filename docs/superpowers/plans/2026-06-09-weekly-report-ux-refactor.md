# 询价周报 HTML 报表 UX 重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对现有询价周报 HTML 报表进行全面 UX 重构：重新划分 Tab 结构、增加全局时间筛选器、优化图表类型和数据展示方式、修复交互断层、统一数据可视化规范。

**Architecture:** 核心改动分两个层面——(1) Python 后端 `generate_html_report.py` 新增每日趋势、审批分组对比、明细下钻等数据计算函数，并传递更多 JSON 数据到前端；(2) HTML 模板 `report_template.html` 重构 Tab 结构、CSS 排版、JS 图表逻辑，实现全局筛选器驱动所有 Tab 联动刷新。

**Tech Stack:** Python 3 (openpyxl, json), Vanilla HTML/CSS/JS (Chart.js 4.4.7)

---

## 文件结构

| 文件 | 职责 | 改动类型 |
|------|------|----------|
| `dms-weekly-report/references/report_template.html` | HTML 结构 + CSS 样式 + JS 交互逻辑 | **重度修改** |
| `dms-weekly-report/scripts/generate_html_report.py` | 数据计算 + JSON 注入 | **中度修改** |
| `dms-weekly-report/SKILL.md` | 更新 HTML 独立生成说明 | 轻量修改 |

---

## 评审意见 → 改动点映射

| # | 评审意见 | 改动类型 | 对应任务 |
|---|---------|---------|---------|
| 1 | Tab 命名重新划分 | HTML 文案 + 内容重组 | Task 1, 2 |
| 2 | 全局时间筛选器 | HTML 结构移动 + JS 联动 | Task 1, 4 |
| 3 | Tab1 周期趋势改每日折线图 | Python 新增 daily_data + JS 改图表 | Task 5, 8 |
| 4 | Tab2 删除"当前选择结果"卡片 | HTML 删除 | Task 6 |
| 5 | Tab2 筛选器与明细表格绑定 | Python 传递 rows_detail + JS 渲染 | Task 6, 9 |
| 6 | Tab3 "王剑"硬编码 → 通用审批人 | HTML 文案 + Python 审批人列表 | Task 2, 7 |
| 7 | Tab3 审批耗时图改为分组对比 | Python 新增分组数据 + JS 改图表 | Task 7, 10 |
| 8 | Tab3 排名图表 60/40 排版 | CSS 修改 | Task 3 |
| 9 | 审批饼图"未通过"灰色→红色 | JS 颜色修改 | Task 10 |
| 10 | 表格数值列右对齐 | CSS 修改 | Task 3 |
| 11 | 空数据状态占位符 | JS 改进 showNoData | Task 11 |
| 12 | 审批耗时 Tooltip 说明 | HTML 新增提示图标 | Task 12 |

---

### Task 1: 重构 HTML 结构 — Tab 导航与全局筛选器

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 修改 Header，增加全局时间段筛选器**

将 Header 部分改为包含全局筛选器的结构。定位到当前模板 525-539 行的 `<header>` 块，替换为：

```html
<header class="header">
  <div class="header-inner">
    <div class="header-brand">
      <div class="header-brand-icon">📊</div>
      <div>
        <h1>询价周报报表</h1>
        <div class="subtitle">DMS 采购询价数据统计</div>
      </div>
    </div>
    <div class="header-right">
      <div class="meta">
        <span>📅 {{REPORT_DATE_RANGE}}</span>
        <span>⏱ {{REPORT_GENERATED_AT}}</span>
      </div>
      <div class="global-filter">
        <label for="global-period-select">📅 时间段：</label>
        <select id="global-period-select" onchange="onGlobalPeriodChange()">
          <option value="全部">全部</option>
          <option value="本周">本周</option>
          <option value="本月" selected>本月</option>
          <option value="上月">上月</option>
          <option value="本季度">本季度</option>
        </select>
      </div>
    </div>
  </div>
</header>
```

- [ ] **Step 2: 重命名 Tab 按钮**

将 544-553 行的 Tab 导航替换为新的命名：

```html
<nav class="tab-nav" role="tablist">
  <button class="tab-btn active" role="tab" data-tab="overview" onclick="switchTab('overview')">
    📈 项目与容量概览 <span class="badge">KPI</span>
  </button>
  <button class="tab-btn" role="tab" data-tab="approval" onclick="switchTab('approval')">
    ⏱ 审批与时效流转 <span class="badge">效率</span>
  </button>
  <button class="tab-btn" role="tab" data-tab="detail" onclick="switchTab('detail')">
    📋 多维数据明细 <span class="badge">下钻</span>
  </button>
</nav>
```

> 注意：Tab data-tab 值从 `summary/query/dashboard` 改为 `overview/approval/detail`，后续所有 JS 中引用这些名称的地方都需同步更新。

- [ ] **Step 3: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "refactor(weekly-report): restructure tab navigation and add global time filter to header"
```

---

### Task 2: 重新组织 Tab 内容区域（HTML 结构调整）

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 重新组织 Tab 内容区域**

当前 3 个 Tab section 的 id 从 `tab-summary/tab-query/tab-dashboard` 改为 `tab-overview/tab-approval/tab-detail`。同时调整各 Tab 内的内容归属。

**Tab 1 (overview, 原 summary):** 保留询价概览 KPI、订单状态饼图、功率容量对比柱状图、功率容量统计 KPI、周期趋势（改为每日趋势，Task 5 处理），移入原 Tab 3 的省公司排名内容。

```html
<!-- Tab 1: 项目与容量概览 -->
<section class="tab-content active" id="tab-overview" role="tabpanel">
  <div class="tab-body">
    <!-- 询价概览 KPI 卡片（保留） -->
    <!-- 订单状态饼图 + 功率容量柱状图（保留） -->
    <!-- 功率容量统计 KPI（保留） -->
    <!-- 每日趋势折线图（替代原周期趋势柱状图，canvas id 改为 chart-daily-trend） -->
    <!-- 省公司询价排名（从原 Tab 3 移入，保持原结构） -->
  </div>
</section>
```

**Tab 2 (approval, 原 dashboard 审批部分):** 聚焦审批与时效。标题从"王剑采购审批统计"改为"关键节点审批统计"，增加审批人下拉选择。

```html
<!-- Tab 2: 审批与时效流转 -->
<section class="tab-content" id="tab-approval" role="tabpanel">
  <div class="tab-body">
    <!-- 审批概览 KPI -->
    <!-- 审批人选择器 -->
    <!-- 审批通过率饼图 + 审批耗时分组对比 -->
    <!-- 询价到审批完成天数 KPI（保留） -->
  </div>
</section>
```

**Tab 3 (detail, 原 query 改造):** 改为明细下钻查询。

```html
<!-- Tab 3: 多维数据明细 -->
<section class="tab-content" id="tab-detail" role="tabpanel">
  <div class="tab-body">
    <!-- 时间筛选器（从原 Tab 2 移入，与全局筛选器联动） -->
    <!-- 周期功率趋势柱状图（保留原 chart-query-bar） -->
    <!-- 明细数据表格（不再是汇总，而是逐条记录） -->
  </div>
</section>
```

具体内容重组代码较长，将在实施时逐块写入。核心原则：

| 原位置 | 内容 | 新位置 |
|--------|------|--------|
| Tab 1 (summary) | 询价概览 KPI、饼图、功率对比、功率 KPI | Tab 1 (overview) 保留 |
| Tab 1 (summary) | 周期趋势柱状图 | Tab 1 (overview) 改为每日趋势 |
| Tab 3 (dashboard) | 省公司排名图表+表格 | Tab 1 (overview) 移入 |
| Tab 3 (dashboard) | 王剑审批 KPI + 饼图 + 天数 | Tab 2 (approval) 移入、通用化 |
| Tab 2 (query) | 时间筛选 + 功率趋势 + 明细表 | Tab 3 (detail) 移入、增强 |

- [ ] **Step 2: 修改 JS 中 tabCharts 和 tabInitialized 的 tab 名称**

```javascript
const tabCharts = {
  overview:  ['chart-order-donut', 'chart-power-bar', 'chart-daily-trend', 'chart-province-bar'],
  approval:  ['chart-approval-donut', 'chart-approval-compare'],
  detail:    ['chart-query-bar'],
};
const tabInitialized = { overview: false, approval: false, detail: false };
```

- [ ] **Step 3: 删除原 Tab 2 底部"当前选择结果"KPI 卡片区域**

删除 template 中 710-735 行的整个 stats-row 块（id 为 `result-count/module/inverter/battery/ratio` 的元素及相关 HTML）。

- [ ] **Step 4: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "refactor(weekly-report): reorganize tab content - overview/approval/detail structure"
```

---

### Task 3: CSS 排版优化 — 数值右对齐 + 排名图表 60/40 布局

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 表格数值列右对齐**

在 `<style>` 块中新增 CSS 类：

```css
/* 数值右对齐（财务报表规范） */
td.number-right {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
th.number-right {
  text-align: right;
}
```

随后修改表格渲染 JS，对所有含小数点的数值列（功率、容量、金额）使用 `number-right` 类替代 `number-format`。

- [ ] **Step 2: 排名区域 60/40 分栏**

在 `<style>` 块中新增：

```css
.chart-row.split-60-40 {
  grid-template-columns: 3fr 2fr;
}
@media (max-width: 1024px) {
  .chart-row.split-60-40 {
    grid-template-columns: 1fr;
  }
}
```

将省公司排名区域的 `.chart-row` 改为 `.chart-row.split-60-40`。

- [ ] **Step 3: Header 右侧筛选器样式**

在 `<style>` 块中新增：

```css
.header-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--spacing-sm);
}
.global-filter {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  background: rgba(255,255,255,0.12);
  border-radius: var(--radius);
  padding: 6px 12px;
}
.global-filter label {
  font-size: 12px;
  color: rgba(255,255,255,0.9);
  white-space: nowrap;
}
.global-filter select {
  padding: 5px 10px;
  border: 1px solid rgba(255,255,255,0.3);
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-family: var(--font-family);
  background: rgba(255,255,255,0.15);
  color: white;
  cursor: pointer;
  min-width: 100px;
}
.global-filter select:focus {
  outline: 2px solid rgba(255,255,255,0.6);
  outline-offset: 1px;
}
.global-filter select option {
  color: var(--text-primary);
  background: white;
}
```

- [ ] **Step 4: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "style(weekly-report): right-align numeric columns, 60/40 ranking layout, header filter styles"
```

---

### Task 4: 全局时间筛选器 JS 联动逻辑

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 实现全局筛选器联动函数**

在 JS 中新增 `onGlobalPeriodChange()` 函数，切换全局时间段后重置所有 Tab 的图表并重新渲染：

```javascript
/* ===================================================================
   GLOBAL PERIOD FILTER
   =================================================================== */
var currentGlobalPeriod = '本月';

function onGlobalPeriodChange() {
  var sel = document.getElementById('global-period-select');
  if (!sel) return;
  currentGlobalPeriod = sel.value;

  // 同步 Tab 3 内的筛选器
  var detailSel = document.getElementById('period-select');
  if (detailSel) {
    detailSel.value = currentGlobalPeriod;
  }

  // 重置所有 Tab 初始化状态，触发重新渲染
  tabInitialized.overview = false;
  tabInitialized.approval = false;
  tabInitialized.detail = false;

  // 销毁所有现有图表实例
  Object.keys(chartInstances).forEach(function(id) {
    if (chartInstances[id]) {
      chartInstances[id].destroy();
      delete chartInstances[id];
    }
  });

  // 清除所有 no-data 提示
  document.querySelectorAll('.no-data-msg').forEach(function(el) {
    el.remove();
  });
  document.querySelectorAll('canvas').forEach(function(c) {
    c.style.display = '';
  });

  // 重新渲染当前激活的 Tab
  var activeTab = document.querySelector('.tab-content.active');
  if (activeTab) {
    var tabName = activeTab.id.replace('tab-', '');
    initTabCharts(tabName);
    if (tabName === 'detail') {
      renderDetailTable(currentGlobalPeriod);
    }
  }
}
```

- [ ] **Step 2: 修改所有图表初始化函数，根据 `currentGlobalPeriod` 过滤数据**

在 `initSummaryCharts` → `initOverviewCharts`（Task 5 重命名）中，每日趋势图根据 `currentGlobalPeriod` 筛选日期范围。

在 `initDashboardCharts` → `initApprovalCharts`（Task 7 重命名）中，审批图表根据全局筛选器过滤。

- [ ] **Step 3: 修改 DOMContentLoaded 初始化逻辑**

```javascript
document.addEventListener('DOMContentLoaded', function() {
  renderProvinceTable();

  // 初始化默认 tab（overview）的图表
  checkChartJsLoaded();
  initTabCharts('overview');

  // 设置全局筛选器默认值
  var gsel = document.getElementById('global-period-select');
  if (gsel && periodNames.length > 2) {
    gsel.value = periodNames[2] || '本月';
    currentGlobalPeriod = gsel.value;
  }

  // 同步 Tab 3 内部筛选器
  var dsel = document.getElementById('period-select');
  if (dsel) {
    dsel.value = currentGlobalPeriod;
  }
});
```

- [ ] **Step 4: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): implement global period filter with cross-tab chart refresh"
```

---

### Task 5: Python 后端 — 新增每日趋势数据计算

**Files:**
- Modify: `dms-weekly-report/scripts/generate_html_report.py`

- [ ] **Step 1: 新增 `compute_daily_data()` 函数**

在 `compute_period_data` 函数之后新增：

```python
def compute_daily_data(rows: list[list[Any]]) -> dict[str, dict[str, int | float]]:
    """按日期统计每日询价项目数和容量，用于每日趋势折线图。"""
    from collections import defaultdict

    daily: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"count": 0, "module": 0.0, "inverter": 0.0, "battery": 0.0}
    )
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        date_str = ""
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        m = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
        if m:
            date_str = m.group(1)
        else:
            continue

        daily[date_str]["count"] += 1
        if len(row) > 6 and isinstance(row[6], (int, float)):
            daily[date_str]["module"] += float(row[6])
        if len(row) > 7 and isinstance(row[7], (int, float)):
            daily[date_str]["inverter"] += float(row[7])
        if len(row) > 8 and isinstance(row[8], (int, float)):
            daily[date_str]["battery"] += float(row[8])

    # 按日期排序并整理
    sorted_dates = sorted(daily.keys())
    result: dict[str, dict[str, int | float]] = {}
    for date_str in sorted_dates:
        d = daily[date_str]
        result[date_str] = {
            "count": d["count"],
            "module": round(d["module"], 2),
            "inverter": round(d["inverter"], 2),
            "battery": round(d["battery"], 2),
        }
    return result
```

- [ ] **Step 2: 在 `generate_html_report()` 中调用并注入**

在 `generate_html_report` 函数中，紧接 `province_ranking = compute_province_ranking(rows_data)` 之后添加：

```python
daily_data = compute_daily_data(rows_data)
```

在替换阶段，紧接 `html = _replace_json_field(html, "PROVINCE_DATA", province_ranking)` 之后添加：

```python
html = _replace_json_field(html, "DAILY_DATA", daily_data)
```

- [ ] **Step 3: 提交**

```bash
git add dms-weekly-report/scripts/generate_html_report.py
git commit -m "feat(weekly-report): add daily trend data computation for line chart"
```

---

### Task 6: Python 后端 — 审批分组对比数据 + 明细下钻数据 + 审批人列表

**Files:**
- Modify: `dms-weekly-report/scripts/generate_html_report.py`

- [ ] **Step 1: 新增 `compute_approval_by_dimension()` 函数**

在 `compute_approval_days` 之后新增：

```python
def compute_approval_by_dimension(
    rows: list[list[Any]], dimension_col: int
) -> list[dict[str, Any]]:
    """按指定维度（省公司=4 或 业务员=5）统计审批耗时对比数据。"""
    from datetime import datetime as dt_dt

    stats: dict[str, list[int]] = {}
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        key = str(row[dimension_col] if len(row) > dimension_col and row[dimension_col] else "")
        if key in ("--", "无", ""):
            continue
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        final_time = str(row[18] if len(row) > 18 and row[18] else "")
        if submit_time in ("--", "") or final_time in ("--", ""):
            continue
        sm = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
        fm = re.match(r"(\d{4}-\d{2}-\d{2})", final_time)
        if sm and fm:
            try:
                sd = dt_dt.strptime(sm.group(1), "%Y-%m-%d")
                fd = dt_dt.strptime(fm.group(1), "%Y-%m-%d")
                delta = (fd - sd).days
                if delta >= 0:
                    if key not in stats:
                        stats[key] = []
                    stats[key].append(delta)
            except ValueError:
                pass

    result: list[dict[str, Any]] = []
    for key, days in stats.items():
        result.append({
            "name": key,
            "avg": round(sum(days) / len(days), 1),
            "min": min(days),
            "max": max(days),
            "count": len(days),
        })
    # 按平均天数降序排列
    result.sort(key=lambda x: -x["avg"])
    return result
```

- [ ] **Step 2: 新增 `compute_approver_list()` 函数**

```python
def compute_approver_list(rows: list[list[Any]]) -> list[str]:
    """提取所有唯一的采购审批人列表。"""
    approvers: set[str] = set()
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        proc = str(row[16] if len(row) > 16 and row[16] else "")
        if proc and proc not in ("--", "无", ""):
            approvers.add(proc)
    return sorted(approvers)
```

- [ ] **Step 3: 新增 `compute_rows_detail()` 函数**

```python
def compute_rows_detail(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """将原始数据行转为可供前端表格展示的字典列表（明细下钻用）。"""
    detail: list[dict[str, Any]] = []
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        submit_time = str(row[11] if len(row) > 11 and row[11] else "")
        detail.append({
            "flowId": fid,
            "projectName": str(row[1]) if row[1] else "",
            "province": str(row[4]) if row[4] else "",
            "salesperson": str(row[5]) if row[5] else "",
            "modulePower": float(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else 0,
            "inverterPower": float(row[7]) if len(row) > 7 and isinstance(row[7], (int, float)) else 0,
            "batteryCapacity": float(row[8]) if len(row) > 8 and isinstance(row[8], (int, float)) else 0,
            "ordered": str(row[13]) if row[13] else "否",
            "submitDate": submit_time[:10] if len(submit_time) >= 10 else submit_time,
            "provinceApprover": str(row[14]) if len(row) > 14 and row[14] and row[14] != "--" else "",
            "procurementApprover": str(row[16]) if len(row) > 16 and row[16] and row[16] != "--" else "",
            "approvalStatus": str(row[17]) if len(row) > 17 and row[17] and row[17] != "--" else "",
        })
    return detail
```

- [ ] **Step 4: 在 `generate_html_report()` 中调用并注入**

添加调用：
```python
approval_by_province = compute_approval_by_dimension(rows_data, 4)
approval_by_salesperson = compute_approval_by_dimension(rows_data, 5)
approver_list = compute_approver_list(rows_data)
rows_detail = compute_rows_detail(rows_data)
```

添加 JSON 注入：
```python
html = _replace_json_field(html, "APPROVAL_BY_PROVINCE", approval_by_province)
html = _replace_json_field(html, "APPROVAL_BY_SALESPERSON", approval_by_salesperson)
html = _replace_json_field(html, "APPROVER_LIST", approver_list)
html = _replace_json_field(html, "ROWS_DETAIL", rows_detail)
```

- [ ] **Step 5: 修改 `compute_wangjian_stats()` 为通用审批人统计**

将函数改为按审批人名称过滤：

```python
def compute_approver_stats(rows: list[list[Any]], approver_name: str | None = None) -> dict[str, Any]:
    """统计指定审批人的采购审批情况。approver_name 为 None 时统计全部。"""
    approved = 0
    total = 0
    for row in rows:
        fid = str(row[0]) if row[0] else ""
        if not re.match(r"^\d{15,}$", fid):
            continue
        proc = str(row[16] if len(row) > 16 and row[16] else "")
        status_val = str(row[17] if len(row) > 17 and row[17] else "")
        if approver_name and approver_name not in proc:
            continue
        total += 1
        if "审批通过" in status_val:
            approved += 1
    rate = f"{int(approved / total * 100)}%" if total > 0 else "--"
    return {"approved": approved, "total": total, "rate": rate, "name": approver_name or "全部"}
```

保持原 `compute_wangjian_stats` 为兼容别名：
```python
def compute_wangjian_stats(rows: list[list[Any]]) -> dict[str, Any]:
    """兼容旧接口。"""
    return compute_approver_stats(rows, "王剑")
```

- [ ] **Step 6: 提交**

```bash
git add dms-weekly-report/scripts/generate_html_report.py
git commit -m "feat(weekly-report): add approval-by-dimension, approver list, rows detail, and generic approver stats"
```

---

### Task 7: Python 后端 — 更新模板替换映射

**Files:**
- Modify: `dms-weekly-report/scripts/generate_html_report.py`

- [ ] **Step 1: 更新 `generate_html_report()` 中的 kpi_data 和 replacements**

在 `generate_html_report` 函数中，更新 `kpi_data` 字典，增加通用审批人统计的默认值（默认显示"王剑"）：

```python
default_approver = "王剑"
default_stats = compute_approver_stats(rows_data, default_approver)

kpi_data = {
    "orderedCount": kpis["ordered_count"],
    "notOrderedCount": kpis["not_ordered_count"],
    "modulePower": float(kpis["module_power"].replace(",", "")) if isinstance(kpis["module_power"], str) and kpis["module_power"] != "0" else 0,
    "inverterPower": float(kpis["inverter_power"].replace(",", "")) if isinstance(kpis["inverter_power"], str) and kpis["inverter_power"] != "0" else 0,
    "batteryCapacity": float(kpis["battery_capacity"].replace(",", "")) if isinstance(kpis["battery_capacity"], str) and kpis["battery_capacity"] != "0" else 0,
    "approverApproved": default_stats["approved"],
    "approverTotal": default_stats["total"],
    "approverRate": default_stats["rate"],
    "approverName": default_stats["name"],
    "daysAvg": approval_days["avg"],
    "daysMin": approval_days["min"],
    "daysMax": approval_days["max"],
}
```

更新 replacements，使用通用命名替代王剑特定命名：

```python
replacements["APPROVER_STATS_APPROVED"] = str(default_stats["approved"])
replacements["APPROVER_STATS_TOTAL"] = str(default_stats["total"])
replacements["APPROVER_STATS_RATE"] = default_stats["rate"]
replacements["APPROVER_STATS_NAME"] = default_stats["name"]
# 保留旧 key 兼容（模板中不再使用）
```

- [ ] **Step 2: 提交**

```bash
git add dms-weekly-report/scripts/generate_html_report.py
git commit -m "refactor(weekly-report): update template replacements with generic approver stats"
```

---

### Task 8: 前端 JS — Tab 1 每日趋势折线图 + 图表初始化重构

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 新增 `DAILY_DATA` 全局变量声明**

```javascript
const DAILY_DATA = {{DAILY_DATA_JSON}} || {};
```

- [ ] **Step 2: 重写 `initSummaryCharts` → `initOverviewCharts`**

将原 `initSummaryCharts` 函数重命名为 `initOverviewCharts`，并修改第 3 个子图（周期趋势柱状图）为每日趋势折线图：

```javascript
function initOverviewCharts() {
  // ── 1. 订单状态饼图（保持不变）──
  // ... (与原来 initSummaryCharts 中 chart-order-donut 相同)

  // ── 2. 功率容量对比柱状图（保持不变）──
  // ... (与原来 chart-power-bar 相同)

  // ── 3. 每日趋势折线图（替代原周期趋势柱状图）──
  var dailyDates = Object.keys(DAILY_DATA).sort();
  if (dailyDates.length === 0) {
    showNoData('chart-daily-trend', '暂无每日数据');
    return;
  }
  var dailyCounts = dailyDates.map(function(d) {
    return DAILY_DATA[d] ? DAILY_DATA[d].count : 0;
  });
  var dailyModules = dailyDates.map(function(d) {
    return DAILY_DATA[d] ? DAILY_DATA[d].module : 0;
  });

  if (!hasData(dailyCounts)) {
    showNoData('chart-daily-trend', '暂无每日数据');
    return;
  }

  var datasets = [{
    label: '项目数',
    data: dailyCounts,
    borderColor: CHART_COLORS.navy,
    backgroundColor: 'rgba(29,78,216,0.08)',
    fill: true,
    tension: 0.3,
    pointRadius: 4,
    pointBackgroundColor: CHART_COLORS.navy,
    yAxisID: 'y',
  }];
  if (hasData(dailyModules)) {
    datasets.push({
      label: '组件功率 (kW)',
      data: dailyModules,
      borderColor: CHART_COLORS.orange,
      backgroundColor: 'rgba(245,158,11,0.06)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
      pointBackgroundColor: CHART_COLORS.orange,
      yAxisID: 'y1',
    });
  }

  createChart('chart-daily-trend', {
    type: 'line',
    data: { labels: dailyDates, datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 2.2,
      animation: { duration: 600, easing: 'easeOutQuart' },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom', labels: { padding: 16, usePointStyle: true, font: { size: 11 } } },
        tooltip: {
          backgroundColor: '#2C3E50',
          padding: 10,
          cornerRadius: 5,
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 10 }, maxRotation: 45 },
        },
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,0.06)' },
          ticks: { font: { size: 11 }, callback: function(v) { return fmtNum(v); } },
          title: { display: true, text: '项目数', font: { size: 11 } },
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          beginAtZero: true,
          grid: { drawOnChartArea: false },
          ticks: { font: { size: 11 }, callback: function(v) { return fmtNum(v) + ' kW'; } },
          title: { display: true, text: '功率 (kW)', font: { size: 11 } },
        },
      },
    },
  });
}
```

- [ ] **Step 3: 修改 `initTabCharts` 中的 case 映射**

```javascript
switch (tabName) {
  case 'overview': initOverviewCharts(); break;
  case 'approval': initApprovalCharts(); break;
  case 'detail':   initDetailCharts();   break;
}
```

- [ ] **Step 4: 将省公司排名图表初始化移入 `initOverviewCharts`**

在 `initOverviewCharts` 末尾调用省公司排名图表的创建代码（从原 `initDashboardCharts` 移入，代码保持不变，仅 canvasId 不变仍为 `chart-province-bar`）。

- [ ] **Step 5: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): replace period trend bar with daily line chart in overview tab"
```

---

### Task 9: 前端 JS — Tab 3 明细下钻表格 + 筛选联动

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 新增全局变量**

```javascript
const ROWS_DETAIL = {{ROWS_DETAIL_JSON}} || [];
const APPROVAL_BY_PROVINCE = {{APPROVAL_BY_PROVINCE_JSON}} || [];
const APPROVAL_BY_SALESPERSON = {{APPROVAL_BY_SALESPERSON_JSON}} || [];
const APPROVER_LIST = {{APPROVER_LIST_JSON}} || [];
```

- [ ] **Step 2: 实现 `renderDetailTable()` 函数**

```javascript
function renderDetailTable(periodName) {
  var tbody = document.getElementById('detail-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  // 根据全局时间段筛选明细数据
  var filtered = filterDetailByPeriod(ROWS_DETAIL, periodName);

  if (filtered.length === 0) {
    var tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="10" style="text-align:center;padding:32px;color:#95A5A6;">该时间段暂无询价项目明细</td>';
    tbody.appendChild(tr);
    return;
  }

  filtered.forEach(function(item) {
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + escHtml(item.flowId) + '</td>' +
      '<td>' + escHtml(item.projectName) + '</td>' +
      '<td>' + escHtml(item.province) + '</td>' +
      '<td>' + escHtml(item.salesperson) + '</td>' +
      '<td class="number-right">' + (item.modulePower > 0 ? item.modulePower.toFixed(2) : '--') + '</td>' +
      '<td class="number-right">' + (item.inverterPower > 0 ? item.inverterPower.toFixed(2) : '--') + '</td>' +
      '<td class="number-right">' + (item.batteryCapacity > 0 ? item.batteryCapacity.toFixed(2) : '--') + '</td>' +
      '<td>' + escHtml(item.ordered) + '</td>' +
      '<td>' + escHtml(item.submitDate) + '</td>' +
      '<td>' + escHtml(item.procurementApprover) + '</td>';
    tbody.appendChild(tr);
  });

  // 更新筛选结果提示
  var resultEl = document.getElementById('detail-filter-result');
  if (resultEl) {
    resultEl.textContent = '当前：' + periodName + ' → ' + filtered.length + ' 条记录';
  }
}
```

- [ ] **Step 3: 实现 `filterDetailByPeriod()` 辅助函数**

```javascript
function filterDetailByPeriod(rows, periodName) {
  if (!rows || rows.length === 0) return [];
  if (periodName === '全部') return rows;

  var today = new Date();
  var todayStr = today.toISOString().split('T')[0];
  var weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay() + 1); // 周一

  var monthStart = today.getFullYear() + '-' +
    String(today.getMonth() + 1).padStart(2, '0') + '-01';

  var lastMonthEnd = new Date(today.getFullYear(), today.getMonth(), 0);
  var lastMonthStart = today.getFullYear() + '-' +
    String(today.getMonth() === 0 ? 12 : today.getMonth()).padStart(2, '0') + '-01';
  var lastMonthEndStr = lastMonthEnd.toISOString().split('T')[0];

  var quarterStartMonth = Math.floor(today.getMonth() / 3) * 3 + 1;
  var quarterStart = today.getFullYear() + '-' +
    String(quarterStartMonth).padStart(2, '0') + '-01';

  return rows.filter(function(item) {
    var d = item.submitDate;
    if (!d) return false;
    switch (periodName) {
      case '本周':
        return d >= weekStart.toISOString().split('T')[0] && d <= todayStr;
      case '本月':
        return d >= monthStart && d <= todayStr;
      case '上月':
        return d >= lastMonthStart && d <= lastMonthEndStr;
      case '本季度':
        return d >= quarterStart && d <= todayStr;
      default:
        return true;
    }
  });
}
```

- [ ] **Step 4: 修改 `initQueryCharts` → `initDetailCharts`**

将原 `initQueryCharts` 重命名为 `initDetailCharts`，保留功率趋势柱状图逻辑，同时调用 `renderDetailTable(currentGlobalPeriod)`。

- [ ] **Step 5: 修改 Tab 3 表格表头为明细列**

将原汇总表头改为明细表头：

```html
<thead>
  <tr>
    <th>流程编号</th>
    <th>项目名称</th>
    <th>省公司</th>
    <th>业务员</th>
    <th class="number-right">组件功率(kW)</th>
    <th class="number-right">逆变器功率(kW)</th>
    <th class="number-right">电池容量(kWh)</th>
    <th>已下单</th>
    <th>提交日期</th>
    <th>采购审批人</th>
  </tr>
</thead>
<tbody id="detail-table-body"></tbody>
```

- [ ] **Step 6: 修改 `filterByPeriod()` 废弃并替换**

原 `filterByPeriod()` 函数改为废弃，其职责由 `onGlobalPeriodChange()` + `renderDetailTable()` 替代。保留函数体为调用新逻辑：

```javascript
function filterByPeriod() {
  // 已废弃：现在由全局筛选器 onGlobalPeriodChange() 统一处理
  var sel = document.getElementById('period-select');
  if (sel) {
    currentGlobalPeriod = sel.value;
    renderDetailTable(currentGlobalPeriod);
  }
}
```

- [ ] **Step 7: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): implement detail drill-down table with period filter in tab 3"
```

---

### Task 10: 前端 JS — Tab 2 审批图表重构（通用审批人 + 分组对比 + 颜色修复）

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 修改审批 Tab 的 HTML 结构**

将标题从"王剑采购审批统计"改为"关键节点审批统计"并增加审批人选择器：

```html
<h2 class="section-title">
  <span class="title-icon">◉</span>
  关键节点审批统计
  <span class="tooltip-icon" title="统计指定审批人经手的所有询价审批情况。切换审批人后，下方 KPI、饼图和耗时对比图表联动刷新。">(?)</span>
</h2>
<div class="filter-bar">
  <label for="approver-select">👤 审批人：</label>
  <select id="approver-select" onchange="onApproverChange()">
    <option value="全部">全部审批人</option>
  </select>
</div>
```

- [ ] **Step 2: 实现审批人下拉填充逻辑**

```javascript
function populateApproverSelect() {
  var sel = document.getElementById('approver-select');
  if (!sel) return;
  // 保留"全部"选项
  sel.innerHTML = '<option value="全部">全部审批人</option>';
  APPROVER_LIST.forEach(function(name) {
    var opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    // 默认选中"王剑"（如果存在）
    if (name.indexOf('王剑') >= 0) opt.selected = true;
    sel.appendChild(opt);
  });
}
```

- [ ] **Step 3: 实现 `initApprovalCharts()` — 审批通过率饼图（修复颜色）**

```javascript
function initApprovalCharts() {
  // ── 1. 审批通过率饼图 ──
  var approverName = getSelectedApprover();
  var stats = getApproverStats(approverName);
  var wApproved = stats.approved;
  var wTotal = stats.total;
  var wNot = Math.max(0, wTotal - wApproved);

  if (hasData([wApproved, wNot])) {
    createChart('chart-approval-donut', {
      type: 'doughnut',
      data: {
        labels: ['审批通过', '未通过'],
        datasets: [{
          data: [wApproved, wNot],
          backgroundColor: [CHART_COLORS.green, CHART_COLORS.red],  // 修复：未通过用红色
          borderWidth: 2,
          borderColor: '#fff',
        }],
      },
      options: makeDonutOpts(),
    });
  } else {
    showNoData('chart-approval-donut', '暂无审批数据');
  }

  // ── 2. 审批耗时分组对比水平条形图（替代原 avg/min/max）──
  // 默认按省公司维度对比
  var compareData = APPROVAL_BY_PROVINCE;
  if (!compareData || compareData.length === 0) {
    showNoData('chart-approval-compare', '暂无审批耗时对比数据');
    return;
  }
  var labels = compareData.map(function(d) { return d.name; });
  var avgData = compareData.map(function(d) { return d.avg; });

  createChart('chart-approval-compare', {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: '平均审批耗时 (天)',
        data: avgData,
        backgroundColor: labels.map(function(_, i) {
          return CHART_COLORS.palette[i % CHART_COLORS.palette.length];
        }),
        borderRadius: 3,
        maxBarThickness: 30,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: Math.max(1.2, labels.length * 0.25),
      indexAxis: 'y',
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#2C3E50',
          padding: 10,
          cornerRadius: 5,
          callbacks: {
            label: function(ctx) {
              var i = ctx.dataIndex;
              var d = compareData[i];
              return '平均: ' + d.avg + '天 | 最短: ' + d.min + '天 | 最长: ' + d.max + '天 | 样本: ' + d.count + '条';
            },
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,0.06)' },
          ticks: {
            font: { size: 11 },
            callback: function(v) { return fmtNum(v) + '天'; },
          },
        },
        y: {
          grid: { display: false },
          ticks: { font: { size: 11 } },
        },
      },
    },
  });
}

function getSelectedApprover() {
  var sel = document.getElementById('approver-select');
  return sel ? sel.value : '王剑';
}

function getApproverStats(approverName) {
  // 从 KPI_DATA 获取当前审批人统计
  // 注：前端通过 KPI_DATA.approverName 等字段获取
  if (approverName === '全部' || approverName === KPI_DATA.approverName) {
    return {
      approved: parseFloat(KPI_DATA.approverApproved) || 0,
      total: parseFloat(KPI_DATA.approverTotal) || 0,
    };
  }
  // 对于非默认审批人，前端遍历 ROWS_DETAIL 计算
  var approved = 0, total = 0;
  ROWS_DETAIL.forEach(function(row) {
    if (approverName === '全部' || row.procurementApprover.indexOf(approverName) >= 0) {
      total++;
      if (row.approvalStatus.indexOf('审批通过') >= 0) approved++;
    }
  });
  return { approved: approved, total: total };
}

function onApproverChange() {
  // 重置审批 tab 图表并重绘
  var chartIds = tabCharts.approval;
  chartIds.forEach(function(id) {
    if (chartInstances[id]) {
      chartInstances[id].destroy();
      delete chartInstances[id];
    }
  });
  document.querySelectorAll('#tab-approval .no-data-msg').forEach(function(el) { el.remove(); });
  document.querySelectorAll('#tab-approval canvas').forEach(function(c) { c.style.display = ''; });
  initApprovalCharts();
}
```

- [ ] **Step 4: 修改 `initTabCharts` 和 `populateApproverSelect` 调用时机**

在 `switchTab` 函数中，切换到 approval tab 时填充审批人下拉：

```javascript
function switchTab(name) {
  // ... 原有切换逻辑 ...

  setTimeout(function() {
    initTabCharts(name);
    if (name === 'approval') {
      populateApproverSelect();
    }
    if (name === 'detail') {
      renderDetailTable(currentGlobalPeriod);
    }
  }, 80);
}
```

在 DOMContentLoaded 中也调用 `populateApproverSelect()`。

- [ ] **Step 5: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): refactor approval tab with generic approver selector and comparison chart"
```

---

### Task 11: 前端 JS — 空数据状态优化

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 增强 `showNoData()` 函数，支持插画占位符**

```javascript
function showNoData(canvasId, message, icon) {
  var canvas = document.getElementById(canvasId);
  if (!canvas) return;
  var wrap = canvas.parentNode;
  if (!wrap) return;
  var existing = wrap.querySelector('.no-data-msg');
  if (existing) existing.remove();
  canvas.style.display = 'none';

  var container = document.createElement('div');
  container.className = 'no-data-msg';
  container.style.cssText = 'text-align:center;padding:48px 16px;';

  var iconEl = document.createElement('div');
  iconEl.style.cssText = 'font-size:40px;margin-bottom:12px;opacity:0.5;';
  iconEl.textContent = icon || '📭';

  var msgEl = document.createElement('p');
  msgEl.style.cssText = 'color:#95A5A6;font-size:13px;margin:0;';
  msgEl.textContent = message || '暂无数据';

  container.appendChild(iconEl);
  container.appendChild(msgEl);
  wrap.appendChild(container);
}
```

- [ ] **Step 2: 更新所有 `showNoData` 调用，添加语义化图标**

```javascript
// Tab 1
showNoData('chart-order-donut', '暂无订单数据', '📊');
showNoData('chart-power-bar', '暂无功率数据', '⚡');
showNoData('chart-daily-trend', '近期暂无询价项目', '📈');
showNoData('chart-province-bar', '暂无省公司排名数据', '🗺️');

// Tab 2
showNoData('chart-approval-donut', '暂无审批数据', '✅');
showNoData('chart-approval-compare', '暂无审批耗时对比数据', '⏱');

// Tab 3
showNoData('chart-query-bar', '暂无周期功率数据', '📋');
```

- [ ] **Step 3: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): enhance empty state placeholders with semantic icons"
```

---

### Task 12: 审批耗时 Tooltip 说明 + CSS 样式收尾

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 新增 Tooltip 图标 CSS 样式**

```css
/* Tooltip 图标 */
.tooltip-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--border-color);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  cursor: help;
  margin-left: 6px;
  position: relative;
  vertical-align: middle;
  transition: background .2s;
}
.tooltip-icon:hover {
  background: var(--primary);
  color: white;
}
```

- [ ] **Step 2: 在"询价到审批完成天数"标题旁添加 Tooltip**

```html
<h2 class="section-title">
  <span class="title-icon">◉</span>
  询价到审批完成天数
  <span class="tooltip-icon" title="计算方式：从流程发起人提交审核时间（含当日）到最终审批完成时间（含当日）的日历天数。包含周末及节假日。">(?)</span>
</h2>
```

- [ ] **Step 3: 提交**

```bash
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): add approval time calculation tooltip and polish styles"
```

---

### Task 13: 端到端验证与 SKILL.md 更新

**Files:**
- Modify: `dms-weekly-report/SKILL.md`

- [ ] **Step 1: 用测试数据生成 HTML 并验证**

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
python "$SKILL_DIR/scripts/generate_html_report.py" \
  --xlsx "d:/Code/Skills开发/tianhe-skills/询价汇总_20260609_121842.xlsx" \
  --output "d:/Code/Skills开发/tianhe-skills/询价周报报表_ux_refactored.html" \
  --range "2026-06-01 ~ 2026-06-09"
```

在浏览器中打开验证：
- [ ] Tab 导航切换正常，3 个 Tab 命名正确
- [ ] 全局筛选器切换后所有 Tab 图表联动刷新
- [ ] Tab 1 每日折线图正确显示
- [ ] Tab 2 审批人选择器切换后 KPI + 图表联动
- [ ] Tab 3 明细表格按时间段过滤
- [ ] 数值列右对齐
- [ ] 空数据状态占位符正常显示
- [ ] Tooltip 悬浮提示正常

- [ ] **Step 2: 更新 SKILL.md 中的 HTML 相关说明**

在 SKILL.md 的"HTML 独立生成"章节和"输出文件"章节更新描述，反映新的 3 Tab 结构：

```markdown
- `{output_dir}/询价周报报表_{时间戳}.html` — 独立 HTML 报表，3 个 Tab（项目与容量概览/审批与时效流转/多维数据明细），自动与 Excel 同步生成
```

更新 190-193 行的 Sheet 说明以匹配新结构：

```markdown
  - **「数据看板」** — **领导汇报专用**，包含：
    - 关键节点审批统计（支持审批人下拉切换）
    - 省公司审批耗时对比
    - 询价到审批完成的平均天数（含最短/最长）
```

- [ ] **Step 3: 提交**

```bash
git add dms-weekly-report/SKILL.md
git commit -m "docs(weekly-report): update SKILL.md to reflect new 3-tab HTML structure"
```

---

### Task 14: 同步到 Claude skills 目录

- [ ] **Step 1: 执行同步命令**

```bash
rm -rf "$HOME/.claude/skills/dms-weekly-report/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/" "$HOME/.claude/skills/dms-weekly-report/"
```

- [ ] **Step 2: 验证同步结果**

```bash
ls -la "$HOME/.claude/skills/dms-weekly-report/references/report_template.html"
ls -la "$HOME/.claude/skills/dms-weekly-report/scripts/generate_html_report.py"
```

- [ ] **Step 3: 提交（如有 git 变更）**

```bash
# 如果 CLAUDE.md 需要更新
git add CLAUDE.md
git commit -m "chore: sync dms-weekly-report skill after ux refactor"
```

---

## 实施顺序建议

1. **第一批 (后端数据):** Task 5 → Task 6 → Task 7（依次依赖，提供完整 JSON 数据）
2. **第二批 (HTML 结构):** Task 1 → Task 2 → Task 3（依赖 Task 1 的 HTML 结构调整）
3. **第三批 (交互逻辑):** Task 4 → Task 8 → Task 9 → Task 10（依赖前两批完成）
4. **第四批 (收尾):** Task 11 → Task 12（独立优化，可并行）
5. **验证:** Task 13
6. **部署:** Task 14

## 注意事项

1. **保持向后兼容：** `compute_wangjian_stats()` 保留为兼容别名，旧调用方不受影响。
2. **模板占位符：** 新增的 `{{DAILY_DATA_JSON}}`、`{{ROWS_DETAIL_JSON}}` 等必须全部注入，缺一会导致 JS 解析失败。
3. **Chart.js 版本：** 继续使用 4.4.7 CDN，不升级。
4. **响应式：** 所有新增 CSS 需在 `@media (max-width: 768px)` 和 `@media (max-width: 1024px)` 中有降级规则。
