# 询价周报 HTML 报表 v1.4 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复全局筛选器"假联动"（KPI 不更新）、删除冗余 Tab 3 筛选器、移除每日趋势图、优化功率对比图排版、增加粘性表头、增强"未下单"卡片视觉权重。

**Architecture:** 两层面改动 — (1) Python `compute_period_data()` 扩展为同时输出 ordered/not-ordered/salesperson 计数，使前端可从 `PERIOD_DATA` 按时间段取完整 KPI；(2) HTML 模板删除每日趋势区域、删除 Tab 3 冗余筛选器、JS `onGlobalPeriodChange()` 增加 KPI DOM 更新逻辑、CSS 增加粘性表头和 hover 气泡。

**Tech Stack:** Python 3 (openpyxl), Vanilla HTML/CSS/JS (Chart.js 4.4.7)

---

## 文件变更表

| 文件 | 改动 | 行数估算 |
|------|------|---------|
| `dms-weekly-report/scripts/generate_html_report.py` | 扩展 `compute_period_data` 输出 ordered/not-ordered/salesperson 计数 | +15 |
| `dms-weekly-report/references/report_template.html` | 删除每日趋势 HTML+JS、删除 Tab 3 filter-bar、新增 KPI 更新函数、调整图表比例、粘性表头 | +80/-100 |

---

### Task 1: Python — 扩展 `compute_period_data` 输出完整 KPI

**Files:**
- Modify: `dms-weekly-report/scripts/generate_html_report.py:146-174`

- [ ] **Step 1: 修改 `compute_period_data` 内部循环，增加 ordered/not-ordered/salesperson 统计**

在 `compute_period_data` 函数的 `for row in rows:` 循环内（约第 159 行，`cnt += 1` 所在位置），增加：

```python
# 在 cnt += 1 之后增加：
# 统计是否下单
ordered_val = str(row[13] if len(row) > 13 and row[13] else "")
# 使用局部变量需要在循环前初始化 ordered_cnt, not_ordered_cnt, sp_set

# 统计业务员
sp = str(row[5] if len(row) > 5 and row[5] else "")
```

实际修改：在 `result[name] = {...}` 处增加三个字段。

定位到 `dms-weekly-report/scripts/generate_html_report.py:146-173`，将整个函数体替换：

```python
    result: dict[str, dict[str, float | int]] = {}
    for name, (s, e) in periods.items():
        cnt = 0
        ordered_cnt = 0
        not_ordered_cnt = 0
        mod = 0.0
        inv = 0.0
        bat = 0.0
        sp_set: set[str] = set()
        for row in rows:
            fid = str(row[0]) if row[0] else ""
            if not re.match(r"^\d{15,}$", fid):
                continue
            o = _parse_date(row[11] if len(row) > 11 else None)
            if o is None or o < s or o > e:
                continue
            cnt += 1
            # 下单状态
            ordered_val = str(row[13] if len(row) > 13 and row[13] else "")
            if ordered_val == "是":
                ordered_cnt += 1
            else:
                not_ordered_cnt += 1
            # 业务员
            sp = str(row[5] if len(row) > 5 and row[5] else "")
            if sp and sp not in ("--", "无", ""):
                sp_set.add(sp)
            # 容量
            if len(row) > 6 and isinstance(row[6], (int, float)):
                mod += float(row[6])
            if len(row) > 7 and isinstance(row[7], (int, float)):
                inv += float(row[7])
            if len(row) > 8 and isinstance(row[8], (int, float)):
                bat += float(row[8])
        ratio = round(mod / inv, 2) if inv > 0 else 0
        result[name] = {
            "count": cnt,
            "ordered": ordered_cnt,
            "notOrdered": not_ordered_cnt,
            "salespersons": len(sp_set),
            "module": round(mod, 2),
            "inverter": round(inv, 2),
            "battery": round(bat, 2),
            "ratio": ratio,
        }
    return result
```

- [ ] **Step 2: 验证 Python 语法**

```bash
cd "d:/Code/Skills开发/tianhe-skills" && python -m py_compile dms-weekly-report/scripts/generate_html_report.py && echo "语法检查通过"
```

- [ ] **Step 3: 提交**

```bash
cd "d:/Code/Skills开发/tianhe-skills"
git add dms-weekly-report/scripts/generate_html_report.py
git commit -m "feat(weekly-report): extend PERIOD_DATA with ordered/not-ordered/salesperson counts per period"
```

---

