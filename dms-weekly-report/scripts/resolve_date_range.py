#!/usr/bin/env python3
"""将中文时段标签解析为起止日期。

架构定位：
  本模块是日期解析层，被 SKILL.md 步骤 1 通过 CLI 调用。
  将用户自然语言（"本周""上月""6月1号到6月7号""上个月12号到现在"）转为标准日期范围。
  输出 JSON 供 Agent shell 变量使用，驱动后续 run_weekly_report.py 的 --start-date/--end-date。

支持的输入格式：
  - 中文标签: 本周, 上周, 本月, 上月, 本季度, 上季度, 今年, 去年
  - 英文标签: this week, last week, this month, last month 等
  - 日期范围: YYYY-MM-DD ~ YYYY-MM-DD
  - 中文日期: 6月1号到6月7号, 6月十二号到现在
  - 相对月+日: 上个月12号, 上月十二号, 上个月12号至今
  - 单日期:   2026-06-01

用法:
    python resolve_date_range.py "本周"
    python resolve_date_range.py "上月"
    python resolve_date_range.py "上个月12号到现在"
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


# ==================== 中文数字转换 ====================

_CN_DIGITS = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
}
_CN_TEN = '十'


def _cn_digit_to_int(text: str) -> int | None:
    """将中文数字字符串转为整数，非中文数字返回 None。

    支持: 一~九, 十, 十一~十九, 二十~九十, 二十一~九十九
    """
    if not text:
        return None
    # 纯阿拉伯数字
    if text.isdigit():
        return int(text)
    # 中文数字
    if _CN_TEN in text:
        parts = text.split(_CN_TEN)
        left = _CN_DIGITS.get(parts[0], 0) if parts[0] else 1
        right = _CN_DIGITS.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        if parts[0] == '':
            # "十" → 10, "十二" → 12
            left = 1
        return left * 10 + right
    return _CN_DIGITS.get(text)


_CN_YUE_MAP = {
    '一月': 1, '二月': 2, '三月': 3, '四月': 4, '五月': 5, '六月': 6,
    '七月': 7, '八月': 8, '九月': 9, '十月': 10, '十一月': 11, '十二月': 12,
    '1月': 1, '2月': 2, '3月': 3, '4月': 4, '5月': 5, '6月': 6,
    '7月': 7, '8月': 8, '9月': 9, '10月': 10, '11月': 11, '12月': 12,
}


def _extract_day_num(s: str) -> int | None:
    """从字符串中提取日号（支持阿拉伯和中文数字），如 '12号' → 12, '十二号' → 12, '12' → 12"""
    s = s.strip().rstrip('号').strip()
    return _cn_digit_to_int(s)


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


def _last_month_range(today: date) -> tuple[date, date]:
    """上个月的起止日期。"""
    first_this = _first_day_of_month(today)
    start = _first_day_of_month(first_this - timedelta(days=1))
    end = _last_day_of_month(start)
    return start, end


def _make_result(start: date, end: date, label: str) -> dict[str, str]:
    return {
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "label": label,
        "range_str": f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}",
    }


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
        6月1号到6月7号  (中文日期范围)
        上个月12号  (相对月+日)
        上个月12号到现在 / 上个月十二号至今  (相对月+日+至今)

    Returns:
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": str, "range_str": str}
        解析失败时 start/end 为空字符串。
    """
    today = date.today()
    raw = label.strip()
    normalized = raw.lower().replace(" ", "")

    # ─── 原始日期范围 ───
    m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s*[~\-]\s*(\d{4}-\d{2}-\d{2})\s*$', raw)
    if m:
        return {
            "start": m.group(1),
            "end": m.group(2),
            "label": f"{m.group(1)} ~ {m.group(2)}",
            "range_str": f"{m.group(1)} ~ {m.group(2)}",
        }

    # ─── 单日期 ───
    m = re.match(r'^(\d{4}-\d{2}-\d{2})$', raw)
    if m:
        return {
            "start": raw,
            "end": raw,
            "label": raw,
            "range_str": raw,
        }

    # ─── 标准关键词匹配 ───
    keyword_map = {
        frozenset({"本周", "这周", "thisweek"}): (
            _monday_of_week(today), today, "本周"),
        frozenset({"上周", "上一周", "lastweek"}): (
            _monday_of_week(today) - timedelta(days=7),
            _sunday_of_week(_monday_of_week(today) - timedelta(days=7)),
            "上周",
        ),
        frozenset({"本月", "这个月", "thismonth"}): (
            _first_day_of_month(today), today, "本月"),
        frozenset({"上月", "上个月", "lastmonth"}): (
            *_last_month_range(today), "上月"),
        frozenset({"本季度", "这个季度", "thisquarter"}): (
            date(today.year, (today.month - 1) // 3 * 3 + 1, 1),
            today,
            "本季度",
        ),
        frozenset({"上季度", "上个季度", "lastquarter"}): (
            _first_day_of_month(
                date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
                - timedelta(days=1)
            ).replace(day=1),
            _last_day_of_month(
                date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
                - timedelta(days=1)
            ),
            "上季度",
        ),
        frozenset({"今年", "本年", "thisyear"}): (
            date(today.year, 1, 1), today, "今年"),
        frozenset({"去年", "上年", "lastyear"}): (
            date(today.year - 1, 1, 1),
            date(today.year - 1, 12, 31),
            "去年",
        ),
    }
    for keywords, (start, end, label_cn) in keyword_map.items():
        if normalized in keywords:
            return _make_result(start, end, label_cn)

    # ─── 中文日期范围："6月1号到6月7号"（支持中文数字）───
    m = re.match(
        r'^(\d{1,2}|[一二三四五六七八九十]+)月'
        r'(\d{1,2}|[一二三四五六七八九十]+)号?\s*(到|~|-)\s*'
        r'(\d{1,2}|[一二三四五六七八九十]+)月?'
        r'(\d{1,2}|[一二三四五六七八九十]+)号?$',
        raw,
    )
    if m:
        m1 = _cn_digit_to_int(m.group(1))
        d1 = _cn_digit_to_int(m.group(2))
        m2 = _cn_digit_to_int(m.group(4))
        d2 = _cn_digit_to_int(m.group(5))
        if m1 and d1 and m2 and d2:
            try:
                sd = date(today.year, m1, d1)
                ed = date(today.year, m2, d2)
                if sd > ed:
                    return {"start": "", "end": "", "label": raw,
                            "range_str": f"❌ 日期范围错误：起始日期 {sd} > 结束日期 {ed}"}
                return _make_result(sd, ed, f"{m1}月{d1}日~{m2}月{d2}日")
            except ValueError as e:
                return {"start": "", "end": "", "label": raw,
                        "range_str": f"❌ 日期无效：{e}"}

    # ─── 相对月 + 日（含"到现在/至今"）───
    # 匹配: (上个月|本月|这个月) X号 (到现在|至今|到今天)?
    rel_month_pat = r'(上个月|上月|本月|这个月)'
    day_pat = r'(\d{1,2}|[一二三四五六七八九十]+)号?'
    until_now_pat = r'(到现在|至今|到今天)?'
    m = re.match(
        rf'^{rel_month_pat}\s*{day_pat}\s*{until_now_pat}$',
        raw,
    )
    if m:
        rel = m.group(1)
        day_num = _extract_day_num(m.group(2))
        until_now = m.group(3) or ''
        if day_num is None:
            return {"start": "", "end": "", "label": raw, "range_str": f"? {raw}"}
        try:
            if rel in ('上月', '上个月'):
                base_start, base_end = _last_month_range(today)
                # 上个月的 day_num 日
                sd = base_start.replace(day=min(day_num, _last_day_of_month(base_start).day))
            else:  # 本月, 这个月
                sd = date(today.year, today.month, min(day_num, _last_day_of_month(today).day))
            # 有"到现在/至今" → 结束到今天；否则结束到该月最后一天
            if until_now:
                ed = today
            else:
                ed = _last_day_of_month(sd)
            if sd > ed:
                sd, ed = ed, sd
            return _make_result(sd, ed, f"{rel}{day_num}日{'至今' if until_now else ''}")
        except ValueError:
            return {"start": "", "end": "", "label": raw, "range_str": f"? {raw}"}

    # ─── 相对月 + 到现在（不带具体日号）───
    # 匹配: 上个月到现在, 上月至今, 本月到现在 等
    m = re.match(
        r'^(上个月|上月|本月|这个月)(到现在|至今|到今天)$',
        raw,
    )
    if m:
        rel = m.group(1)
        if rel in ('上月', '上个月'):
            base_start, _ = _last_month_range(today)
            sd = base_start
        else:  # 本月, 这个月
            sd = _first_day_of_month(today)
        return _make_result(sd, today, f"{rel}至今")

    # ─── 中文日期 + 至今："5月12号到现在"、"六月十二号至今" ───
    m = re.match(
        r'^(\d{1,2}|[一二三四五六七八九十]+)月'
        r'(\d{1,2}|[一二三四五六七八九十]+)号?'
        r'(到现在|至今|到今天)$',
        raw,
    )
    if m:
        month_num = _cn_digit_to_int(m.group(1))
        day_num = _cn_digit_to_int(m.group(2))
        if month_num and day_num:
            try:
                sd = date(today.year, month_num, day_num)
                if sd > today:
                    sd = sd.replace(year=today.year - 1)
                return _make_result(sd, today, f"{month_num}月{day_num}日至今")
            except ValueError as e:
                return {"start": "", "end": "", "label": raw,
                        "range_str": f"❌ 日期无效：{e}"}

    # ─── fallback ───
    return {"start": "", "end": "", "label": raw, "range_str": f"? {raw}"}


# ==================== CLI ====================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将中文时段标签解析为起止日期",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python resolve_date_range.py 本周
  python resolve_date_range.py 上月 --json
  python resolve_date_range.py 上个月12号到现在 --json
  python resolve_date_range.py 2026-06-01~2026-06-07 --json
  python resolve_date_range.py 六月一号到六月七号 --json

支持的关键词:
  本周 / 上周 / 本月 / 上月 / 本季度 / 上季度 / 今年 / 去年

支持的自然表述:
  上个月12号到现在     → 上月12日 ~ 今天
  上个月十二号到现在    → 同上（支持中文数字）
  上个月到现在          → 上月1日 ~ 今天
  5月12号到现在         → 今年5月12日 ~ 今天
  六月一号到六月七号    → 今年6月1日 ~ 6月7日

标准格式:
  YYYY-MM-DD ~ YYYY-MM-DD
  YYYY-MM-DD
""",
    )
    parser.add_argument("label", nargs="*", help="时段标签（如 本周，本月，上周，上个月12号到现在）")
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
        print(f"   也支持: 上个月12号到现在")
        sys.exit(1)

    print(f"📅 {result['label']}: {result['range_str']}")


if __name__ == "__main__":
    main()
