"""resolve_date_range.py 单元测试。"""

import unittest
from datetime import date, timedelta
from resolve_date_range import resolve_date_range


class TestResolveDateRange(unittest.TestCase):
    """日期范围解析测试。"""

    def test_this_week(self):
        """测试'本周'解析。"""
        result = resolve_date_range("本周")
        self.assertIn("start", result)
        self.assertIn("end", result)
        self.assertEqual(result["label"], "本周")
        # 检查 start 是周一，end 是今天或之前
        self.assertLessEqual(result["start"], result["end"])

    def test_last_week(self):
        """测试'上周'解析。"""
        result = resolve_date_range("上周")
        self.assertEqual(result["label"], "上周")
        self.assertLessEqual(result["start"], result["end"])

    def test_this_month(self):
        """测试'本月'解析。"""
        result = resolve_date_range("本月")
        self.assertEqual(result["label"], "本月")
        # start 应该是 1 号
        self.assertTrue(result["start"].endswith("-01"))

    def test_last_month(self):
        """测试'上月'解析。"""
        result = resolve_date_range("上月")
        self.assertEqual(result["label"], "上月")
        self.assertLessEqual(result["start"], result["end"])

    def test_date_range_format1(self):
        """测试标准日期范围格式 (YYYY-MM-DD ~ YYYY-MM-DD)。"""
        result = resolve_date_range("2026-06-01 ~ 2026-06-07")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-07")

    def test_date_range_format2(self):
        """测试日期范围格式带横线。"""
        result = resolve_date_range("2026-06-01 - 2026-06-07")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-07")

    def test_single_date(self):
        """测试单日期解析。"""
        result = resolve_date_range("2026-06-01")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-01")

    def test_chinese_date_range(self):
        """测试中文日期范围。"""
        result = resolve_date_range("6月1号到6月7号")
        self.assertIn("start", result)
        self.assertIn("end", result)
        # 应该包含当前年份
        self.assertTrue(result["start"].startswith("2026"))

    def test_invalid_chinese_date_month31(self):
        """测试无效的中文日期（6 月 31 号不存在）。"""
        result = resolve_date_range("6月31号到7月5号")
        # 应该返回空的 start 和 end，并包含错误信息
        self.assertEqual(result["start"], "")
        self.assertEqual(result["end"], "")
        self.assertIn("❌", result["range_str"])

    def test_invalid_date_range_reversed(self):
        """测试日期范围颠倒（起始 > 结束）。"""
        result = resolve_date_range("6月7号到6月1号")
        # 应该返回错误
        self.assertEqual(result["start"], "")
        self.assertEqual(result["end"], "")
        self.assertIn("❌", result["range_str"])

    def test_english_labels(self):
        """测试英文标签。"""
        result = resolve_date_range("this week")
        self.assertEqual(result["label"], "本周")

    def test_case_insensitive(self):
        """测试大小写不敏感。"""
        result1 = resolve_date_range("本周")
        result2 = resolve_date_range("本 周")
        self.assertEqual(result1["label"], result2["label"])

    def test_quarter_parsing(self):
        """测试季度解析。"""
        result = resolve_date_range("本季度")
        self.assertEqual(result["label"], "本季度")
        self.assertLessEqual(result["start"], result["end"])

    def test_year_parsing(self):
        """测试年度解析。"""
        result = resolve_date_range("今年")
        self.assertEqual(result["label"], "今年")
        self.assertTrue(result["start"].endswith("01-01"))

    def test_unknown_format(self):
        """测试未识别的格式。"""
        result = resolve_date_range("不知道是啥")
        self.assertEqual(result["start"], "")
        self.assertEqual(result["end"], "")
        self.assertIn("?", result["range_str"])

    # ─── 新功能：相对月 + 日 ───

    def test_last_month_day_until_now(self):
        """测试'上个月X号到现在'（相对月+日+至今）。"""
        result = resolve_date_range("上个月12号到现在")
        self.assertEqual(result["start"], "2026-05-12")
        self.assertEqual(result["end"], "2026-06-12")
        self.assertIn("至今", result["label"])

    def test_last_month_day_chinese_numeral(self):
        """测试中文数字'上个月十二号到现在'。"""
        result = resolve_date_range("上个月十二号到现在")
        self.assertEqual(result["start"], "2026-05-12")
        self.assertEqual(result["end"], "2026-06-12")

    def test_last_month_day_only(self):
        """测试'上月X号'（相对月+日，无至今→到月末）。"""
        result = resolve_date_range("上月5号")
        self.assertEqual(result["start"], "2026-05-05")
        self.assertEqual(result["end"], "2026-05-31")

    def test_this_month_day_until_today(self):
        """测试'本月X号至今'。"""
        result = resolve_date_range("本月1号至今")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-12")

    def test_month_day_until_now(self):
        """测试'X月X号到现在'。"""
        result = resolve_date_range("5月12号到现在")
        self.assertEqual(result["start"], "2026-05-12")
        self.assertEqual(result["end"], "2026-06-12")

    def test_chinese_date_range_with_cn_numeral(self):
        """测试中文数字日期范围'六月十二号至今'。"""
        result = resolve_date_range("六月十二号至今")
        self.assertEqual(result["start"], "2026-06-12")
        self.assertEqual(result["end"], "2026-06-12")

    def test_chinese_date_range_cn_month_day(self):
        """测试中文数字的'6月1号到6月7号'。"""
        result = resolve_date_range("六月一号到六月七号")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-07")

    def test_last_month_until_now(self):
        """测试'上个月到现在'（不带日号）。"""
        result = resolve_date_range("上个月到现在")
        self.assertEqual(result["start"], "2026-05-01")
        self.assertEqual(result["end"], "2026-06-12")
        self.assertIn("至今", result["label"])

    def test_this_month_until_now(self):
        """测试'本月到现在'。"""
        result = resolve_date_range("本月到现在")
        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-12")


if __name__ == "__main__":
    unittest.main()