### Task 2: HTML — 删除每日趋势区域 + 放大功率对比图

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 删除 Tab 1 每日趋势 HTML 块（689-702 行）**

删除整个块：
```html
<!-- ──────────── 每日趋势折线图（替代原周期趋势柱状图）──────────── -->
<h2 class="section-title">...</h2>
<div class="chart-row single">...</div>
```

- [ ] **Step 2: 功率对比图从 1:1 改为 2:3 分栏，减少留白**

将 643 行的 `<div class="chart-row">` 改为 `<div class="chart-row split-40-60">`：

```html
<div class="chart-row split-40-60">
```

在 `<style>` 中新增对应 CSS（在 `.chart-row.split-60-40` 之后）：

```css
.chart-row.split-40-60 {
  grid-template-columns: 2fr 3fr;
}
```

并在 `@media (max-width: 1024px)` 内增加回退：
```css
.chart-row.split-40-60 { grid-template-columns: 1fr; }
```

- [ ] **Step 3: 功率柱状图增加 `aspectRatio` 控制留白**

在 `initOverviewCharts` 中图表 2 的 `makeBarOpts` 调用改为自定义 options，降低 `aspectRatio`：

```javascript
// 原: options: makeBarOpts('类型', '容量'),
// 改为自定义 options:
options: {
  responsive: true,
  maintainAspectRatio: true,
  aspectRatio: 1.6,  // 原默认 2.2 → 降低减少纵向留白
  animation: { duration: 600, easing: 'easeOutQuart' },
  plugins: {
    legend: {
      position: 'bottom',
      labels: { padding: 16, usePointStyle: true, font: { size: 11 } },
    },
    tooltip: {
      backgroundColor: '#2C3E50',
      padding: 10,
      cornerRadius: 5,
      callbacks: {
        label: function(ctx) {
          return ctx.dataset.label + ': ' + fmtNum(ctx.parsed.y);
        }
      }
    },
  },
  scales: {
    x: { grid: { display: false }, ticks: { font: { size: 11 } } },
    y: {
      beginAtZero: true,
      grid: { color: 'rgba(0,0,0,0.06)' },
      ticks: { font: { size: 11 }, callback: function(v) { return fmtNum(v); } },
    },
  },
}
```

- [ ] **Step 4: 从 `tabCharts` 中移除 `chart-daily-trend`**

```javascript
const tabCharts = {
  overview:  ['chart-order-donut', 'chart-power-bar', 'chart-province-bar'],  // 移除 chart-daily-trend
  approval:  ['chart-approval-donut', 'chart-approval-compare'],
  detail:    ['chart-query-bar'],
};
```

- [ ] **Step 5: 删除 `initOverviewCharts` 中第 3 段每日趋势折线图的创建代码（1211-1284 行）**

整个 `// ── 3. 每日趋势折线图 ──` 至省公司排名前的代码块，全部删除。

- [ ] **Step 6: 提交**

```bash
cd "d:/Code/Skills开发/tianhe-skills"
git add dms-weekly-report/references/report_template.html
git commit -m "refactor(weekly-report): remove daily trend chart, enlarge power bar with 40/60 split"
```

---

### Task 3: HTML — 全局筛选器驱动 KPI 卡片更新（修复 P0）

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 给 Tab 1 的 4 个 KPI 卡片 value 添加 id**

```html
<div class="kpi-card highlight">
  <div class="label">询价项目总数</div>
  <div class="value" id="kpi-total-projects">{{KPI_TOTAL_PROJECTS}}</div>
  <div class="unit">个</div>
</div>
<div class="kpi-card">
  <div class="label">涉及业务员</div>
  <div class="value" id="kpi-total-salespersons">{{KPI_TOTAL_SALESPERSONS}}</div>
  <div class="unit">人</div>
</div>
<div class="kpi-card green">
  <div class="label">已下单</div>
  <div class="value" id="kpi-ordered">{{KPI_ORDERED_COUNT}}</div>
  <div class="unit">个</div>
</div>
<div class="kpi-card orange">
  <div class="label">未下单</div>
  <div class="value" id="kpi-not-ordered">{{KPI_NOT_ORDERED_COUNT}}</div>
  <div class="unit">个</div>
</div>
```

同样给功率容量 KPI 卡片 value 添加 id：
```html
<div class="value" id="kpi-module-power">{{KPI_MODULE_POWER}}</div>
<div class="value" id="kpi-inverter-power">{{KPI_INVERTER_POWER}}</div>
<div class="value" id="kpi-battery-capacity">{{KPI_BATTERY_CAPACITY}}</div>
<div class="value" id="kpi-ratio">{{KPI_RATIO}}</div>
```

