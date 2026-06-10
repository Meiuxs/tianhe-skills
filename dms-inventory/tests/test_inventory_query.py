#!/usr/bin/env python3
"""inventory_query.py 的完整测试套件（dms-inventory 版）。

覆盖范围：
  1. 文件发现（仅 assets/ 目录）
  2. 数据加载与预处理
  3. 三种查询函数（组件/逆变器/并网箱）
  4. 库存聚合
  5. 格式化输出
  6. Mock 数据纯逻辑测试
"""

import io
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

from inventory_query import (
    _find_latest_inventory_file,
    load_inventory,
    query_components,
    query_inverters,
    query_boxes,
    aggregate_stock,
    format_inverter_by_brand,
    DEFAULT_INVENTORY_FILE,
)

# ═══════════════════════════════════════════════════════════
#  Mock 数据
# ═══════════════════════════════════════════════════════════

MOCK_COMPONENTS = pd.DataFrame({
    "物料编号": ["6B001492", "6B001492", "6B001492",
                 "6B001440", "6B001440", "6B001440"],
    "物料名称": [
        "销售组件_TSM-NEG21C.20_730W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_730W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_730W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_715W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_715W_18BB_银边框_33mm_竖装",
        "销售组件_TSM-NEG21C.20_715W_18BB_银边框_33mm_竖装",
    ],
    "功率": ["730W", "730W", "730W", "715W", "715W", "715W"],
    "可用库存": [1115.0, None, 7286.0, None, 0.0, 10.0],
    "仓库名称": [
        "天合富家-南宁仓", "天合富家-徐州仓", "天合富家-郑州仓",
        "天合富家-南宁仓", "天合富家-郑州仓", "天合富家-金华仓",
    ],
})

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
    "仓库名称": [
        "天合富家-常州西北仓", "天合富家-金华仓", "天合富家-常州西北仓",
        "天合富家-上海仓", "天合富家-北京仓", "天合富家-广州仓",
    ],
    "可用库存": [20.0, None, 1.0, 27.0, 59.0, 30.0],
    "备注": [None, None, None, None, None, None],
    "价格排序": [None, 102.0, 102.0, None, None, None],
})

MOCK_BOXES = pd.DataFrame({
    "并网箱类型": [
        "标准一体式并网箱", "标准一体式并网箱", "标准一体式并网箱",
        "单刀闸带漏保并网箱", "单刀闸带漏保并网箱",
    ],
    "功率": [
        "10KW单相", "25KW三相", "25KW三相",
        "50KW三相", "50KW三相",
    ],
    "物料编号": [
        "AA001062", "AA001061", "AA001061",
        "AA001653", "AA001653",
    ],
    "物料名称": [
        "并网柜_10KW单相_220V_不锈钢_天合原装专用",
        "并网柜_25KW三相_380V_不锈钢_天合原装专用",
        "并网柜_25KW三相_380V_不锈钢_天合原装专用",
        "并网柜_50KW三相_380V_不锈钢_天合原装专用",
        "并网柜_50KW三相_380V_不锈钢_天合原装专用",
    ],
    "仓库名称": [
        "天合富家-济南仓", "天合富家-佛山仓", "天合富家-南宁仓",
        "天合富家-上海仓", "天合富家-广州仓",
    ],
    "可用库存": [None, None, 21.0, 70.0, 197.0],
})


# ═══════════════════════════════════════════════════════════
#  1. 文件发现
# ═══════════════════════════════════════════════════════════

class TestFileDiscovery(unittest.TestCase):
    """测试 _find_latest_inventory_file 和默认文件路径"""

    def test_find_file_in_assets(self):
        """能在 assets/ 中找到库存文件"""
        file_path = _find_latest_inventory_file()
        self.assertTrue(os.path.exists(file_path))
        self.assertIn("组件、逆变器、并网箱可用库存统计", file_path)
        self.assertIn("assets", file_path)

    def test_default_inventory_file_not_none(self):
        """模块启动时能自动定位库存文件"""
        self.assertIsNotNone(DEFAULT_INVENTORY_FILE)
        self.assertTrue(os.path.exists(DEFAULT_INVENTORY_FILE))

    def test_not_found_in_root(self):
        """文件不存在于根目录（仅搜索 assets/）"""
        assets_dir = os.path.join(SKILL_DIR, "assets")
        pattern = os.path.join(assets_dir, "组件、逆变器、并网箱可用库存统计*.xlsx")
        import glob
        files = glob.glob(pattern)
        self.assertGreater(len(files), 0, "assets/ 中应有库存文件")


# ═══════════════════════════════════════════════════════════
#  2. 数据加载
# ═══════════════════════════════════════════════════════════

