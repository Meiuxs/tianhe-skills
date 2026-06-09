# 日期范围解析器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建独立日期解析脚本，用户说"本周""上月""本季度"等中文短语，自动算出起止日期，替代 SKILL.md 步骤 1 中 AskUserQuestion 的三选一确认流程。

**Architecture:** 新增 `scripts/resolve_date_range.py` 作为纯函数 CLI 工具，接收中文时段标签输出 JSON。SKILL.md 步骤 1 改为直接调用此脚本 + 用户一句话输入模式。

**Tech Stack:** Python 3.10+, 标准库（`datetime`, `calendar`, `json`, `argparse`），无需第三方依赖。

---

## 文件结构

| 文件 | 变更 | 职责 |
|------|------|------|
| `scripts/resolve_date_range.py` | **新建** | 中文时段 → `{start, end, label, range_str}` 的纯函数 + CLI |
| `SKILL.md` | **修改** | 步骤 1 改为使用 resolve_date_range.py 的简化流程 |
| `docs/superpowers/plans/2026-06-09-date-range-resolver.md` | 本文件 | 实施计划 |

不修改 `run_weekly_report.py` 或 `generate_html_report.py` — 新脚本是 agent 工作流层的工具，不是脚本内部库。

---

### Task 1: 创建 `resolve_date_range.py`（核心 + CLI）

**Files:**
- Create: `scripts/resolve_date_range.py`
- Test: 通过命令行手动验证

