#!/usr/bin/env python3
"""inverter_config.py 测试套件（dms-inventory 版）。

覆盖范围：
  1. calculate_inverter_range 功率范围计算
  2. find_inverter_combinations 贪心组合算法（Mock 数据）
  3. format_combination 格式化输出
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

from inverter_config import (
    calculate_inverter_range,
    find_inverter_combinations,
    format_combination,
)

MOCK_INVERTERS = pd.DataFrame({
    "厂家": ["爱士惟", "爱士惟", "爱士惟",
             "华为", "华为", "上能"],
    "功率": ["6KW三相", "8KW单相", "8KW单相",
             "50KW三相", "50KW三相", "50KW三相"],
    "物料编号": ["AB002001", "AA002219", "AA002219",
                 "AB001347", "AB001347", "AB001653"],
    "物料名称": [
        "组串式逆变器_6kW_天合原装专用(16A/16A)",
        "组串式逆变器_8kW_天合原装专用(20A/20A)",
        "组串式逆变器_8kW_天合原装专用(20A/20A)",
        "组串式逆变器_50kW_4路_三相_天合原装专用(40A/40A)",
        "组串式逆变器_50kW_4路_三相_天合原装专用(40A/40A)",
        "组串式逆变器_50kW_天合原装专用(4*40A)",
    ],
    "可用库存": [20.0, 0.0, 1.0, 27.0, 59.0, 30.0],
    "备注": [None, None, None, None, None, None],
    "价格排序": [0.0, 102.0, 102.0, 5.0, 5.0, 8.0],
})


class TestCalculateInverterRange(unittest.TestCase):
    """测试 calculate_inverter_range"""

    def test_basic_calculation(self):
        """基本计算：572kW，已有100kW，比例1.1~1.2"""
        need_min, need_max, (total_min, total_max) = calculate_inverter_range(
            component_power=572, existing_power=100,
            ratio_min=1.1, ratio_max=1.2
        )
        self.assertAlmostEqual(need_min, 476.67 - 100, places=1)
        self.assertAlmostEqual(need_max, 520.00 - 100, places=1)

    def test_existing_exceeds_need(self):
        """已有逆变器足够时需新增为0"""
        need_min, need_max, _ = calculate_inverter_range(
            component_power=100, existing_power=100
        )
        self.assertEqual(need_min, 0)
        self.assertEqual(need_max, 0)

    def test_no_existing(self):
        """没有已有逆变器"""
        need_min, need_max, (total_min, total_max) = calculate_inverter_range(
            component_power=100, existing_power=0
        )
        self.assertAlmostEqual(need_min, total_min)
        self.assertAlmostEqual(need_max, total_max)


class TestFindInverterCombinations(unittest.TestCase):
    """测试 find_inverter_combinations"""

    def setUp(self):
        self.inverters = MOCK_INVERTERS.copy()

    def test_finds_combinations(self):
        """找到满足目标功率的组合"""
        combos = find_inverter_combinations(
            self.inverters, target_power=50.0, tolerance=0.1,
            max_combinations=5, same_brand=True, stock_sufficient=True,
        )
        self.assertGreater(len(combos), 0)

    def test_all_items_have_stock(self):
        """所有返回方案库存充足"""
        combos = find_inverter_combinations(
            self.inverters, target_power=50.0, tolerance=0.1,
            max_combinations=5, same_brand=True, stock_sufficient=True,
        )
        for combo_data in combos:
            for item in combo_data['combo']:
                code, _, qty = item[0], item[1], item[2]
                stock_row = self.inverters[self.inverters['物料编号'] == code]
                if len(stock_row) > 0:
                    stock = stock_row['可用库存'].values[0]
                    self.assertGreaterEqual(stock, qty)

    def test_no_stock_returns_empty(self):
        """没有库存时返回空"""
        df_no_stock = self.inverters.copy()
        df_no_stock['可用库存'] = 0.0
        combos = find_inverter_combinations(
            df_no_stock, target_power=50.0, tolerance=0.1,
            max_combinations=5, same_brand=True, stock_sufficient=True,
        )
        self.assertEqual(len(combos), 0)

    def test_allow_insufficient(self):
        """允许库存不足时返回方案"""
        df_zero = self.inverters.copy()
        df_zero['可用库存'] = 0.0
        combos = find_inverter_combinations(
            df_zero, target_power=50.0, tolerance=0.1,
            max_combinations=5, same_brand=True, stock_sufficient=False,
        )
        self.assertGreater(len(combos), 0)

    def test_same_brand_preferred(self):
        """同品牌优先"""
        combos = find_inverter_combinations(
            self.inverters, target_power=50.0, tolerance=0.1,
            max_combinations=5, same_brand=True, stock_sufficient=False,
        )
        for combo_data in combos:
            self.assertTrue(combo_data['is_same_brand'])

    def test_max_combinations_limited(self):
        """限制最大组合数"""
        combos = find_inverter_combinations(
            self.inverters, target_power=50.0, tolerance=0.1,
            max_combinations=2, same_brand=False, stock_sufficient=False,
        )
        self.assertLessEqual(len(combos), 2)

    def test_power_fulfilled(self):
        """组合功率满足目标功率（容差内）"""
        target = 50.0
        tolerance = 0.1
        combos = find_inverter_combinations(
            self.inverters, target_power=target, tolerance=tolerance,
            max_combinations=5, same_brand=False, stock_sufficient=False,
        )
        for combo_data in combos:
            total = sum(p * q for _, p, q, _, _ in combo_data['combo'])
            self.assertAlmostEqual(total, target, delta=target * tolerance)


class TestFormatCombination(unittest.TestCase):
    """测试 format_combination"""

    def setUp(self):
        self.sample_combo = {
            'combo': [('AB001347', 50, 1, 5, '华为')],
            'brand': '华为',
            'is_same_brand': True,
        }

    def test_contains_total_power(self):
        """包含总功率"""
        result = format_combination(self.sample_combo)
        self.assertEqual(result['total_power'], 50)

    def test_contains_items(self):
        """包含物料明细"""
        result = format_combination(self.sample_combo)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['code'], 'AB001347')

    def test_json_serializable(self):
        """可序列化为JSON"""
        result = format_combination(self.sample_combo)
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)
        self.assertEqual(parsed['total_power'], 50)

    def test_mixed_brand(self):
        """混合品牌格式"""
        combo = {
            'combo': [('AB001347', 50, 1, 5, '华为')],
            'brand': '混合',
            'is_same_brand': False,
        }
        result = format_combination(combo)
        self.assertFalse(result['is_same_brand'])


if __name__ == "__main__":
    unittest.main()