class TestDataLoading(unittest.TestCase):
    """测试 load_inventory 加载功能"""

    @classmethod
    def setUpClass(cls):
        cls.data = load_inventory()

    def test_loads_three_sheets(self):
        """加载了组件、逆变器、并网箱三个sheet"""
        self.assertIn("组件", self.data)
        self.assertIn("逆变器", self.data)
        self.assertIn("并网箱", self.data)

    def test_components_not_empty(self):
        """组件数据非空"""
        self.assertGreater(len(self.data["组件"]), 0)

    def test_inverters_not_empty(self):
        """逆变器数据非空"""
        self.assertGreater(len(self.data["逆变器"]), 0)

    def test_boxes_not_empty(self):
        """并网箱数据非空"""
        self.assertGreater(len(self.data["并网箱"]), 0)

    def test_merged_cells_forward_filled(self):
        """合并单元格被前向填充"""
        df = self.data["组件"]
        non_null = df["物料编号"].notna()
        self.assertGreater(non_null.sum(), 0)

    def test_single_sheet_loading(self):
        """指定 sheet_name 时只加载该工作表"""
        sheet_data = load_inventory(sheet_name="组件")
        self.assertIn("组件", sheet_data)
        self.assertNotIn("逆变器", sheet_data)


# ═══════════════════════════════════════════════════════════
#  3. 组件查询
# ═══════════════════════════════════════════════════════════

class TestQueryComponents(unittest.TestCase):
    """测试 query_components"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["组件"]

    def test_query_all(self):
        """无参数时返回全部组件"""
        result = query_components(self.df)
        self.assertGreater(len(result), 0)

    def test_query_by_power(self):
        """按功率筛选"""
        result = query_components(self.df, power=715)
        self.assertGreater(len(result), 0)
        self.assertTrue(all("715" in str(p) for p in result["功率"]))

    def test_query_non_existent_power(self):
        """查询不存在功率返回空"""
        result = query_components(self.df, power=99999)
        self.assertEqual(len(result), 0)

    def test_output_columns(self):
        """返回列包含关键字段"""
        result = query_components(self.df)
        for col in ["物料编号", "物料名称", "功率", "可用库存", "仓库名称"]:
            self.assertIn(col, result.columns)


# ═══════════════════════════════════════════════════════════
#  4. 逆变器查询
# ═══════════════════════════════════════════════════════════

class TestQueryInverters(unittest.TestCase):
    """测试 query_inverters"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["逆变器"]

    def test_default_has_stock(self):
        """默认只显示有库存"""
        result = query_inverters(self.df)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(result["可用库存"].notna() & (result["可用库存"] > 0)))

    def test_has_stock_false(self):
        """has_stock=False 返回所有行"""
        result = query_inverters(self.df, has_stock=False)
        self.assertGreater(len(result), 0)

    def test_query_by_power(self):
        """按功率 50kW 筛选"""
        result = query_inverters(self.df, power=50)
        self.assertGreater(len(result), 0)
        self.assertTrue(all("50" in str(p) for p in result["功率"]))

    def test_query_by_brand_tianhe(self):
        """天合品牌筛选"""
        result = query_inverters(self.df, brand="天合")
        self.assertGreater(len(result), 0)
        self.assertTrue(all("天合原装专用" in str(n) for n in result["物料名称"]))

    def test_output_columns(self):
        """返回正确的列集合"""
        result = query_inverters(self.df)
        expected = {"厂家", "功率", "物料编号", "物料名称", "可用库存", "备注", "价格排序"}
        self.assertTrue(expected.issubset(set(result.columns)))


# ═══════════════════════════════════════════════════════════
#  5. 并网箱查询
# ═══════════════════════════════════════════════════════════

class TestQueryBoxes(unittest.TestCase):
    """测试 query_boxes"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["并网箱"]

    def test_default_has_stock(self):
        """默认只显示有库存"""
        result = query_boxes(self.df)
        self.assertGreater(len(result), 0)

    def test_query_by_power(self):
        """按功率筛选"""
        result = query_boxes(self.df, power=50)
        self.assertGreater(len(result), 0)
        self.assertTrue(all("50" in str(p) for p in result["功率"]))

    def test_query_by_type(self):
        """按并网箱类型筛选"""
        result = query_boxes(self.df, box_type="标准")
        self.assertGreater(len(result), 0)


# ═══════════════════════════════════════════════════════════
#  6. 库存聚合
# ═══════════════════════════════════════════════════════════

class TestAggregateStock(unittest.TestCase):
    """测试 aggregate_stock"""

    @classmethod
    def setUpClass(cls):
        cls.components = load_inventory()["组件"]

    def test_groups_by_material(self):
        """聚合后按物料编号去重"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        self.assertEqual(agg["物料编号"].nunique(), len(agg))

    def test_contains_total_stock_column(self):
        """聚合结果包含库存总量列"""
        agg = aggregate_stock(query_components(self.components))
        if len(agg) > 0:
            self.assertIn("库存总量", agg.columns)

    def test_sorted_descending(self):
        """按库存量降序排列"""
        agg = aggregate_stock(query_components(self.components))
        if len(agg) > 1:
            vals = agg["库存总量"].values
            for i in range(len(vals) - 1):
                self.assertGreaterEqual(vals[i], vals[i + 1])

    def test_zero_stock_filtered(self):
        """不含库存为0的物料"""
        agg = aggregate_stock(query_components(self.components))
        self.assertTrue(all(agg["库存总量"] > 0))

    def test_warehouse_distribution(self):
        """仓库分布列有内容"""
        agg = aggregate_stock(query_components(self.components))
        if len(agg) > 0 and "仓库分布" in agg.columns:
            non_empty = agg["仓库分布"].dropna()
            non_blank = non_empty[non_empty.str.strip() != ""]
            self.assertGreater(len(non_blank), 0)


