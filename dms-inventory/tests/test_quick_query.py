#!/usr/bin/env python3
"""quick_query.py 测试套件（dms-inventory 版）。

覆盖范围：
  1. _query_by_code 精确查询
  2. _query_by_name 模糊查询
  3. _query_by_power 功率查询
  4. query 多条件 AND 语义
  5. _build_category_result 聚合/非聚合
  6. format_text 文本格式化
"""

import json
import os
import sys
import unittest

import pandas as pd

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from quick_query import (
    _build_category_result,
    _query_by_code,
    _query_by_name,
    _query_by_power,
    format_text,
    query,
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

MOCK_INVERTERS = pd.DataFrame({
    "物料编号": ["AB001311", "AB001395"],
    "物料名称": [
        "组串式逆变器_TS-SN110TL3H-T9_110kW_天合原装专用(40A*2+20A*7)",
        "组串式逆变器_GW110K-GT_110kW_固德威",
    ],
    "功率": ["110KW三相", "110KW三相"],
    "可用库存": [0.0, 0.0],
    "仓库名称": ["天合富家-常州西北仓", "天合富家-常州西北仓"],
    "厂家": ["天合", "固德威"],
})


# ═══════════════════════════════════════════════════════════
#  1. _query_by_code
# ═══════════════════════════════════════════════════════════

class TestQueryByCode(unittest.TestCase):
    """测试 _query_by_code"""

    def setUp(self):
        self.df = MOCK_COMPONENTS.copy()
        self.meta = CATEGORY_META["组件"]

    def test_find_exact_match(self):
        result = _query_by_code(self.df, "6B001492", self.meta)
        self.assertEqual(len(result), 2)

    def test_no_match(self):
        result = _query_by_code(self.df, "NONEXIST", self.meta)
        self.assertEqual(len(result), 0)

    def test_case_sensitive_strip(self):
        result = _query_by_code(self.df, "  6B001492  ", self.meta)
        self.assertEqual(len(result), 2)


# ═══════════════════════════════════════════════════════════
#  2. _query_by_name
# ═══════════════════════════════════════════════════════════

class TestQueryByName(unittest.TestCase):
    """测试 _query_by_name"""

    def setUp(self):
        self.df = MOCK_COMPONENTS.copy()
        self.meta = CATEGORY_META["组件"]

    def test_find_by_keyword(self):
        result = _query_by_name(self.df, "730W", self.meta)
        self.assertEqual(len(result), 2)

    def test_case_insensitive(self):
        result = _query_by_name(self.df, "730w", self.meta)
        self.assertEqual(len(result), 2)

    def test_no_match(self):
        result = _query_by_name(self.df, "NONEXIST", self.meta)
        self.assertEqual(len(result), 0)

    def test_partial_keyword(self):
        result = _query_by_name(self.df, "TSM", self.meta)
        self.assertEqual(len(result), 3)

    def test_only_searches_name_col(self):
        """确认只搜物料名称列，不搜功率列"""
        meta_inv = CATEGORY_META["逆变器"]
        # "KW三相" 只出现在功率列，不在名称列
        result = _query_by_name(MOCK_INVERTERS, "KW三相", meta_inv)
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════
#  2b. _query_by_power
# ═══════════════════════════════════════════════════════════

class TestQueryByPower(unittest.TestCase):
    """测试 _query_by_power"""

    def test_find_by_power_keyword(self):
        result = _query_by_power(MOCK_COMPONENTS, "730W", CATEGORY_META["组件"])
        self.assertEqual(len(result), 2)

    def test_case_insensitive(self):
        result = _query_by_power(MOCK_COMPONENTS, "730w", CATEGORY_META["组件"])
        self.assertEqual(len(result), 2)

    def test_no_match(self):
        result = _query_by_power(MOCK_COMPONENTS, "9999W", CATEGORY_META["组件"])
        self.assertEqual(len(result), 0)

    def test_partial_power(self):
        result = _query_by_power(MOCK_COMPONENTS, "715", CATEGORY_META["组件"])
        self.assertEqual(len(result), 1)

    def test_missing_power_col(self):
        meta_no_power = dict(CATEGORY_META["组件"])
        meta_no_power["power_col"] = None
        result = _query_by_power(MOCK_COMPONENTS, "730W", meta_no_power)
        self.assertEqual(len(result), 0)

    def test_finds_110kw_by_power(self):
        """功率列含 `110KW三相`，搜索 `110KW` 应匹配"""
        meta_inv = CATEGORY_META["逆变器"]
        result = _query_by_power(MOCK_INVERTERS, "110KW", meta_inv)
        self.assertEqual(len(result), 2)


# ═══════════════════════════════════════════════════════════
#  3. query（多条件 AND）
# ═══════════════════════════════════════════════════════════

class TestQueryAnd(unittest.TestCase):
    """测试 query 的多条件交集语义"""

    def test_single_code(self):
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"], code="6B001492")
        self.assertEqual(len(result), 2)

    def test_single_name(self):
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"], name="715W")
        self.assertEqual(len(result), 1)

    def test_single_power(self):
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"], power="730W")
        self.assertEqual(len(result), 2)

    def test_code_and_name_and(self):
        """code + name 取交集：编码6B001492 且 名称含730W"""
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"],
                       code="6B001492", name="730W")
        # 6B001492 有2行，都是730W → 2行
        self.assertEqual(len(result), 2)

    def test_code_and_name_and_no_match(self):
        """code + name 取交集：编码6B001492 但 名称含715W → 无匹配"""
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"],
                       code="6B001492", name="715W")
        self.assertEqual(len(result), 0)

    def test_name_and_power_and(self):
        """name + power 取交集：名称含固德威 且 功率=110KW"""
        meta_inv = CATEGORY_META["逆变器"]
        result = query(MOCK_INVERTERS, meta_inv,
                       name="固德威", power="110KW")
        self.assertEqual(len(result), 1)

    def test_name_and_power_and_no_match(self):
        """name + power：名称含730W 且 功率=715W → 无匹配"""
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"],
                       name="730W", power="715W")
        self.assertEqual(len(result), 0,
                         "名称搜730W 且 功率=715W 应为空集")

    def test_all_three_and(self):
        """code + name + power 三者都 AND"""
        meta_inv = CATEGORY_META["逆变器"]
        result = query(MOCK_INVERTERS, meta_inv,
                       code="AB001311", name="天合原装", power="110KW")
        self.assertEqual(len(result), 1)

    def test_neither(self):
        """无参数返回空"""
        result = query(MOCK_COMPONENTS, CATEGORY_META["组件"])
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
        result = _build_category_result(pd.DataFrame(), self.meta, aggregate=False)
        self.assertIsNone(result)

    def test_non_aggregate(self):
        result = _build_category_result(self.df, self.meta, aggregate=False)
        self.assertEqual(len(result), 3)
        self.assertIn("仓库名称", result[0])
        self.assertIn("可用库存", result[0])

    def test_aggregate(self):
        result = _build_category_result(self.df, self.meta, aggregate=True)
        self.assertEqual(len(result), 2)
        self.assertIn("库存总量", result[0])

    def test_json_serializable(self):
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
        text = format_text({"组件": None}, code="6B001492")
        self.assertIn("未找到", text)

    def test_with_records(self):
        meta = CATEGORY_META["组件"]
        records = _build_category_result(MOCK_COMPONENTS, meta, aggregate=False)
        text = format_text({"组件": records}, name="730W")
        self.assertIn("【组件】", text)
        self.assertIn("6B001492", text)

    def test_aggregate_format(self):
        meta = CATEGORY_META["组件"]
        records = _build_category_result(MOCK_COMPONENTS, meta, aggregate=True)
        text = format_text({"组件": records}, code="6B001492")
        self.assertIn("库存总量", text)

    def test_power_header(self):
        """带 --power 参数时显示功率查询头部"""
        text = format_text({}, power="110KW")
        self.assertIn("按功率查询 [110KW]", text)