- [ ] **Step 2: 新增 `updateOverviewKPIs()` 函数**

在 JS 中（`onApproverChange` 函数之前或 `onGlobalPeriodChange` 之前）新增：

```javascript
/* ===================================================================
   KPI UPDATE — 根据全局时间段刷新 Tab 1 所有 KPI 卡片
   =================================================================== */
function updateOverviewKPIs(periodName) {
  var d = PERIOD_DATA[periodName];
  if (!d) return;

  // 汇总 KPI
  var elTotal = document.getElementById('kpi-total-projects');
  if (elTotal) elTotal.textContent = d.count;
  var elSp = document.getElementById('kpi-total-salespersons');
  if (elSp) elSp.textContent = d.salespersons;
  var elOrdered = document.getElementById('kpi-ordered');
  if (elOrdered) elOrdered.textContent = d.ordered;
  var elNot = document.getElementById('kpi-not-ordered');
  if (elNot) elNot.textContent = d.notOrdered;

  // 容量 KPI
  var elMod = document.getElementById('kpi-module-power');
  if (elMod) elMod.textContent = fmtNum(d.module);
  var elInv = document.getElementById('kpi-inverter-power');
  if (elInv) elInv.textContent = fmtNum(d.inverter);
  var elBat = document.getElementById('kpi-battery-capacity');
  if (elBat) elBat.textContent = fmtNum(d.battery);
  var elRatio = document.getElementById('kpi-ratio');
  if (elRatio) elRatio.textContent = d.ratio.toFixed(2);
}
```

- [ ] **Step 3: 在 `onGlobalPeriodChange` 中调用 `updateOverviewKPIs`**

在 `onGlobalPeriodChange()` 函数中，`currentGlobalPeriod = sel.value;` 之后立即添加：

```javascript
// 更新 Tab 1 KPI 卡片
updateOverviewKPIs(currentGlobalPeriod);
```

- [ ] **Step 4: 删除 Tab 3 的 filter-bar 段落（842-852 行）**

删除：
```html
<div class="filter-bar">
  <label for="period-select">📅 时间段筛选：</label>
  <select id="period-select" onchange="filterByPeriod()">...</select>
  <span class="filter-result" id="detail-filter-result"></span>
</div>
```

替换为动态提示语：
```html
<p style="font-size:13px;color:var(--text-secondary);margin-bottom:var(--spacing-lg);background:var(--primary-l5);padding:10px 16px;border-radius:var(--radius);border-left:3px solid var(--primary);">
  💡 当前正在展示 <strong id="detail-period-label">本月</strong> 的询价项目明细。如需切换，请使用右上角 <strong>全局时间筛选</strong>。
</p>
```

- [ ] **Step 5: 更新 `renderDetailTable` 中动态更新提示文案**

在 `renderDetailTable` 函数中增加：
```javascript
var label = document.getElementById('detail-period-label');
if (label) label.textContent = periodName;
```

同时删除 `filterByPeriod()` 函数中对 `period-select` 的引用，简化该函数或直接删除（因为 Tab 3 不再有本地筛选器）。

- [ ] **Step 6: 简化 `onGlobalPeriodChange`，移除 Tab 3 同步代码**

删除 `onGlobalPeriodChange` 中 Tab 3 筛选器同步的代码块：
```javascript
// 删除以下 4 行:
// 同步 Tab 3 内的筛选器
var detailSel = document.getElementById('period-select');
if (detailSel) {
  detailSel.value = currentGlobalPeriod;
}
```

- [ ] **Step 7: 提交**

```bash
cd "d:/Code/Skills开发/tianhe-skills"
git add dms-weekly-report/references/report_template.html
git commit -m "fix(weekly-report): wire global filter to KPI cards, remove redundant Tab 3 filter"
```

---

### Task 4: CSS — 粘性表头 + 未下单卡片视觉增强 + Hover Tooltip

**Files:**
- Modify: `dms-weekly-report/references/report_template.html`

- [ ] **Step 1: 表格粘性表头 CSS**

在 `<style>` 中 `thead th` 选择器（约 351 行）增加 `position: sticky;`：

```css
thead th {
  background: var(--primary);
  color: white;
  padding: 11px 14px;
  text-align: center;
  font-weight: 500;
  white-space: nowrap;
  font-size: 12px;
  letter-spacing: 0.3px;
  position: sticky;
  top: 48px;   /* Tab 导航栏高度 */
  z-index: 10;
}
```

