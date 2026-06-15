#!/usr/bin/env python3
"""inventory_orchestrator.py 测试套件（dms-inventory 版）。

覆盖范围：
  1. _parse_remark 备注解析
  2. _get_stock 库存获取
  3. _filter_by_remark 备注过滤（排除/警告/可用）
  4. _extract_power_num 功率数字提取
  5. _calc_dc_ac_ratio DC/AC 比计算
  6. _calc_existing_kw 已有设备总功率计算
  7. _serializable 类型转换
  8. run_analysis 主流程（Mock load_inventory）
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

try:
    import numpy as np
except ImportError:
    np = type('np', (), {'integer': int, 'floating': float, 'bool_': bool})()

from inventory_orchestrator import (
    _parse_remark,
    _get_stock,
    _filter_by_remark,
    _extract_power_num,
    _calc_dc_ac_ratio,
    _calc_existing_kw,
_serializable,
    run_analysis,
    REMARK_RULES,
)


# ═══════════════════════════════════════════════════════════
#  1. _parse_remark
# ═══════════════════════════════════════════════════════════

class TestParseRemark(unittest.TestCase):
    """测试 _parse_remark"""

    def test_none_remark(self):
        """None 返回 none 级别"""
        result = _parse_remark(None)
        self.assertEqual(result['level'], 'none')

    def test_empty_remark(self):
        """空字符串返回 none"""
        result = _parse_remark('')
        self.assertEqual(result['level'], 'none')

    def test_project_specific(self):
        """'项目专用' 返回 excluded"""
        result = _parse_remark('项目专用物料')
        self.assertEqual(result['level'], 'excluded')
        self.assertEqual(result['matched_rule'], '项目专用')

    def test_unlisted(self):
        """'未上架' 返回 excluded"""
        result = _parse_remark('未上架不可售')
        self.assertEqual(result['level'], 'excluded')

    def test_warning_original(self):
        """'原厂机' 返回 warning"""
        result = _parse_remark('原厂机，交期长')
        self.assertEqual(result['level'], 'warning')

    def test_warning_special_price(self):
        """'特价组件' 返回 warning"""
        result = _parse_remark('特价组件')
        self.assertEqual(result['level'], 'warning')

    def test_unknown_remark(self):
        """未匹配到规则的返回 unknown"""
        result = _parse_remark('自定义备注内容')
        self.assertEqual(result['level'], 'unknown')

    def test_normal_remark(self):
        """'常规备货' 返回 normal"""
        result = _parse_remark('常规备货')
        self.assertEqual(result['level'], 'normal')


# ═══════════════════════════════════════════════════════════
#  2. _get_stock
# ═══════════════════════════════════════════════════════════

class TestGetStock(unittest.TestCase):
    """测试 _get_stock"""

    def test_available_stock(self):
        """取 库存总量（优先于可用库存）"""
        row = {'可用库存': 100, '库存总量': 200}
        self.assertEqual(_get_stock(row), 200)

    def test_total_stock(self):
        """取 库存总量"""
        row = {'库存总量': 200}
        self.assertEqual(_get_stock(row), 200)

    def test_nan_stock(self):
        """NaN 返回 0"""
        row = {'可用库存': float('nan')}
        result = _get_stock(row)
        self.assertEqual(result, 0)

    def test_no_stock_col(self):
        """没有库存列返回 0"""
        row = {'foo': 'bar'}
        self.assertEqual(_get_stock(row), 0)


# ═══════════════════════════════════════════════════════════
#  3. _filter_by_remark
# ═══════════════════════════════════════════════════════════

class TestFilterByRemark(unittest.TestCase):
    """测试 _filter_by_remark"""

    def setUp(self):
        self.df = pd.DataFrame({
            '物料编号': ['A001', 'A002', 'A003', 'A004', 'A005'],
            '物料名称': ['物料1', '物料2', '物料3', '物料4', '物料5'],
            '备注': ['项目专用', '原厂机', '常规备货', '未上架', None],
            '可用库存': [100, 50, 200, 30, 80],
        })
        self.prefs = {
            'exclude_project_specific': True,
            'exclude_unlisted': True,
            'prefer_non_original': True,
        }

    def test_excluded_filtered(self):
        """排除项被过滤"""
        result = _filter_by_remark(self.df, self.prefs)
        excluded_codes = [e['code'] for e in result['excluded']]
        self.assertIn('A001', excluded_codes)
        self.assertIn('A004', excluded_codes)

    def test_warning_recorded(self):
        """警告级别被记录但不排除"""
        result = _filter_by_remark(self.df, self.prefs)
        warning_codes = [w['code'] for w in result['warnings']]
        self.assertIn('A002', warning_codes)
        # A002 应在 available 中
        avail_codes = result['available']['物料编号'].values.tolist()
        self.assertIn('A002', avail_codes)

    def test_available_contains_normal(self):
        """正常可用物料在 available 中"""
        result = _filter_by_remark(self.df, self.prefs)
        avail_codes = result['available']['物料编号'].values.tolist()
        self.assertIn('A003', avail_codes)
        self.assertIn('A005', avail_codes)

    def test_empty_df(self):
        """空 DataFrame"""
        result = _filter_by_remark(pd.DataFrame(), self.prefs)
        self.assertTrue(result['available'].empty)

    def test_exclude_turned_off(self):
        """排除开关关闭时不排除"""
        prefs = {k: False for k in self.prefs}
        result = _filter_by_remark(self.df, prefs)
        self.assertEqual(len(result['excluded']), 0)

    def test_original_excluded_regardless(self):
        """原厂机不管 prefer_non_original 都记录为 warning（不排除）"""
        prefs = {**self.prefs, 'prefer_non_original': False}
        result = _filter_by_remark(self.df, prefs)
        # A002（原厂机）仍在 available 中，同时记录 warning
        avail_codes = result['available']['物料编号'].values.tolist()
        self.assertIn('A002', avail_codes)
        warning_codes = [w['code'] for w in result['warnings']]
        self.assertIn('A002', warning_codes)

    def test_remark_not_in_columns(self):
        """没有备注列时全部可用"""
        df = pd.DataFrame({'物料编号': ['A001'], '可用库存': [100]})
        result = _filter_by_remark(df, self.prefs)
        self.assertFalse(result['available'].empty)


# ═══════════════════════════════════════════════════════════
#  4. _extract_power_num
# ═══════════════════════════════════════════════════════════

class TestExtractPowerNum(unittest.TestCase):
    """测试 _extract_power_num"""

    def test_w_suffix(self):
        """"715W" → 715"""
        self.assertEqual(_extract_power_num("715W"), 715)

    def test_kw_suffix(self):
        """"50KW三相" → 50"""
        self.assertEqual(_extract_power_num("50KW三相"), 50)

    def test_plain_number(self):
        """纯数字字符串 → 数字"""
        self.assertEqual(_extract_power_num("730"), 730)

    def test_nan(self):
        """NaN → 0"""
        self.assertEqual(_extract_power_num(float('nan')), 0)

    def test_no_number(self):
        """无数字 → 0"""
        self.assertEqual(_extract_power_num("无功率"), 0)


# ═══════════════════════════════════════════════════════════
#  5. _calc_dc_ac_ratio
# ═══════════════════════════════════════════════════════════

class TestCalcDcAcRatio(unittest.TestCase):
    """测试 _calc_dc_ac_ratio"""

    def test_positive(self):
        """正常值"""
        self.assertAlmostEqual(_calc_dc_ac_ratio(100, 80), 1.25)

    def test_zero_inverter(self):
        """逆变器为0时返回0"""
        self.assertEqual(_calc_dc_ac_ratio(100, 0), 0)


# ═══════════════════════════════════════════════════════════
#  6. _calc_existing_kw
# ═══════════════════════════════════════════════════════════

class TestCalcExistingKw(unittest.TestCase):
    """测试 _calc_existing_kw"""

    def test_power_kw(self):
        """power_kw 格式"""
        items = [{'power_kw': 40, 'qty': 2}]
        self.assertEqual(_calc_existing_kw(items), 80)

    def test_power_plus_unit(self):
        """power + unit 格式"""
        items = [{'power': 40, 'unit': 'kW', 'qty': 1}]
        self.assertEqual(_calc_existing_kw(items), 40)

    def test_power_as_string(self):
        """power 为带单位字符串"""
        items = [{'power': '40kW', 'qty': 2}]
        self.assertEqual(_calc_existing_kw(items), 80)

    def test_mixed_items(self):
        """多种设备混合"""
        items = [
            {'power_kw': 40, 'qty': 2},
            {'power_kw': 30, 'qty': 1},
        ]
        self.assertEqual(_calc_existing_kw(items), 110)

    def test_empty_list(self):
        """空列表"""
        self.assertEqual(_calc_existing_kw([]), 0)


# ═══════════════════════════════════════════════════════════
#  7. _serializable
# ═══════════════════════════════════════════════════════════

class TestSerializable(unittest.TestCase):
    """测试 _serializable"""

    def test_pandas_integer(self):
        """numpy integer → int"""
        val = np.int64(42)
        self.assertEqual(_serializable(val), 42)

    def test_numpy_float(self):
        """numpy float → float"""
        val = np.float64(3.14)
        self.assertIsInstance(_serializable(val), float)

    def test_numpy_bool(self):
        """numpy bool → bool"""
        val = np.bool_(True)
        self.assertIsInstance(_serializable(val), bool)

    def test_plain_types(self):
        """普通类型原样返回"""
        self.assertEqual(_serializable(42), 42)
        self.assertEqual(_serializable(3.14), 3.14)
        self.assertEqual(_serializable("hello"), "hello")


# ═══════════════════════════════════════════════════════════
#  8. run_analysis — 纯组件需求
# ═══════════════════════════════════════════════════════════

class TestRunAnalysisComponentsOnly(unittest.TestCase):
    """测试 run_analysis（Mock load_inventory，仅组件）"""

    @patch('inventory_orchestrator.load_inventory')
    def test_components_sufficient(self, mock_load):
        """组件库存充足"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492', '6B001492'],
                '物料名称': ['组件A', '组件A'],
                '功率': ['730W', '730W'],
                '可用库存': [500.0, 500.0],
                '仓库名称': ['南宁仓', '郑州仓'],
            }),
            '逆变器': pd.DataFrame(),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {
                'components': {'power': 730, 'qty': 800},
            },
            'preferences': {},
        }
        result = run_analysis(params)
        self.assertEqual(result['summary']['component_status'], 'sufficient')

    @patch('inventory_orchestrator.load_inventory')
    def test_components_insufficient(self, mock_load):
        """组件库存不足"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'],
                '功率': ['730W'],
                '可用库存': [100.0],
                '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame(),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {
                'components': {'power': 730, 'qty': 800},
            },
            'preferences': {},
        }
        result = run_analysis(params)
        self.assertEqual(result['summary']['component_status'], 'insufficient')

    @patch('inventory_orchestrator.load_inventory')
    def test_components_no_stock(self, mock_load):
        """组件无库存"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'],
                '功率': ['730W'],
                '可用库存': [0.0],
                '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame(),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {
                'components': {'power': 730, 'qty': 800},
            },
            'preferences': {},
        }
        result = run_analysis(params)
        self.assertEqual(result['summary']['component_status'], 'no_stock')

    @patch('inventory_orchestrator.load_inventory')
    def test_no_component_req(self, mock_load):
        """无组件需求"""
        mock_load.return_value = {
            '组件': pd.DataFrame(),
            '逆变器': pd.DataFrame(),
            '并网箱': pd.DataFrame(),
        }
        params = {'requirements': {}, 'preferences': {}}
        result = run_analysis(params)
        self.assertIsNotNone(result)

    def test_output_structure(self):
        """输出结构包含所有顶层字段"""
        # 使用 mock 避免读文件
        with patch('inventory_orchestrator.load_inventory') as mock_load:
            mock_load.return_value = {
                '组件': pd.DataFrame(),
                '逆变器': pd.DataFrame(),
                '并网箱': pd.DataFrame(),
            }
            result = run_analysis({'requirements': {}, 'preferences': {}})
            for key in ('version', 'summary', 'components', 'inverters', 'combiner_boxes'):
                self.assertIn(key, result)


