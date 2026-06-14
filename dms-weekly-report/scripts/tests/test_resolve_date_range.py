"""resolve_date_range.py 单元测试。"""

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from resolve_date_range import resolve_date_range

FIXED_TODAY = date(2026, 6, 14)


class TestResolveDateRange(unittest.TestCase):
    """日期范围解析测试。"""

    @patch("resolve_date_range.date")
    def test_this_week(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("本周")
        self.assertIn("start", result)
        self.assertIn("end", result)
        self.assertEqual(result["label"], "本周")
        self.assertLessEqual(result["start"], result["end"])

    @patch("resolve_date_range.date")
    def test_last_week(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("上周")
        self.assertEqual(result["label"], "上周")
        self.assertLessEqual(result["start"], result["end"])

    @patch("resolve_date_range.date")
    def test_this_month(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("本月")
        self.assertEqual(result["label"], "本月")
        self.assertTrue(result["start"].endswith("-01"))

    @patch("resolve_date_range.date")
    def test_last_month(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("上月")
        self.assertEqual(result["label"], "上月")
        self.assertLessEqual(result["start"], result["end"])

    def test_date_range_format1(self):
        result = resolve_date_range("2026-06-01 ~ 2026-06-07")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-07")

    def test_date_range_format2(self):
        result = resolve_date_range("2026-06-01 - 2026-06-07")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-07")

    def test_single_date(self):
        result = resolve_date_range("2026-06-01")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-01")

    @patch("resolve_date_range.date")
    def test_chinese_date_range(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("6月1号到6月7号")
        self.assertIn("start", result)
        self.assertIn("end", result)
        self.assertTrue(result["start"].startswith("2026"))

    @patch("resolve_date_range.date")
    def test_invalid_chinese_date_month31(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("6月31号到7月5号")
        self.assertEqual(result["start"], "")
        self.assertEqual(result["end"], "")
        self.assertIn("❌", result["range_str"])

    @patch("resolve_date_range.date")
    def test_invalid_date_range_reversed(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("6月7号到6月1号")
        self.assertEqual(result["start"], "")
        self.assertEqual(result["end"], "")
        self.assertIn("❌", result["range_str"])

    @patch("resolve_date_range.date")
    def test_english_labels(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("this week")
        self.assertEqual(result["label"], "本周")

    @patch("resolve_date_range.date")
    def test_case_insensitive(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result1 = resolve_date_range("本周")
        result2 = resolve_date_range("本 周")
        self.assertEqual(result1["label"], result2["label"])

    @patch("resolve_date_range.date")
    def test_quarter_parsing(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("本季度")
        self.assertEqual(result["label"], "本季度")
        self.assertLessEqual(result["start"], result["end"])

    @patch("resolve_date_range.date")
    def test_year_parsing(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("今年")
        self.assertEqual(result["label"], "今年")
        self.assertTrue(result["start"].endswith("01-01"))

    def test_unknown_format(self):
        result = resolve_date_range("不知道是啥")
        self.assertEqual(result["start"], "")
        self.assertEqual(result["end"], "")
        self.assertIn("?", result["range_str"])

    # ─── 新功能：相对月 + 日 ───

    @patch("resolve_date_range.date")
    def test_last_month_day_until_now(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("上个月12号到现在")
        self.assertEqual(result["start"], "2026-05-12")
        self.assertEqual(result["end"], "2026-06-14")
        self.assertIn("至今", result["label"])

    @patch("resolve_date_range.date")
    def test_last_month_day_chinese_numeral(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("上个月十二号到现在")
        self.assertEqual(result["start"], "2026-05-12")
        self.assertEqual(result["end"], "2026-06-14")

    @patch("resolve_date_range.date")
    def test_last_month_day_only(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("上月5号")
        self.assertEqual(result["start"], "2026-05-05")
        self.assertEqual(result["end"], "2026-05-31")

    @patch("resolve_date_range.date")
    def test_this_month_day_until_today(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("本月1号至今")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-14")

    @patch("resolve_date_range.date")
    def test_month_day_until_now(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("5月12号到现在")
        self.assertEqual(result["start"], "2026-05-12")
        self.assertEqual(result["end"], "2026-06-14")

    @patch("resolve_date_range.date")
    def test_chinese_date_range_with_cn_numeral(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("六月十二号至今")
        self.assertEqual(result["start"], "2026-06-12")
        self.assertEqual(result["end"], "2026-06-14")

    @patch("resolve_date_range.date")
    def test_chinese_date_range_cn_month_day(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("六月一号到六月七号")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-07")

    @patch("resolve_date_range.date")
    def test_last_month_until_now(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("上个月到现在")
        self.assertEqual(result["start"], "2026-05-01")
        self.assertEqual(result["end"], "2026-06-14")
        self.assertIn("至今", result["label"])

    @patch("resolve_date_range.date")
    def test_this_month_until_now(self, mock_date):
        mock_date.today.return_value = FIXED_TODAY
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = resolve_date_range("本月到现在")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-14")


if __name__ == "__main__":
    unittest.main()
