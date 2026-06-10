#!/usr/bin/env python3
"""lookup_by_code.py 测试套件（dms-inventory 版）。

覆盖范围：
  1. lookup_by_code 精确查询
  2. lookup_by_name 模糊查询
  3. lookup_by_code_or_name 并集查询
  4. _build_category_result 聚合/非聚合
  5. format_text 文本格式化
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from lookup_by_code import (
    lookup_by_code,
    lookup_by_name,
    lookup_by_code_or_name,
    _build_category_result,
    format_text,
    CATEGORY_META,
    VALID_CATEGORIES,
)


# ═══════════════════════════════════════════════════════════
#  Mock 数据
# ═══════════════════════════════════════════════════════════

MOCK_COMPONENTS = pd.DataFrame({
    "物料编号": ["6B001492", "6B001492", "6B001440"],
    "物料名称": [
        "销售组件_TSM-NEG21C.20_730W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_730W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_715W_18BB_银边框_33mm_竖装",
    ],
    "功率": ["730W", "730W", "715W"],
    "可用库存": [1115.0, 7286.0, 10.0],
    "仓库名称": ["天合富家-南宁仓", "天合富家-郑州仓", "天合富家-金华仓"],
})


# ═══════════════════════════════════════════════════════════
#  1. lookup_by_code
# ═══════════════════════════════════════════════════════════

class TestLookupByCode(unittest.TestCase):
    """测试 lookup_by_code"""

    def setUp(self):
        self.df = MOCK_COMPONENTS.copy()
        self.meta = CATEGORY_META["组件"]

    def test_find_exact_match(self):
        """精确匹配物料编号"""
        result = lookup_by_code(self.df, "6B001492", self.meta)
        self.assertEqual(len(result), 2)

    def test_no_match(self):
        """不存在的物料编号"""
        result = lookup_by_code(self.df, "NONEXIST", self.meta)
        self.assertEqual(len(result), 0)

    def test_case_sensitive_strip(self):
        """前后空格不影响匹配（内部做 strip）"""
        result = lookup_by_code(self.df, "  6B001492  ", self.meta)
        self.assertEqual(len(result), 2)


# ═══════════════════════════════════════════════════════════
#  2. lookup_by_name
# ═══════════════════════════════════════════════════════════

class TestLookupByName(unittest.TestCase):
    """测试 lookup_by_name"""

    def setUp(self):
        self.df = MOCK_COMPONENTS.copy()
        self.meta = CATEGORY_META["组件"]

    def test_find_by_keyword(self):
        """按名称关键词查询"""
        result = lookup_by_name(self.df, "730W", self.meta)
        self.assertEqual(len(result), 2)

    def test_case_insensitive(self):
        """大小写不敏感"""
        result = lookup_by_name(self.df, "730w", self.meta)
        self.assertEqual(len(result), 2)

    def test_no_match(self):
        """不存在的关键词"""
        result = lookup_by_name(self.df, "NONEXIST", self.meta)
        self.assertEqual(len(result), 0)

    def test_partial_keyword(self):
        """部分匹配"""
        result = lookup_by_name(self.df, "TSM", self.meta)
        self.assertEqual(len(result), 3)


# ═══════════════════════════════════════════════════════════
#  3. lookup_by_code_or_name
# ═══════════════════════════════════════════════════════════

class TestLookupByCodeOrName(unittest.TestCase):
    """测试 lookup_by_code_or_name"""

    def setUp(self):
        self.df = MOCK_COMPONENTS.copy()
        self.meta = CATEGORY_META["组件"]

    def test_by_code_only(self):
        """仅编码"""
        result = lookup_by_code_or_name(self.df, code="6B001492", meta=self.meta)
        self.assertEqual(len(result), 2)

    def test_by_name_only(self):
        """仅名称"""
        result = lookup_by_code_or_name(self.df, name="715W", meta=self.meta)
        self.assertEqual(len(result), 1)

    def test_both(self):
        """同时传入时取并集"""
        result = lookup_by_code_or_name(self.df, code="6B001492", name="715W", meta=self.meta)
        # 6B001492 有2行 + 715W 有1行 = 3行（不重复）
        self.assertEqual(len(result), 3)

    def test_neither(self):
        """都不传时返回空"""
        result = lookup_by_code_or_name(self.df, meta=self.meta)
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════
#  4. _build_category_result
# ═══════════════════════════════════════════════════════════

class TestBuildCategoryResult(unittest.TestCase):
    """测试 _build_category_result"""

    def setUp(self):
        self.df = MOCK_COMPONENTS.copy()
        self.meta = CATEGORY_META["组件"]

    def test_empty_df(self):
        """空 DataFrame 返回 None"""
        result = _build_category_result(pd.DataFrame(), self.meta, aggregate=False)
        self.assertIsNone(result)

    def test_non_aggregate(self):
        """非聚合时返回多行"""
        result = _build_category_result(self.df, self.meta, aggregate=False)
        self.assertEqual(len(result), 3)
        self.assertIn("仓库名称", result[0])
        self.assertIn("可用库存", result[0])

    def test_aggregate(self):
        """聚合时按物料编号去重"""
        result = _build_category_result(self.df, self.meta, aggregate=True)
        self.assertEqual(len(result), 2)
        self.assertIn("库存总量", result[0])

    def test_json_serializable(self):
        """返回结果可序列化"""
        result = _build_category_result(self.df, self.meta, aggregate=True)
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)
        self.assertEqual(len(parsed), 2)


# ═══════════════════════════════════════════════════════════
#  5. format_text
# ═══════════════════════════════════════════════════════════

class TestFormatText(unittest.TestCase):
    """测试 format_text"""

    def test_empty_results(self):
        """空结果"""
        text = format_text({"组件": None}, code="6B001492")
        self.assertIn("未找到", text)

    def test_with_records(self):
        """有结果时"""
        meta = CATEGORY_META["组件"]
        records = _build_category_result(MOCK_COMPONENTS, meta, aggregate=False)
        text = format_text({"组件": records}, name="730W")
        self.assertIn("【组件】", text)
        self.assertIn("6B001492", text)

    def test_aggregate_format(self):
        """聚合格式"""
        meta = CATEGORY_META["组件"]
        records = _build_category_result(MOCK_COMPONENTS, meta, aggregate=True)
        text = format_text({"组件": records}, code="6B001492")
        self.assertIn("库存总量", text)


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