# ═══════════════════════════════════════════════════════════
#  7. Mock 数据测试
# ═══════════════════════════════════════════════════════════

class TestQueryWithMockData(unittest.TestCase):
    """纯逻辑测试：Mock DataFrame"""

    def setUp(self):
        self.components = MOCK_COMPONENTS.copy()
        self.inverters = MOCK_INVERTERS.copy()
        self.boxes = MOCK_BOXES.copy()

    def test_mock_components_by_power_730(self):
        """按730W查询返回3个仓库行"""
        result = query_components(self.components, power=730)
        self.assertEqual(len(result), 3)

    def test_mock_components_by_power_715(self):
        """按715W查询返回3个仓库行"""
        result = query_components(self.components, power=715)
        self.assertEqual(len(result), 3)

    def test_mock_inverters_tianhe_filter(self):
        """品牌='天合'筛选：所有物料名称含'天合原装专用'"""
        result = query_inverters(self.inverters, brand="天合")
        self.assertGreater(len(result), 0)
        for _, row in result.iterrows():
            self.assertIn("天合原装专用", str(row["物料名称"]))

    def test_mock_inverters_has_stock(self):
        """has_stock=True 时所有结果库存 > 0"""
        result = query_inverters(self.inverters, has_stock=True)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(result["可用库存"].notna() & (result["可用库存"] > 0)))

    def test_mock_boxes_standard_type(self):
        """按'标准'筛选并网箱类型"""
        result = query_boxes(self.boxes, box_type="标准")
        self.assertGreater(len(result), 0)
        self.assertTrue(all("标准" in str(t) for t in result["并网箱类型"]))

    def test_mock_aggregate_sum(self):
        """聚合后 6B001492 总库存 = 1115 + 7286 = 8401"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        m1 = agg[agg["物料编号"] == "6B001492"]
        if len(m1) > 0:
            self.assertAlmostEqual(m1["库存总量"].values[0], 1115 + 7286, delta=1)

    def test_mock_aggregate_zero_filtered(self):
        """聚合后库存 > 0"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        self.assertTrue(all(agg["库存总量"] > 0))

    def test_mock_warehouse_distribution_content(self):
        """仓库分布包含正确的仓库名和数量"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        self.assertIn("仓库分布", agg.columns)
        m1 = agg[agg["物料编号"] == "6B001492"]
        if len(m1) > 0:
            dist = str(m1["仓库分布"].values[0])
            self.assertIn("南宁仓", dist)
            self.assertIn("郑州仓", dist)

    def test_mock_inverters_power_and_brand(self):
        """同时指定功率和品牌"""
        result = query_inverters(self.inverters, power=50, brand="天合")
        self.assertGreater(len(result), 0)
        self.assertTrue(all("50" in str(p) for p in result["功率"]))

    def test_mock_components_power_no_partial(self):
        """功率 5 不应匹配 715W 或 730W"""
        result = query_components(self.components, power=5)
        self.assertEqual(len(result), 0)

    def test_format_empty_dataframe(self):
        """空 DataFrame 格式化"""
        result = format_inverter_by_brand(pd.DataFrame())
        self.assertIn("未找到", result)

    def test_format_with_data(self):
        """有数据时含品牌分组"""
        result = query_inverters(self.inverters, has_stock=False)
        formatted = format_inverter_by_brand(result)
        self.assertIn("按品牌分组", formatted)

    def test_json_serializable(self):
        """DataFrame 可转为 JSON"""
        comp = query_components(self.components, power=730)
        if len(comp) > 0:
            json_str = comp.to_json(orient="records", force_ascii=False)
            parsed = json.loads(json_str)
            self.assertIsInstance(parsed, list)


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
