#!/usr/bin/env python3
"""inventory_query.py 的完整测试套件。

覆盖范围：
  1. 文件发现机制
  2. 数据加载与缓存
  3. 数据预处理（合并单元格前向填充、列重命名）
  4. 三种查询函数（组件/逆变器/并网箱）的参数组合
  5. 库存聚合（按物料编码汇总所有仓库）
  6. 格式化输出（按品牌分组、空结果）
  7. 数据完整性对比（主sheet vs 工作表1）
  8. Mock 数据的纯逻辑测试（不依赖真实Excel）
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

# ── 加入项目路径 ──────────────────────────────────────────
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from inventory_query import (  # noqa: E402
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
#  Mock 数据（模拟 load_inventory 前向填充后的输出）
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


# ═══════════════════════════════════════════════════════════
#  2. 数据加载与缓存
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
        """合并单元格被前向填充（关键预处理）"""
        df = self.data["组件"]
        non_null = df["物料编号"].notna()
        self.assertGreater(non_null.sum(), 0, "物料编号应有非空值")

        # 选中一个具体物料编号，检查它的所有行都被填充
        first_code = df.loc[non_null, "物料编号"].iloc[0]
        code_rows = df[df["物料编号"] == first_code]
        self.assertGreater(len(code_rows), 1,
                           f"物料 {first_code} 应分布在多个仓库行")

    def test_inverter_price_rank_renamed(self):
        """价格排序列被正确重命名"""
        df = self.data["逆变器"]
        # 原长列名应不存在
        self.assertNotIn("价格排序（数字越大则越贵）", df.columns)
        # 简短列名应存在
        self.assertIn("价格排序", df.columns)

    def test_single_sheet_loading(self):
        """指定 sheet_name 时只加载该工作表"""
        sheet_data = load_inventory(sheet_name="组件")
        self.assertIn("组件", sheet_data)
        self.assertNotIn("逆变器", sheet_data)
        self.assertNotIn("并网箱", sheet_data)


# ═══════════════════════════════════════════════════════════
#  3. 组件查询
# ═══════════════════════════════════════════════════════════

class TestQueryComponents(unittest.TestCase):
    """测试 query_components 的参数组合"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["组件"]

    def test_query_all(self):
        """无参数时返回全部组件，含关键列"""
        result = query_components(self.df)
        self.assertGreater(len(result), 0)
        for col in ["物料编号", "物料名称", "功率", "可用库存", "备注", "仓库名称"]:
            self.assertIn(col, result.columns)

    def test_query_by_power(self):
        """按功率筛选（如715W）"""
        result = query_components(self.df, power=715)
        self.assertGreater(len(result), 0)
        self.assertTrue(
            all("715" in str(p) for p in result["功率"]),
            "所有结果的功率都应包含'715'"
        )

    def test_query_non_existent_power(self):
        """查询不存在的功率返回空DataFrame"""
        result = query_components(self.df, power=99999)
        self.assertEqual(len(result), 0)

    def test_duplicate_materials_after_ffill(self):
        """前向填充后同一物料有多个仓库行"""
        result = query_components(self.df)
        counts = result["物料编号"].value_counts()
        multi = counts[counts > 1]
        self.assertGreater(len(multi), 0, "应有物料分布在多个仓库")


# ═══════════════════════════════════════════════════════════
#  4. 逆变器查询
# ═══════════════════════════════════════════════════════════

