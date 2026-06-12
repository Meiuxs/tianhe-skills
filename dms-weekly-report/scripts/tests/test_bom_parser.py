"""BOM 解析模块的单元测试。

测试功率、容量等参数从物料名称中的提取和计算。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.bom_parser import (
    BOMItem,
    extract_power,
    extract_capacity,
    calc_module_power,
    calc_inverter_power,
    calc_battery_capacity,
    build_remark,
)
from tests.fixtures import (
    BOM_MODULE, BOM_INVERTER, BOM_BATTERY,
    SAMPLE_BOM_ITEMS, compare_floats,
)


class TestPowerExtraction(unittest.TestCase):
    """功率值提取测试。"""

    def test_extract_power_from_module_name(self):
        """从组件名称中提取功率。"""
        # 模块: Trina Module TSM-415DE09RS 415W
        # 应该提取 415W = 0.415 kW
        power = extract_power("Trina Module TSM-415DE09RS 415W")
        self.assertIsNotNone(power)
        self.assertTrue(compare_floats(power, 0.415))

    def test_extract_power_from_inverter_name(self):
        """从逆变器名称中提取功率。"""
        # 逆变器: Trina Inverter TSM50KTL-US 50KW
        # 应该提取 50KW = 50 kW
        power = extract_power("Trina Inverter TSM50KTL-US 50KW")
        self.assertIsNotNone(power)
        self.assertTrue(compare_floats(power, 50.0))

    def test_extract_power_case_insensitive(self):
        """功率提取应该不分大小写。"""
        p1 = extract_power("逆变器 50kw")
        p2 = extract_power("逆变器 50KW")
        p3 = extract_power("逆变器 50Kw")
        self.assertIsNotNone(p1)
        self.assertEqual(p1, p2)
        self.assertEqual(p2, p3)

    def test_extract_power_with_underscore_format(self):
        """支持下划线分隔格式。"""
        # SUN2000-50KTL_50_kW_
        power = extract_power("SUN2000-50KTL_50_kW_")
        self.assertIsNotNone(power)
        self.assertTrue(compare_floats(power, 50.0))

    def test_extract_power_with_watts_unit(self):
        """支持 W 单位。"""
        power = extract_power("Inverter_50000_W_")
        self.assertIsNotNone(power)
        self.assertTrue(compare_floats(power, 50.0))

    def test_extract_power_inverter_underscore_separated(self):
        """逆变器名称以下划线分段，kW 前不是下划线。"""
        # 组串式逆变器_SG110CX_P2H-CN-110kW_9路/2*40+7*20A
        # 注意：110kW 后跟着 _，之前 \b 在此处不匹配
        name = "组串式逆变器_SG110CX_P2H-CN-110kW_9路/2*40+7*20A_三相_180-1000V_380/400V_NB/T32004_IP66_RS485/4G(选配)_风冷"
        power = extract_power(name)
        self.assertIsNotNone(power)
        self.assertTrue(compare_floats(power, 110.0))

    def test_extract_power_kw_after_dash(self):
        """kW 在横杠之后。"""
        power = extract_power("SG33CX-P2-CN-33kW")
        self.assertIsNotNone(power)
        self.assertTrue(compare_floats(power, 33.0))


class TestCapacityExtraction(unittest.TestCase):
    """容量值提取测试。"""

    def test_extract_capacity_from_battery_name(self):
        """从电池名称中提取容量。"""
        # LG Chem RESU10H 9.8kWh
        capacity = extract_capacity("LG Chem RESU10H 9.8kWh")
        self.assertIsNotNone(capacity)
        self.assertTrue(compare_floats(capacity, 9.8))

    def test_extract_capacity_case_insensitive(self):
        """支持不同的容量单位大小写。"""
        c1 = extract_capacity("电池 10kwh")
        c2 = extract_capacity("电池 10kWh")
        c3 = extract_capacity("电池 10KWH")
        self.assertIsNotNone(c1)
        self.assertEqual(c1, c2)
        self.assertEqual(c2, c3)

    def test_extract_capacity_with_wh_unit(self):
        """支持 Wh 单位。"""
        capacity = extract_capacity("Battery_9800_Wh_")
        self.assertIsNotNone(capacity)
        self.assertTrue(compare_floats(capacity, 9.8))

    def test_extract_capacity_none_for_non_battery(self):
        """非电池物料返回 None"""
        capacity = extract_capacity("组件 415W")
        self.assertIsNone(capacity)


class TestPowerCalculation(unittest.TestCase):
    """功率计算测试。"""

    def test_calc_module_power(self):
        """计算组件总功率 = 单块功率 × 数量。"""
        # 415W × 240 = 99.6 kW
        items = [BOMItem(code="M1", name="销售组件 Trina 415W", qty=240, unit="块")]
        power = calc_module_power(items)
        self.assertTrue(compare_floats(power, 99.6))

    def test_calc_inverter_power(self):
        """计算逆变器总功率。"""
        # 50KW × 1 = 50 kW
        items = [BOMItem(code="I1", name="Inverter 50KW", qty=1, unit="套")]
        power = calc_inverter_power(items)
        self.assertTrue(compare_floats(power, 50.0))

    def test_calc_battery_capacity(self):
        """计算电池总容量。"""
        # 9.8 kWh × 10 = 98 kWh
        items = [BOMItem(code="B1", name="Battery 9.8kWh", qty=10, unit="组")]
        capacity = calc_battery_capacity(items)
        self.assertTrue(compare_floats(capacity, 98.0))

    def test_calc_power_with_empty_list(self):
        """空 BOM 列表应该返回 0"""
        self.assertEqual(calc_module_power([]), 0.0)
        self.assertEqual(calc_inverter_power([]), 0.0)
        self.assertEqual(calc_battery_capacity([]), 0.0)

    def test_calc_ignores_non_matching_items(self):
        """计算时忽略不匹配的物料。"""
        items = [
            BOMItem(code="M1", name="组件 415W", qty=100, unit="块"),
            BOMItem(code="X1", name="安装架", qty=100, unit="套"),  # 不匹配
            BOMItem(code="M2", name="组件 415W", qty=140, unit="块"),
        ]
        power = calc_module_power(items)
        # 415W × (100+140) = 99.6 kW
        self.assertTrue(compare_floats(power, 99.6))

    def test_calc_with_multiple_inverters(self):
        """支持多个逆变器。"""
        items = [
            BOMItem(code="I1", name="逆变器 50kW", qty=1, unit="套"),
            BOMItem(code="I2", name="逆变器 30kW", qty=2, unit="套"),
        ]
        power = calc_inverter_power(items)
        # 50 + 30×2 = 110 kW
        self.assertTrue(compare_floats(power, 110.0))


class TestRemarkBuilding(unittest.TestCase):
    """备注信息构建测试。"""

    def test_build_remark_with_hybrid_inverter(self):
        """包含光储逆变器时应该在备注中体现。"""
        items = [BOMItem(code="I1", name="光储逆变器 50kW", qty=1, unit="套")]
        remark = build_remark(items)
        self.assertIn("光储逆变器", remark)

    def test_build_remark_with_grid_cabinet(self):
        """包含并网柜。"""
        items = [BOMItem(code="C1", name="并网柜", qty=1, unit="套")]
        remark = build_remark(items)
        self.assertIn("有并网柜", remark)

    def test_build_remark_with_grid_box(self):
        """包含并网箱。"""
        items = [BOMItem(code="B1", name="并网箱", qty=1, unit="套")]
        remark = build_remark(items)
        self.assertIn("有并网箱", remark)

    def test_build_remark_cabinet_over_box(self):
        """并网柜优先于并网箱。"""
        items = [
            BOMItem(code="B1", name="并网箱", qty=1, unit="套"),
            BOMItem(code="C1", name="并网柜", qty=1, unit="套"),
        ]
        remark = build_remark(items)
        self.assertIn("有并网柜", remark)
        self.assertNotIn("有并网箱", remark)

    def test_build_remark_with_dc_cable(self):
        """包含直流线。"""
        items = [BOMItem(code="D1", name="直流电缆", qty=100, unit="米")]
        remark = build_remark(items)
        self.assertIn("有直流线", remark)

    def test_build_remark_multiple_features(self):
        """多个特性分号分隔。"""
        items = [
            BOMItem(code="I1", name="光储逆变器", qty=1, unit="套"),
            BOMItem(code="C1", name="并网柜", qty=1, unit="套"),
            BOMItem(code="D1", name="直流线", qty=100, unit="米"),
        ]
        remark = build_remark(items)
        parts = remark.split("; ")
        self.assertGreaterEqual(len(parts), 2)

    def test_build_remark_empty_list(self):
        """空列表返回默认值。"""
        remark = build_remark([])
        self.assertEqual(remark, "无")

    def test_build_remark_no_matching_items(self):
        """没有匹配的特性。"""
        items = [
            BOMItem(code="M1", name="组件 415W", qty=100, unit="块"),
            BOMItem(code="A1", name="安装架", qty=100, unit="套"),
        ]
        remark = build_remark(items)
        self.assertEqual(remark, "无")

    def test_build_remark_deduplicates(self):
        """重复的特性应该去重。"""
        items = [
            BOMItem(code="D1", name="直流电缆", qty=50, unit="米"),
            BOMItem(code="D2", name="直流线", qty=50, unit="米"),
        ]
        remark = build_remark(items)
        # 应该只有一个"有直流线"
        self.assertEqual(remark.count("有直流线"), 1)


class TestEdgeCases(unittest.TestCase):
    """边界情况和异常测试。"""

    def test_extract_power_empty_string(self):
        """空字符串返回 None"""
        self.assertIsNone(extract_power(""))

    def test_extract_power_none_input(self):
        """None 输入返回 None"""
        self.assertIsNone(extract_power(None))

    def test_extract_capacity_no_unit(self):
        """名称中只有数字没有单位。"""
        result = extract_capacity("电池 9.8")
        self.assertIsNone(result)

    def test_calc_with_zero_quantity(self):
        """数量为 0 的物料。"""
        items = [BOMItem(code="M1", name="组件 415W", qty=0, unit="块")]
        power = calc_module_power(items)
        self.assertEqual(power, 0.0)

    def test_calc_with_float_quantity(self):
        """数量为浮点数。"""
        items = [BOMItem(code="M1", name="组件 415W", qty=1.5, unit="套")]
        power = calc_module_power(items)
        self.assertTrue(compare_floats(power, 0.6225))

    def test_extract_power_very_large_number(self):
        """非常大的数字。"""
        power = extract_power("Inverter 1000kW")
        self.assertEqual(power, 1000.0)

    def test_rounding(self):
        """测试四舍五入。"""
        items = [BOMItem(code="M1", name="组件 333W", qty=100, unit="块")]
        power = calc_module_power(items)
        # 333W × 100 = 33.3 kW，精确到小数点后 2 位
        self.assertEqual(power, 33.30)


if __name__ == "__main__":
    unittest.main()