# ═══════════════════════════════════════════════════════════
# 6. 空条件警告
# ═══════════════════════════════════════════════════════════

class TestEmptyConditionWarning(unittest.TestCase):
    """测试空条件时输出警告"""

    def test_empty_condition_warning(self):
        """所有条件都是空字符串时应输出警告到 stderr"""
        import io
        from contextlib import redirect_stderr

        df = pd.DataFrame({'物料编号': ['C001'], '物料名称': ['组件A']})
        meta = CATEGORY_META['组件']

        # code="" 被视为无效条件
        stderr_capture = io.StringIO()
        with redirect_stderr(stderr_capture):
            result = query(df, meta, code="", name="", power="")

        warning = stderr_capture.getvalue()
        # 应有警告输出
        self.assertIn("警告", warning)
        self.assertTrue(result.empty)


# ═══════════════════════════════════════════════════════════
# 7. 跨品类搜索
# ═══════════════════════════════════════════════════════════

class TestCrossCategorySearch(unittest.TestCase):
    """测试跨品类搜索"""

    def test_search_all_categories(self):
        """不指定 --category 时应搜索全部品类"""
        mock_data = {
            '组件': pd.DataFrame({
                '物料编号': ['C001'],
                '物料名称': ['730W组件'],
                '功率': ['730W'],
                '可用库存': [100.0],
                '仓库名称': ['仓A'],
            }),
            '逆变器': pd.DataFrame({
                '物料编号': ['I001'],
                '物料名称': ['50KW逆变器'],
                '功率': ['50KW三相'],
                '可用库存': [10.0],
                '仓库名称': ['仓B'],
                '厂家': ['华为'],
            }),
            '并网箱': pd.DataFrame({
                '并网箱类型': ['标准'],
                '功率': ['50KW三相'],
                '物料编号': ['B001'],
                '物料名称': ['并网箱'],
                '可用库存': [5.0],
                '仓库名称': ['仓C'],
            }),
        }

        # 直接测试 query 函数跨品类
        results = {}
        for cat in VALID_CATEGORIES:
            df = mock_data.get(cat, pd.DataFrame())
            if df.empty:
                continue
            matched = query(df, CATEGORY_META[cat], power="50")
            if not matched.empty:
                results[cat] = matched

        # 50KW 应匹配逆变器和并网箱
        self.assertIn('逆变器', results)
        self.assertIn('并网箱', results)


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