注意：Tab 导航栏 `.tab-nav` 是 `position: sticky; top: 0; z-index: 100;`，表头 `top: 48px` 刚好在导航栏下方。

- [ ] **Step 2: "未下单"卡片增加高亮视觉锚点**

将"未下单" KPI 卡片的 `class="kpi-card orange"` 改为 `class="kpi-card orange highlight"`。

同时为 `.kpi-card.orange.highlight` 补充 CSS，确保 highlight 左框线覆盖 orange 左框线：

```css
.kpi-card.orange.highlight {
  border-left: 4px solid var(--primary);
}
.kpi-card.orange.highlight .label { color: var(--primary); font-weight: 600; }
```

- [ ] **Step 3: CSS Hover 气泡 Tooltip（替换原生 title）**

删除模板中审批天数 section title 内的 `title` 属性（保留 `class="tooltip-icon"`），新增 CSS 伪元素气泡：

```css
/* Tooltip 气泡 */
.tooltip-icon {
  /* ... 保持原有样式 ... */
  position: relative;
}
.tooltip-icon::after {
  content: attr(data-tip);
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  background: #2C3E50;
  color: white;
  font-size: 11px;
  font-weight: 400;
  padding: 6px 12px;
  border-radius: 4px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity .2s;
  z-index: 200;
}
.tooltip-icon:hover::after {
  opacity: 1;
}
```

修改 HTML 中 tooltip-icon，将 `title="..."` 改为 `data-tip="..."`：

```html
<span class="tooltip-icon" data-tip="计算方式：从流程发起人提交审核时间（含当日）到最终审批完成时间（含当日）的日历天数，包含周末及节假日。">(?)</span>
```

- [ ] **Step 4: 提交**

```bash
cd "d:/Code/Skills开发/tianhe-skills"
git add dms-weekly-report/references/report_template.html
git commit -m "feat(weekly-report): sticky table header, emphasize 未下单 card, CSS hover tooltip"
```

---

### Task 5: 端到端验证 + 同步

- [ ] **Step 1: 生成测试 HTML 并验证**

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
python "$SKILL_DIR/scripts/generate_html_report.py" \
  --xlsx "d:/Code/Skills开发/tianhe-skills/询价汇总_20260609_121842.xlsx" \
  --output "d:/Code/Skills开发/tianhe-skills/询价周报报表_v14.html" \
  --range "2026-06-01 ~ 2026-06-09"
```

在浏览器中验证：
- [ ] 全局筛选器切换后 Tab 1 的 4 个核心 KPI 数值联动变化
- [ ] Tab 3 无本地时间段筛选器，只有提示文字
- [ ] 每日趋势图已删除，功率对比图占比更大
- [ ] "未下单"卡片有高亮左边框
- [ ] 表格表头粘性固定
- [ ] Tooltip `(?)` 悬浮气泡正常显示

- [ ] **Step 2: 检查无残留占位符**

```bash
grep -c '{{.*}}' "d:/Code/Skills开发/tianhe-skills/询价周报报表_v14.html"
# 期望: 0
```

- [ ] **Step 3: 同步到 skills 目录**

```bash
rm -rf "$HOME/.claude/skills/dms-weekly-report/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/" "$HOME/.claude/skills/dms-weekly-report/"
```

- [ ] **Step 4: 提交**

```bash
cd "d:/Code/Skills开发/tianhe-skills"
git add dms-weekly-report/
git commit -m "chore(weekly-report): sync v1.4 fixes to skills directory"
```

---

## 实施顺序

1. **Task 1** — Python 数据层（为 Task 3 提供 `PERIOD_DATA.ordered/notOrdered/salespersons`）
2. **Task 2 + Task 3 + Task 4** — 可并行编辑同一文件，建议合并执行
3. **Task 5** — 验证 + 同步

## 自审清单

- [x] **Spec 覆盖**: P0 KPI 假联动 → Task 1+3; P0 冗余筛选器 → Task 3 Step 4-6; 每日趋势删除 → Task 2; 功率图留白 → Task 2 Step 2-3; 粘性表头 → Task 4 Step 1; 未下单视觉 → Task 4 Step 2; Hover Tooltip → Task 4 Step 3
- [x] **无占位符**: 所有步骤都有具体代码
- [x] **类型一致**: `PERIOD_DATA[name].ordered` / `.notOrdered` / `.salespersons` 在 Task 1 定义，Task 3 使用