class TestQueryInverters(unittest.TestCase):
    """测试 query_inverters 的参数组合"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["逆变器"]

    def test_default_has_stock(self):
        """默认只显示有库存的逆变器"""
        result = query_inverters(self.df)
        self.assertGreater(len(result), 0)
        self.assertTrue(
            all(result["可用库存"].notna() & (result["可用库存"] > 0))
        )

    def test_has_stock_false(self):
        """has_stock=False 返回所有行（含无库存）"""
        result = query_inverters(self.df, has_stock=False)
        self.assertGreater(len(result), 0)

    def test_query_by_power_50kw(self):
        """按功率 50kW 筛选"""
        result = query_inverters(self.df, power=50)
        self.assertGreater(len(result), 0)
        self.assertTrue(all("50" in str(p) for p in result["功率"]))

    def test_query_by_brand_tianhe(self):
        """天合品牌筛选（物料名称含'天合原装专用'）"""
        result = query_inverters(self.df, brand="天合")
        self.assertGreater(len(result), 0)
        self.assertTrue(
            all("天合原装专用" in str(n) for n in result["物料名称"]),
            "天合品牌筛选应只返回天合原装专用物料"
        )

    def test_output_columns(self):
        """返回正确的列集合"""
        result = query_inverters(self.df)
        expected = {"厂家", "功率", "物料编号", "物料名称", "可用库存", "备注", "价格排序"}
        self.assertTrue(expected.issubset(set(result.columns)),
                        f"缺少列: {expected - set(result.columns)}")


# ═══════════════════════════════════════════════════════════
#  5. 并网箱查询
# ═══════════════════════════════════════════════════════════

class TestQueryBoxes(unittest.TestCase):
    """测试 query_boxes 的参数组合"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["并网箱"]

    def test_default_has_stock(self):
        """默认只显示有库存的并网箱"""
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
        self.assertTrue(all("标准" in str(t) for t in result["并网箱类型"]))

    def test_output_columns(self):
        """返回正确的列集合"""
        result = query_boxes(self.df)
        expected = {"并网箱类型", "功率", "物料编号", "物料名称", "可用库存", "备注", "仓库名称"}
        self.assertTrue(expected.issubset(set(result.columns)))


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
        self.assertLessEqual(len(agg), len(raw))
        self.assertEqual(agg["物料编号"].nunique(), len(agg),
                         "聚合后物料编号应唯一")

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

    def test_warehouse_distribution_has_content(self):
        """仓库分布列包含正确的仓库名和台数（修复后）"""
        agg = aggregate_stock(query_components(self.components))
        if len(agg) > 0 and "仓库分布" in agg.columns:
            non_empty = agg["仓库分布"].dropna()
            non_blank = non_empty[non_empty.str.strip() != ""]
            self.assertGreater(len(non_blank), 0,
                               "仓库分布应有非空内容（如'南宁仓(1115台)'）")
            self.assertTrue(
                any("台" in str(v) for v in non_blank),
                "仓库分布应包含'台'字样的库存明细"
            )


# ═══════════════════════════════════════════════════════════
#  7. 格式化输出
# ═══════════════════════════════════════════════════════════

class TestFormatInverter(unittest.TestCase):
    """测试 format_inverter_by_brand"""

    @classmethod
    def setUpClass(cls):
        cls.df = load_inventory()["逆变器"]

    def test_format_empty(self):
        """空DataFrame返回无结果提示"""
        result = format_inverter_by_brand(pd.DataFrame())
        self.assertIn("未找到", result)

    def test_format_contains_brand_grouping(self):
        """格式化结果含按品牌分组的标题"""
        result = query_inverters(self.df)
        formatted = format_inverter_by_brand(result)
        self.assertIn("按品牌分组", formatted)


# ═══════════════════════════════════════════════════════════
#  8. JSON / CLI 输出格式
# ═══════════════════════════════════════════════════════════

class TestOutputFormat(unittest.TestCase):
    """测试输出格式（JSON 序列化）"""

    @classmethod
    def setUpClass(cls):
        cls.components = load_inventory()["组件"]

    def test_json_serializable(self):
        """DataFrame 可转为 JSON"""
        comp = query_components(self.components, power=730)
        if len(comp) > 0:
            json_str = comp.to_json(orient="records", force_ascii=False)
            parsed = json.loads(json_str)
            self.assertIsInstance(parsed, list)
            self.assertGreater(len(parsed), 0)

    def test_json_contains_expected_fields(self):
        """JSON 记录含关键字段"""
        comp = query_components(self.components, power=730)
        if len(comp) > 0:
            json_str = comp.to_json(orient="records", force_ascii=False)
            records = json.loads(json_str)
            for key in ("物料编号", "物料名称", "可用库存"):
                self.assertIn(key, records[0])


# ═══════════════════════════════════════════════════════════
#  9. Mock 数据测试（不依赖真实Excel文件）
# ═══════════════════════════════════════════════════════════

