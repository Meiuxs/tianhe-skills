#!/usr/bin/env python3
"""将中文时段标签解析为起止日期。

架构定位：
  本模块是日期解析层，被 SKILL.md 步骤 1 通过 CLI 调用。
  将用户自然语言（“本周”“上月”“6月1号到6月7号”）转为标准日期范围。
  输出 JSON 供 Agent shell 变量使用，驱动后续 run_weekly_report.py 的 --start-date/--end-date。

支持的输入格式：
  - 中文标签: 本周, 上周, 本月, 上月, 本季度, 上季度, 今年, 去年
  - 英文标签: this week, last week, this month, last month 等
  - 日期范围: YYYY-MM-DD ~ YYYY-MM-DD
  - 中文日期: 6月1号到6月7号
  - 单日期:   2026-06-01

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
from datetime import date, timedelta

# Windows 终端中文乱码修复（与项目其他脚本一致）
import _compat  # noqa: F401


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
        本周, 这周, this week
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

    # 先尝试匹配原始日期范围
    m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s*[~\-]\s*(\d{4}-\d{2}-\d{2})\s*$', raw)
    if m:
        start_str, end_str = m.group(1), m.group(2)
        return {
            "start": start_str,
            "end": end_str,
            "label": f"{start_str} ~ {end_str}",
            "range_str": f"{start_str} ~ {end_str}",
        }

    # 标准化输入：去空格、小写化
    s = raw.lower().replace(" ", "")

    # 本周
    if s in ("本周", "这周", "thisweek"):
        start = _monday_of_week(today)
        end = today
        label_cn = "本周"
    # 上周
    elif s in ("上周", "上一周", "lastweek"):
        last_monday = _monday_of_week(today) - timedelta(days=7)
        start = last_monday
        end = _sunday_of_week(last_monday)
        label_cn = "上周"
    # 本月
    elif s in ("本月", "这个月", "thismonth"):
        start = _first_day_of_month(today)
        end = today
        label_cn = "本月"
    # 上月
    elif s in ("上月", "上个月", "lastmonth"):
        first_this = _first_day_of_month(today)
        start = _first_day_of_month(first_this - timedelta(days=1))
        end = _last_day_of_month(start)
        label_cn = "上月"
    # 本季度
    elif s in ("本季度", "这个季度", "thisquarter"):
        q_start_month = (today.month - 1) // 3 * 3 + 1
        start = date(today.year, q_start_month, 1)
        end = today
        label_cn = "本季度"
    # 上季度
    elif s in ("上季度", "上个季度", "lastquarter"):
        q_start_month = (today.month - 1) // 3 * 3 + 1
        first_this_q = date(today.year, q_start_month, 1)
        first_last_q = first_this_q - timedelta(days=1)
        q_start_month = (first_last_q.month - 1) // 3 * 3 + 1
        start = date(first_last_q.year, q_start_month, 1)
        end = _last_day_of_month(date(first_last_q.year, q_start_month + 2, 1))
        label_cn = "上季度"
    # 今年
    elif s in ("今年", "本年", "thisyear"):
        start = date(today.year, 1, 1)
        end = today
        label_cn = "今年"
    # 去年
    elif s in ("去年", "上年", "lastyear"):
        start = date(today.year - 1, 1, 1)
        end = date(today.year - 1, 12, 31)
        label_cn = "去年"
    else:
        # 尝试解析 "2026-06-01" 单日期
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