# ═══════════════════════════════════════════════════════════
#  9. run_analysis — prefer_material 物料偏好
# ═══════════════════════════════════════════════════════════

class TestRunAnalysisPreferMaterial(unittest.TestCase):
    """测试 prefer_material 物料偏好参数"""

    @patch('inventory_orchestrator.load_inventory')
    def test_prefer_material_matches(self, mock_load):
        """prefer_material 匹配到对应物料"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'],
                '功率': ['730W'],
                '可用库存': [800.0],
                '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame({
                '物料编号': ['INV001', 'INV002', 'INV003'],
                '物料名称': ['天合原装专用40kW', '天合原装专用40kW', '普通40kW'],
                '功率': ['40kW', '40kW', '40kW'],
                '可用库存': [5.0, 3.0, 10.0],
                '厂家': ['上能', '华为', '上能'],
                '价格排序': [1, 2, 3],
                '备注': [None, None, None],
            }),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {
                'components': {'power': 730, 'qty': 800},
                'inverters': {},
            },
            'preferences': {
                'prefer_material': '天合原装专用',
            },
        }
        result = run_analysis(params)
        inverters = result['inverters']
        # prefer_material 前置过滤，只保留匹配的物料进入品牌分组
        self.assertIn('brands', inverters)
        brand_names = [b['name'] for b in inverters['brands']]
        self.assertIn('上能', brand_names)
        self.assertIn('华为', brand_names)
        # 上能品牌只包含天合原装专用物料（普通物料被过滤掉）
        shangneng = next(b for b in inverters['brands'] if b['name'] == '上能')
        shangneng_codes = [m['code'] for m in shangneng['models']]
        self.assertIn('INV001', shangneng_codes)
        self.assertNotIn('INV003', shangneng_codes)
        # 华为品牌包含天合原装专用物料
        huawei = next(b for b in inverters['brands'] if b['name'] == '华为')
        huawei_codes = [m['code'] for m in huawei['models']]
        self.assertIn('INV002', huawei_codes)
        # preferred_material 记录过滤信息
        self.assertIn('preferred_material', inverters)
        self.assertEqual(inverters['preferred_material']['keyword'], '天合原装专用')
        self.assertEqual(inverters['preferred_material']['total_count'], 2)

    @patch('inventory_orchestrator.load_inventory')
    def test_prefer_material_no_match(self, mock_load):
        """prefer_material 无匹配时不产生 preferred_material 区块"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'],
                '功率': ['730W'],
                '可用库存': [800.0],
                '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame({
                '物料编号': ['INV001'],
                '物料名称': ['普通40kW'],
                '功率': ['40kW'],
                '可用库存': [10.0],
                '厂家': ['上能'],
                '价格排序': [1],
                '备注': [None],
            }),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {
                'components': {'power': 730, 'qty': 800},
                'inverters': {},
            },
            'preferences': {
                'prefer_material': '天合原装专用',
            },
        }
        result = run_analysis(params)
        inverters = result['inverters']
        # 无匹配物料时，不应产生 preferred_material 区块
        self.assertNotIn('preferred_material', inverters)

    @patch('inventory_orchestrator.load_inventory')
    def test_prefer_material_not_set(self, mock_load):
        """不设置 prefer_material 时无 preferred_material 区块"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'],
                '功率': ['730W'],
                '可用库存': [800.0],
                '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame({
                '物料编号': ['INV001'],
                '物料名称': ['天合原装专用40kW'],
                '功率': ['40kW'],
                '可用库存': [5.0],
                '厂家': ['上能'],
                '价格排序': [1],
                '备注': [None],
            }),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {
                'components': {'power': 730, 'qty': 800},
            },
            'preferences': {},
        }
        result = run_analysis(params)
        inverters = result['inverters']
        self.assertNotIn('preferred_material', inverters)


# ═══════════════════════════════════════════════════════════
#  10. run_analysis — 组合逻辑测试
# ═══════════════════════════════════════════════════════════

class TestRunAnalysisCombinations(unittest.TestCase):
    """测试逆变器组合生成逻辑"""

    @patch('inventory_orchestrator.load_inventory')
    def test_same_brand_preferred_over_mixed(self, mock_load):
        """同品牌有方案时应直接输出，不尝试混合品牌"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'], '功率': ['730W'],
                '可用库存': [800.0], '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame({
                '物料编号': ['INV001', 'INV002', 'INV003'],
                '物料名称': ['品牌A 50kW', '品牌A 40kW', '品牌B 40kW'],
                '功率': ['50kW', '40kW', '40kW'],
                '可用库存': [10.0, 10.0, 10.0],
                '厂家': ['品牌A', '品牌A', '品牌B'],
                '价格排序': [1, 2, 3],
                '备注': [None, None, None],
            }),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {'components': {'power': 730, 'qty': 800}, 'inverters': {}},
            'preferences': {},
        }
        result = run_analysis(params)
        combos = result['inverters'].get('combinations', [])
        # 品牌A有足够的库存出方案 → 应返回组合
        self.assertTrue(len(combos) > 0, "同品牌应有方案输出")
        # 所有组合应为同品牌（is_same_brand=True）
        for combo in combos:
            self.assertTrue(
                combo.get('is_same_brand', False),
                f"组合 {combo.get('plan_label')} 应为同品牌",
            )

    @patch('inventory_orchestrator.load_inventory')
    def test_combos_sorted_by_units_then_price(self, mock_load):
        """组合排序按 total_units ASC → total_price_rank ASC"""
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['6B001492'],
                '物料名称': ['组件A'], '功率': ['730W'],
                '可用库存': [800.0], '仓库名称': ['南宁仓'],
            }),
            '逆变器': pd.DataFrame({
                '物料编号': ['INV001', 'INV002'],
                '物料名称': ['品牌A 50kW', '品牌A 40kW'],
                '功率': ['50kW', '40kW'],
                '可用库存': [20.0, 20.0],
                '厂家': ['品牌A', '品牌A'],
                '价格排序': [1, 2],
                '备注': [None, None],
            }),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {'components': {'power': 730, 'qty': 800}, 'inverters': {}},
            'preferences': {},
        }
        result = run_analysis(params)
        combos = result['inverters'].get('combinations', [])
        for i in range(len(combos) - 1):
            u1 = combos[i]['total_units']
            u2 = combos[i + 1]['total_units']
            p1 = combos[i]['total_price_rank']
            p2 = combos[i + 1]['total_price_rank']
            self.assertTrue(
                u1 < u2 or (u1 == u2 and p1 <= p2),
                f"方案{i+1}(台数{u1},价格{p1}) 应在方案{i+2}(台数{u2},价格{p2})之前",
            )


class TestJsonSerialization(unittest.TestCase):
    """测试 JSON 序列化不因 numpy 类型失败"""

    @patch('inventory_orchestrator.load_inventory')
    def test_numpy_types_in_output(self, mock_load):
        """输出中即使有 numpy 类型也不应抛出 TypeError"""
        import numpy as np
        mock_load.return_value = {
            '组件': pd.DataFrame({
                '物料编号': ['TEST001'],
                '物料名称': ['测试组件'],
                '功率': ['715W'],
                '可用库存': [np.int64(100)],
                '仓库名称': ['测试仓'],
            }),
            '逆变器': pd.DataFrame(),
            '并网箱': pd.DataFrame(),
        }
        params = {
            'requirements': {'components': {'power': 715, 'qty': 100}},
            'preferences': {},
        }
        result = run_analysis(params)
        # 不应抛出 TypeError
        output = json.dumps(result, ensure_ascii=False, indent=2)
        self.assertIsInstance(output, str)


if __name__ == "__main__":
    unittest.main()