class TestQueryWithMockData(unittest.TestCase):
    """纯逻辑测试：用 mock DataFrame 验证查询逻辑"""

    def setUp(self):
        # Mock 数据已模拟 load_inventory 的前向填充输出
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

    def test_mock_inverters_no_stock(self):
        """has_stock=False 包含库存为0或空的行"""
        result = query_inverters(self.inverters, has_stock=False)
        total = len(self.inverters)
        self.assertEqual(len(result), total, "has_stock=False 应返回所有行")

    def test_mock_boxes_standard_type(self):
        """按'标准'筛选并网箱类型"""
        result = query_boxes(self.boxes, box_type="标准")
        self.assertGreater(len(result), 0)
        self.assertTrue(all("标准" in str(t) for t in result["并网箱类型"]))

    def test_mock_aggregate_sum(self):
        """聚合后 6B001492 总库存 = 1115 + 0 + 7286 = 8401"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        self.assertIn("库存总量", agg.columns)
        m1 = agg[agg["物料编号"] == "6B001492"]
        if len(m1) > 0:
            self.assertAlmostEqual(m1["库存总量"].values[0], 1115 + 7286, delta=1)

    def test_mock_aggregate_zero_filtered(self):
        """聚合后库存总量 > 0"""
        # 6B001440 总库存 = 0 + 0 + 10 = 10 > 0，不会被过滤
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        self.assertTrue(all(agg["库存总量"] > 0))

    def test_mock_warehouse_distribution_content(self):
        """mock数据：仓库分布包含正确的仓库名和数量"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        self.assertIn("仓库分布", agg.columns)
        # 6B001492 有 南宁仓(1115台) 和 郑州仓(7286台)
        m1 = agg[agg["物料编号"] == "6B001492"]
        if len(m1) > 0:
            dist = str(m1["仓库分布"].values[0])
            self.assertIn("南宁仓", dist)
            self.assertIn("1115台", dist)
            self.assertIn("郑州仓", dist)
            self.assertIn("7286台", dist)

    def test_mock_boxes_has_stock(self):
        """并网箱 has_stock 过滤"""
        result = query_boxes(self.boxes, has_stock=True)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(result["可用库存"].notna() & (result["可用库存"] > 0)))

    def test_mock_format_empty_dataframe(self):
        """空DataFrame格式化"""
        result = format_inverter_by_brand(pd.DataFrame())
        self.assertIn("未找到", result)

    def test_mock_format_with_data(self):
        """有数据时格式化含品牌分组"""
        result = query_inverters(self.inverters, has_stock=False)
        formatted = format_inverter_by_brand(result)
        self.assertIn("按品牌分组", formatted)

    def test_mock_inverters_power_and_brand(self):
        """同时指定功率和品牌"""
        result = query_inverters(self.inverters, power=50, brand="天合")
        self.assertGreater(len(result), 0)
        self.assertTrue(all("50" in str(p) for p in result["功率"]))
        self.assertTrue(all("天合原装专用" in str(n) for n in result["物料名称"]))

    def test_mock_components_power_zero(self):
        """power=0 正确进行功率过滤（不匹配任何数据时返回空）"""
        result = query_components(self.components, power=0)
        self.assertEqual(len(result), 0,
                         "power=0 过滤后不应匹配任何组件")

    def test_mock_components_power_no_partial_match(self):
        """功率匹配不应误匹配子串（如 5 不应匹配 715W）"""
        result = query_components(self.components, power=5)
        self.assertEqual(len(result), 0,
                         "功率 5 不应匹配到 715W 或 730W")

    def test_mock_aggregate_extra_cols_alignment(self):
        """聚合后额外列（品牌、功率）应与物料编号正确对齐"""
        raw = query_components(self.components)
        agg = aggregate_stock(raw)
        # 6B001492 的物料名称应包含 730W
        m1 = agg[agg["物料编号"] == "6B001492"]
        if len(m1) > 0:
            self.assertIn("730W", str(m1["物料名称"].values[0]))

    def test_mock_inverters_power_no_partial(self):
        """逆变器功率 5 不应匹配 50KW"""
        result = query_inverters(self.inverters, power=5, has_stock=False)
        self.assertEqual(len(result), 0,
                         "功率 5 不应匹配到 50KW 的数据")


# ═══════════════════════════════════════════════════════════
#  10. 数据审计与差异分析
# ═══════════════════════════════════════════════════════════