```python
#!/usr/bin/env python3
"""将中文时段标签解析为起止日期。

用法:
    python resolve_date_range.py "本周"
    python resolve_date_range.py "上月"
    python resolve_date_range.py "2026-06-01 ~ 2026-06-07"

输出 JSON: {"start": "2026-06-01", "end": "2026-06-07", "label": "本周", "range_str": "2026-06-01 ~ 2026-06-07"}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, date


# ==================== 解析逻辑 ====================


def _first_day_of_month(d: date) -> date:
    """当月第一天。"""
    return d.replace(day=1)


def _last_day_of_month(d: date) -> date:
    """当月最后一天。"""
    next_month = d.replace(day=28) + timedelta(days=4)  # 跨月安全
    return next_month.replace(day=1) - timedelta(days=1)


def _monday_of_week(d: date) -> date:
    """d 所在周的周一。"""
    return d - timedelta(days=d.weekday())


def _sunday_of_week(d: date) -> date:
    """d 所在周的周日。"""
    return _monday_of_week(d) + timedelta(days=6)


def resolve_date_range(label: str) -> dict[str, str]:
    """将中文时段标签解析为起止日期。

    支持的标签（大小写/空格不敏感）:
        本周, 本周, 这周, this week
        上周, 上一周, last week
        本月, 这个月, this month
        上月, 上个月, last month
        本季度, 这个季度, this quarter
        上季度, 上个季度, last quarter
        今年, 本年, this year
        去年, 上年, last year
        YYYY-MM-DD ~ YYYY-MM-DD  (原始日期范围)

    Returns:
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": str, "range_str": str}
    """
    today = date.today()
    raw = label.strip()

    # ── 先尝试匹配原始日期范围 ──
    m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s*[~\-]\s*(\d{4}-\d{2}-\d{2})\s*$', raw)
    if m:
        start_str, end_str = m.group(1), m.group(2)
        return {
            "start": start_str,
            "end": end_str,
            "label": f"{start_str} ~ {end_str}",
            "range_str": f"{start_str} ~ {end_str}",
        }

    # ── 标准化输入：去空格、小写化
    s = raw.lower().replace(" ", "")

    # ── 本周 ──
    if s in ("本周", "这周", "thisweek"):
        start = _monday_of_week(today)
        end = today
        label_cn = "本周"
    # ── 上周 ──
    elif s in ("上周", "上一周", "lastweek"):
        last_monday = _monday_of_week(today) - timedelta(days=7)
        start = last_monday
        end = _sunday_of_week(last_monday)
        label_cn = "上周"
    # ── 本月 ──
    elif s in ("本月", "这个月", "thismonth"):
        start = _first_day_of_month(today)
        end = today
        label_cn = "本月"
    # ── 上月 ──
    elif s in ("上月", "上个月", "lastmonth"):
        first_this = _first_day_of_month(today)
        start = _first_day_of_month(first_this - timedelta(days=1))
        end = _last_day_of_month(start)
        label_cn = "上月"
    # ── 本季度 ──
    elif s in ("本季度", "这个季度", "thisquarter"):
        q_start_month = (today.month - 1) // 3 * 3 + 1
        start = date(today.year, q_start_month, 1)
        end = today
        label_cn = "本季度"
    # ── 上季度 ──
    elif s in ("上季度", "上个季度", "lastquarter"):
        q_start_month = (today.month - 1) // 3 * 3 + 1
        first_this_q = date(today.year, q_start_month, 1)
        first_last_q = first_this_q - timedelta(days=1)
        q_start_month = (first_last_q.month - 1) // 3 * 3 + 1
        start = date(first_last_q.year, q_start_month, 1)
        end = _last_day_of_month(date(first_last_q.year, q_start_month + 2, 1))
        label_cn = "上季度"
    # ── 今年 ──
    elif s in ("今年", "本年", "thisyear"):
        start = date(today.year, 1, 1)
        end = today
        label_cn = "今年"
    # ── 去年 ──
    elif s in ("去年", "上年", "lastyear"):
        start = date(today.year - 1, 1, 1)
        end = date(today.year - 1, 12, 31)
        label_cn = "去年"
    else:
        # 尝试解析 "2026-06-01" 单日期 → 当天范围
        m2 = re.match(r'^(\d{4}-\d{2}-\d{2})$', raw)
        if m2:
            return {
                "start": raw,
                "end": raw,
                "label": raw,
                "range_str": raw,
            }
        # 尝试 "6月1号到6月7号" 等中文日期格式
        m3 = re.match(r'^(\d{1,2})月(\d{1,2})号?\s*(到|~|-)\s*(\d{1,2})月?(\d{1,2})号?$', raw)
        if m3:
            m1, d1, _, m2, d2 = m3.groups()
            y = today.year
            sd = date(y, int(m1), int(d1))
            ed = date(y, int(m2), int(d2))
            return {
                "start": sd.strftime("%Y-%m-%d"),
                "end": ed.strftime("%Y-%m-%d"),
                "label": f"{int(m1)}月{int(d1)}日~{int(m2)}月{int(d2)}日",
                "range_str": f"{sd.strftime('%Y-%m-%d')} ~ {ed.strftime('%Y-%m-%d')}",
            }
        # fallback: 无法解析
        return {
            "start": "",
            "end": "",
            "label": raw,
            "range_str": f"? {raw}",
        }

    return {
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "label": label_cn,
        "range_str": f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}",
    }


# ==================== CLI ====================


def main() -> None:
    parser = argparse.ArgumentParser(description="将中文时段标签解析为起止日期")
    parser.add_argument("label", nargs="*", help="时段标签（如 本周，本月，上周，YYYY-MM-DD ~ YYYY-MM-DD）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    label = " ".join(args.label) if args.label else "本周"

    result = resolve_date_range(label)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return

    if not result["start"]:
        print(f"❌ 无法解析: {label}")
        print(f"   支持: 本周, 本月, 上周, 上月, 本季度, 上季度, 今年, 去年")
        print(f"   也支持: YYYY-MM-DD ~ YYYY-MM-DD")
        sys.exit(1)

    print(f"📅 {result['label']}: {result['range_str']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 1: 创建脚本文件**

写入上述完整代码到 `scripts/resolve_date_range.py`。

- [ ] **Step 2: 验证所有标签解析正确**

```bash
cd "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/scripts"
python resolve_date_range.py "本周"
# 输出: 📅 本周: 2026-06-01 ~ 2026-06-09

python resolve_date_range.py "上周"
# 输出: 📅 上周: 2026-05-25 ~ 2026-05-31

python resolve_date_range.py "本月"
# 输出: 📅 本月: 2026-06-01 ~ 2026-06-09

python resolve_date_range.py "上月"
# 输出: 📅 上月: 2026-05-01 ~ 2026-05-31

python resolve_date_range.py "本季度"
# 输出: 📅 本季度: 2026-04-01 ~ 2026-06-09

python resolve_date_range.py "上季度"
# 输出: 📅 上季度: 2026-01-01 ~ 2026-03-31

python resolve_date_range.py "2026-06-01 ~ 2026-06-07" --json
# 输出: {"start": "2026-06-01", "end": "2026-06-07", ...}

python resolve_date_range.py "6月1号到6月7号"
# 输出: 📅 6月1日~6月7日: 2026-06-01 ~ 2026-06-07
```

- [ ] **Step 3: 验证无效标签处理**

```bash
cd "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/scripts"
python resolve_date_range.py "不存在的标签"
# 输出: ❌ 无法解析: 不存在的标签
# 退出码: 1
```

- [ ] **Step 4: 验证 JSON 输出模式**

```bash
cd "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/scripts"
python resolve_date_range.py "上周" --json
# 输出: {"start": "2026-05-25", "end": "2026-05-31", "label": "上周", "range_str": "2026-05-25 ~ 2026-05-31"}
```

---

### Task 2: 更新 SKILL.md 步骤 1

**Files:**
- Modify: `SKILL.md`（第 39-93 行步骤 1）

将原有的 AskUserQuestion 三选一流程替换为：

```markdown
### 步骤 1：解析日期范围