class TestDataAudit(unittest.TestCase):
    """数据审计：对比主sheet（组件/逆变器/并网箱）与工作表1的差异。

    这些用例输出审计信息辅助排查，不阻断 CI 流程。
    """

    @classmethod
    def setUpClass(cls):
        cls.file_path = _find_latest_inventory_file()
        cls.data = load_inventory()
        cls.flat = pd.read_excel(cls.file_path, sheet_name="工作表1",
                                 engine="calamine")

    def _cross_ref(self, main_df, flat_type):
        """返回主sheet 与 工作表1 的物料编号交叉引用结果"""
        main_codes = set(main_df["物料编号"].dropna().unique())
        flat_codes = set(
            self.flat[self.flat["物料类型"] == flat_type]["物料编号"].unique()
        )
        return {
            "main_count": len(main_codes),
            "flat_count": len(flat_codes),
            "missing_in_flat": main_codes - flat_codes,
            "only_in_flat": flat_codes - main_codes,
        }

    def test_audit_components(self):
        """审计组件物料覆盖差异"""
        r = self._cross_ref(self.data["组件"], "组件")
        print(f"\n  [审计-组件] 主sheet={r['main_count']}个, "
              f"工作表1={r['flat_count']}个, "
              f"仅在工作表1中={len(r['only_in_flat'])}个")
        if r["missing_in_flat"]:
            print(f"  [审计-组件] 主sheet特有(不在工作表1): {r['missing_in_flat']}")

    def test_audit_inverters(self):
        """审计逆变器物料覆盖差异"""
        r = self._cross_ref(self.data["逆变器"], "逆变器")
        print(f"\n  [审计-逆变器] 主sheet={r['main_count']}个, "
              f"工作表1={r['flat_count']}个, "
              f"仅在工作表1中={len(r['only_in_flat'])}个")
        if r["missing_in_flat"]:
            print(f"  [审计-逆变器] 主sheet特有: {r['missing_in_flat']}")

    def test_audit_boxes(self):
        """审计并网箱物料覆盖差异"""
        r = self._cross_ref(self.data["并网箱"], "配电柜")
        print(f"\n  [审计-并网箱] 主sheet={r['main_count']}个, "
              f"工作表1(配电柜)={r['flat_count']}个")

    def test_audit_flat_sheet_zero_stock(self):
        """工作表1中组件库存为0的比例"""
        flat_comp = self.flat[self.flat["物料类型"] == "组件"]
        zero = (flat_comp["可用库存"] == 0).sum()
        neg = (flat_comp["可用库存"] < 0).sum()
        print(f"\n  [审计-工作表1] 组件: {len(flat_comp)}行, "
              f"零库存={zero}({zero/len(flat_comp)*100:.1f}%), "
              f"负库存={neg}")

    def test_audit_main_sheet_data_types(self):
        """主sheet各列的NaN分布"""
        for sheet in ["组件", "逆变器", "并网箱"]:
            df = self.data[sheet]
            null_pct = df.isna().mean().mul(100).round(1)
            high_null = null_pct[null_pct > 50]
            info = ", ".join(f"{c}={v}%" for c, v in high_null.items())
            print(f"\n  [NaN-{sheet}] NaN>50%列: {info}" if len(high_null) > 0
                  else f"\n  [NaN-{sheet}] 无NaN>50%的列")


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

def print_summary(test_result):
    total = test_result.testsRun
    failures = len(test_result.failures)
    errors = len(test_result.errors)
    passed = total - failures - errors
    print("\n" + "=" * 60)
    print(f"  测试结果汇总")
    print("=" * 60)
    print(f"  总计: {total}  ✅ 通过: {passed}  "
          f"{'❌ 失败: ' + str(failures) if failures else ''}"
          f"{'⚠️  错误: ' + str(errors) if errors else ''}")
    if failures:
        print("\n  失败用例:")
        for test, _ in test_result.failures:
            print(f"    - {test.id()}")
    if errors:
        print("\n  错误:")
        for test, _ in test_result.errors:
            print(f"    - {test.id()}")
    print("=" * 60)
    return failures + errors


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

    result = unittest.TestResult()
    suite.run(result)

    print("\n" + "─" * 60)
    print("  测试状态")
    print("─" * 60)
    exit_code = print_summary(result)
    sys.exit(exit_code)
   
   
    