**不再需要三选一确认。** 直接根据用户话语中的时段词调用日期解析脚本：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
RANGE=$(python "$SKILL_DIR/scripts/resolve_date_range.py" "本周" --json)
START=$(echo "$RANGE" | python -c "import sys,json;print(json.load(sys.stdin)['start'])")
END=$(echo "$RANGE" | python -c "import sys,json;print(json.load(sys.stdin)['end'])")
RANGE_STR=$(echo "$RANGE" | python -c "import sys,json;print(json.load(sys.stdin)['range_str'])")
```

**匹配规则（从用户话语中提取时段词）：**

| 用户说... | 传给脚本的标签 | 行为 |
|-----------|---------------|------|
| "帮我把本周的询价做一下周报" | `"本周"` | 本周一到今天 |
| "做上周的周报" / "做上一周的" | `"上周"` | 上周一到上周日 |
| "查一下这个月的情况" / "做本月统计" | `"本月"` | 本月一号到今天 |
| "上个月的询价汇总一下" | `"上月"` | 上个月整月 |
| "做本季度的报表" | `"本季度"` | 本季度第一天到今天 |
| "看看去年全年的数据" | `"去年"` | 去年1月1日到12月31日 |
| "查 6月1号到6月7号的数据" | `"6月1号到6月7号"` | 自动解析中文日期格式 |
| 用户没说任何时段（只说"做周报"） | `"本周"` | 默认本周 |

**提取方法：** 从用户话语中按优先级匹配关键词
1. 先检查 "去年"/"上季度"/"本季度"/"上月"/"本月"/"上周"/"本周"
2. 再检查中文日期范围 `\d{1,2}月\d{1,2}号?\s*(到|~)\s*...`
3. 最后检查 `YYYY-MM-DD ~ YYYY-MM-DD`
4. 都无匹配 → 默认 `"本周"`，**然后向用户说一句**：
   > "没检测到时段时间，默认按本周（本周一~今天）统计。如果需要其他时段请告诉我。"

> 不再使用 `AskUserQuestion` 方式让用户三选一确认，直接用脚本解析。只有在解析失败时（`resolve_date_range.py` 退出码非 0）才回退询问用户。
```

- [ ] **Step 5: 编辑 SKILL.md**

用上述内容替换第 39-93 行（原步骤 1）。

---

### Task 3: 同步所有变更

- [ ] **Step 6: 同步到 skills 目录并提交**

```bash
# 同步到 skills
rm -rf "$HOME/.claude/skills/dms-weekly-report/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/" "$HOME/.claude/skills/dms-weekly-report/"

# 验证
ls -la "$HOME/.claude/skills/dms-weekly-report/scripts/resolve_date_range.py"
python "$HOME/.claude/skills/dms-weekly-report/scripts/resolve_date_range.py" "本周"

# 提交
git add -A
git commit -m "feat(weekly-report): 添加日期范围解析脚本，简化步骤1的日期确认流程"
```

---

## 自检清单

**1. 需求覆盖度：**
- [x] 用户说"本周" → 本周一到今天 ✅ (Task 1)
- [x] 用户说"本月" → 本月1号到今今天 ✅ (Task 1)
- [x] 用户说"上周" → 上周一到上周日 ✅ (Task 1)
- [x] 用户说"上月" → 上个月整月 ✅ (Task 1)
- [x] 用户说"本季度" → 季度初到今天 ✅ (Task 1)
- [x] 用户说"上季度" → 上季度整季 ✅ (Task 1)
- [x] 用户说"今年"/"去年" → 整年 ✅ (Task 1)
- [x] 用户说中文日期"6月1号到6月7号" → 解析 ✅ (Task 1)
- [x] 用户说 "YYYY-MM-DD ~ YYYY-MM-DD" → 透传 ✅ (Task 1)
- [x] 最后一个标签不自定义 → 用户说啥就解析啥 ✅ (Task 2 匹配规则)
- [x] 无法解析时回退询问 ✅ (Task 2)

**2. 占位符检查：** 无 TBD/TODO/FIXME/占位符代码。

**3. 类型一致性：** `resolve_date_range()` 始终返回 `{"start": str, "end": str, "label": str, "range_str": str}`；CLI 输出端到端一致。
