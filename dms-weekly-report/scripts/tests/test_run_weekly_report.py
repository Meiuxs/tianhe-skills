#!/usr/bin/env python3
"""单元测试：dms_browser + bom_parser + excel_generator 纯函数（兼容 v3 架构）。"""

from __future__ import annotations

import logging
import re
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# ==================== Mock 外部依赖 ====================

mock_playwright = types.ModuleType("playwright")
mock_playwright.async_api = types.ModuleType("playwright.async_api")
class MockPlaywrightTimeout(Exception):
    pass
mock_playwright.async_api.TimeoutError = MockPlaywrightTimeout
mock_playwright.async_api.async_playwright = None
mock_playwright.async_api.Page = type("Page", (), {})
mock_playwright.async_api.BrowserContext = type("BrowserContext", (), {})
mock_playwright.async_api.Response = type("Response", (), {})

mock_playwright_impl = types.ModuleType("playwright._impl")
mock_playwright_impl._errors = types.ModuleType("playwright._impl._errors")
mock_playwright_impl._errors.TargetClosedError = type("TargetClosedError", (Exception,), {})
mock_playwright_impl._errors.TimeoutError = MockPlaywrightTimeout

mock_openpyxl = types.ModuleType("openpyxl")
mock_openpyxl.worksheet = types.ModuleType("openpyxl.worksheet")
mock_openpyxl.worksheet.datavalidation = types.ModuleType("openpyxl.worksheet.datavalidation")
mock_openpyxl.worksheet.datavalidation.DataValidation = lambda **kw: type(
    "DV", (), {"prompt": "", "promptTitle": "", "add": lambda s, c: None}
)()
mock_openpyxl.styles = types.ModuleType("openpyxl.styles")
mock_openpyxl.styles.Side = lambda *a, **kw: object()
mock_openpyxl.styles.Alignment = lambda *a, **kw: object()
mock_openpyxl.styles.Border = lambda *a, **kw: object()
mock_openpyxl.styles.Font = lambda *a, **kw: object()
mock_openpyxl.styles.PatternFill = lambda *a, **kw: object()
mock_openpyxl.utils = types.ModuleType("openpyxl.utils")
mock_openpyxl.utils.get_column_letter = lambda i: chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)

from collections import defaultdict

class MockCell:
    font = None
    fill = None
    border = None
    alignment = None
    value = None
    number_format = None

class MockWorksheet:
    title = ""
    max_row = 0

    def __init__(self):
        self.column_dimensions = defaultdict(lambda: type("D", (), {"width": None, "hidden": False})())
        self.row_dimensions = defaultdict(lambda: type("D", (), {"height": None})())

    def cell(self, row, column, value=None):
        return MockCell()

    def __getitem__(self, key):
        return MockCell()

    def merge_cells(self, *args, **kwargs):
        pass

    def iter_rows(self, min_row=1, max_row=None, max_col=None, values_only=False):
        return iter([])


class MockWorkbook:
    def __init__(self):
        self.sheetnames = []
        self.active = MockWorksheet()

    def create_sheet(self, name):
        return MockWorksheet()

    def save(self, path):
        pass

    def add_data_validation(self, dv):
        pass


mock_openpyxl.Workbook = MockWorkbook
mock_openpyxl.load_workbook = lambda f: MockWorkbook()

# Save originals before mocking (restored at end of file)
_saved_sys_modules = {}
for _k in ("dms_credentials", "_compat", "playwright", "playwright.async_api",
           "playwright._impl", "playwright._impl._errors", "openpyxl", "openpyxl.styles"):
    if _k in sys.modules:
        _saved_sys_modules[_k] = sys.modules[_k]

sys.modules["playwright"] = mock_playwright
sys.modules["playwright.async_api"] = mock_playwright.async_api
sys.modules["playwright._impl"] = mock_playwright_impl
sys.modules["playwright._impl._errors"] = mock_playwright_impl._errors
sys.modules["openpyxl"] = mock_openpyxl
sys.modules["openpyxl.styles"] = mock_openpyxl.styles
sys.modules["_compat"] = types.ModuleType("_compat")

mock_creds = types.ModuleType("dms_credentials")
mock_creds.get_credentials = lambda on_source=None: ("test@test.com", "password123")
mock_creds.source_label = lambda s: "mock"
sys.modules["dms_credentials"] = mock_creds

# 不模拟 column_definitions，使用实际模块
# 这样可以避免模拟模块中变量名不匹配的问题

# ==================== 导入 core 模块 ====================

from core.dms_browser import (
    FlowRecord, TableProcessResult,
    is_on_login_page, get_week_range,
    retry_async,
)
from core.html_parser import extract_from_html, split_agent
from core.bom_parser import BOMItem, extract_power, extract_capacity
from core.excel_generator import (
    generate_excel,
    _update_summary_sheet, _fill_date_helper_column,
    _create_date_query_sheet_v2, _create_report_dashboard,
)


# ==================== 测试：工具函数 ====================


class TestIsOnLoginPage:
    def test_login_domain(self):
        assert is_on_login_page("https://iauth.trinapower.com/login") is True
        assert is_on_login_page("https://iauth.trinapower.com/oauth") is True

    def test_non_login_domain(self):
        assert is_on_login_page("https://dms-admin.trinapower.com") is False
        assert is_on_login_page("https://example.com") is False

    def test_empty_url(self):
        assert is_on_login_page("") is False


class TestGetWeekRange:
    def test_returns_tuple_of_two_strings(self):
        start, end = get_week_range(0)
        assert isinstance(start, str)
        assert isinstance(end, str)
        assert re.match(r"\d{4}-\d{2}-\d{2}", start)
        assert re.match(r"\d{4}-\d{2}-\d{2}", end)

    def test_start_is_monday(self):
        start, _ = get_week_range(0)
        dt = datetime.strptime(start, "%Y-%m-%d")
        assert dt.weekday() == 0

    def test_last_week_start_is_monday(self):
        start, _ = get_week_range(1)
        dt = datetime.strptime(start, "%Y-%m-%d")
        assert dt.weekday() == 0

    def test_two_weeks_ago(self):
        start, end = get_week_range(2)
        assert start < end


class TestExtractFromHtml:
    def test_direct_match(self):
        html = '<th>项目名称:</th><td>天合光能项目</td>'
        assert extract_from_html(html, "项目名称") == "天合光能项目"

    def test_nested_match(self):
        html = '<th>项目名称:</th><th><div>天合光能项目</div></th>'
        assert extract_from_html(html, "项目名称") == "天合光能项目"

    def test_not_found(self):
        html = '<th>其他字段:</th><td>值</td>'
        assert extract_from_html(html, "不存在的字段") == "--"

    def test_label_with_colon(self):
        html = '<th>省公司:</th><td>江苏</td>'
        assert extract_from_html(html, "省公司") == "江苏"

    def test_colon_in_label(self):
        html = '<th>瓦单价(元/瓦):</th><td>1.25</td>'
        assert extract_from_html(html, "瓦单价(元/瓦)") == "1.25"

    def test_empty_html(self):
        assert extract_from_html("", "字段") == "--"


class TestSplitAgent:
    def test_code_and_name(self):
        assert split_agent("AG001 天合代理商") == ("AG001", "天合代理商")

    def test_code_only(self):
        assert split_agent("AG001") == ("AG001", "--")

    def test_empty(self):
        assert split_agent("") == ("--", "--")
        assert split_agent("--") == ("--", "--")

    def test_multi_word_name(self):
        assert split_agent("AG002 天合光能有限公司") == ("AG002", "天合光能有限公司")


class TestExtractPower:
    def test_kW_direct(self):
        assert extract_power("销售组件_550kW_单晶") == 550.0

    def test_w_to_kw_conversion(self):
        val = extract_power("销售组件_500W_单晶")
        assert val is not None and abs(val - 0.5) < 0.001

    def test_no_match(self):
        assert extract_power("电缆_10mm2") is None

    def test_decimal_power(self):
        val = extract_power("逆变器_33.3kW_三相")
        assert val is not None and abs(val - 33.3) < 0.01

    def test_case_insensitive(self):
        assert extract_power("逆变器 50KW") == 50.0
        assert extract_power("逆变器 50kW") == 50.0
        assert extract_power("逆变器 50kw") == 50.0


class TestExtractCapacity:
    def test_kWh_direct(self):
        val = extract_capacity("电池_9.8kWh_储能")
        assert val is not None and abs(val - 9.8) < 0.01

    def test_wh_to_kwh_conversion(self):
        val = extract_capacity("电池_9800_Wh_")
        assert val is not None and abs(val - 9.8) < 0.01

    def test_no_match(self):
        assert extract_capacity("组件_415W") is None

    def test_decimal_capacity(self):
        val = extract_capacity("电池_13.5kWh")
        assert val is not None and abs(val - 13.5) < 0.01

    def test_case_insensitive_capacity(self):
        assert extract_capacity("电池 10kwh") == 10.0
        assert extract_capacity("电池 10kWh") == 10.0


class TestCalcModulePower:
    def test_single_module(self):
        from core.bom_parser import calc_module_power
        items = [BOMItem("M1", "销售组件_415W", 240, "块")]
        assert calc_module_power(items) == 99.6

    def test_no_module(self):
        from core.bom_parser import calc_module_power
        items = [BOMItem("I1", "逆变器_50kW", 1, "套")]
        assert calc_module_power(items) == 0.0

    def test_empty(self):
        from core.bom_parser import calc_module_power
        assert calc_module_power([]) == 0.0

    def test_mixed_items(self):
        from core.bom_parser import calc_module_power
        items = [BOMItem("M1", "销售组件_415W", 240, "块"),
                 BOMItem("I1", "逆变器_50kW", 1, "套")]
        assert calc_module_power(items) == 99.6

    def test_component_in_name(self):
        from core.bom_parser import calc_module_power
        items = [BOMItem("M1", "组件_415W", 100, "块")]
        power = calc_module_power(items)
        assert power == 41.5


class TestCalcInverterPower:
    def test_single_inverter(self):
        from core.bom_parser import calc_inverter_power
        items = [BOMItem("I1", "逆变器_50kW", 1, "套")]
        assert calc_inverter_power(items) == 50.0

    def test_no_inverter(self):
        from core.bom_parser import calc_inverter_power
        items = [BOMItem("M1", "组件_415W", 240, "块")]
        assert calc_inverter_power(items) == 0.0

    def test_empty(self):
        from core.bom_parser import calc_inverter_power
        assert calc_inverter_power([]) == 0.0


class TestCalcBatteryCapacity:
    def test_single_battery(self):
        from core.bom_parser import calc_battery_capacity
        items = [BOMItem("B1", "电池_9.8kWh", 10, "组")]
        assert calc_battery_capacity(items) == 98.0

    def test_storage_battery(self):
        from core.bom_parser import calc_battery_capacity
        items = [BOMItem("B1", "储能系统_9.8kWh", 5, "组")]
        assert calc_battery_capacity(items) == 49.0

    def test_no_battery(self):
        from core.bom_parser import calc_battery_capacity
        items = [BOMItem("M1", "组件_415W", 240, "块")]
        assert calc_battery_capacity(items) == 0.0

    def test_empty(self):
        from core.bom_parser import calc_battery_capacity
        assert calc_battery_capacity([]) == 0.0


class TestBuildRemark:
    def test_inverter_only(self):
        from core.bom_parser import build_remark
        items = [BOMItem("I1", "光储逆变器", 1, "套")]
        assert "光储逆变器" in build_remark(items)

    def test_grid_cabinet(self):
        from core.bom_parser import build_remark
        items = [BOMItem("C1", "并网柜", 1, "套")]
        assert "有并网柜" in build_remark(items)

    def test_grid_box_without_cabinet(self):
        from core.bom_parser import build_remark
        items = [BOMItem("B1", "并网箱", 1, "套")]
        assert "有并网箱" in build_remark(items)

    def test_grid_box_ignored_when_cabinet_present(self):
        from core.bom_parser import build_remark
        items = [BOMItem("B1", "并网箱", 1, "套"),
                 BOMItem("C1", "并网柜", 1, "套")]
        remark = build_remark(items)
        assert "有并网柜" in remark
        assert "有并网箱" not in remark

    def test_dc_cable(self):
        from core.bom_parser import build_remark
        items = [BOMItem("D1", "直流电缆", 100, "米")]
        assert "有直流线" in build_remark(items)

    def test_no_remark(self):
        from core.bom_parser import build_remark
        items = [BOMItem("A1", "安装架", 100, "套")]
        assert build_remark(items) == "无"

    def test_empty(self):
        from core.bom_parser import build_remark
        assert build_remark([]) == "无"

    def test_multiple_remarks(self):
        from core.bom_parser import build_remark
        items = [BOMItem("I1", "光储逆变器", 1, "套"),
                 BOMItem("C1", "并网柜", 1, "套")]
        remark = build_remark(items)
        assert ";" in remark


class TestTableProcessResult:
    def test_default_values(self):
        t = TableProcessResult()
        assert t.flow_ids == []
        assert t.seen_ids == set()
        assert t.skipped_invalid == 0

    def test_mutation_isolation(self):
        t1 = TableProcessResult()
        t2 = TableProcessResult()
        t1.flow_ids.append("A")
        assert len(t2.flow_ids) == 0


class TestDedupLogic:
    def test_dedup_behavior(self):
        from core.excel_generator import _build_rows_data
        records = [
            FlowRecord(flow_id="111111111111111", project_name="A"),
            FlowRecord(flow_id="111111111111111", project_name="A"),
            FlowRecord(flow_id="222222222222222", project_name="B"),
        ]
        rows = _build_rows_data(records)
        assert len(rows) == 3


class TestRetryAsync:
    def test_success_first_try(self):
        import asyncio
        call_count = [0]

        @retry_async(max_retries=3)
        async def succeed():
            call_count[0] += 1
            return "ok"

        result = asyncio.run(succeed())
        assert result == "ok"
        assert call_count[0] == 1

    def test_retry_then_succeed(self):
        import asyncio
        call_count = [0]

        @retry_async(max_retries=3)
        async def eventually_succeed():
            call_count[0] += 1
            if call_count[0] < 2:
                raise OSError("网络错误")
            return "ok"

        result = asyncio.run(eventually_succeed())
        assert result == "ok"
        assert call_count[0] == 2

    def test_exhaust_retries(self):
        import asyncio
        call_count = [0]

        @retry_async(max_retries=2)
        async def always_fail():
            call_count[0] += 1
            raise OSError("连接超时")

        with pytest.raises(OSError):
            asyncio.run(always_fail())
        assert call_count[0] == 2


class TestRunFlowIdsEmpty:
    """测试 run() 中 flow_ids 为空时提前返回的逻辑（第 206 行）。"""

    @pytest.mark.asyncio
    async def test_empty_flow_ids_returns_early(self, caplog):
        """filter_and_get_flow_ids 返回空列表时，run() 应提前返回，不执行后续步骤。"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from run_weekly_report import run

        # 使用简单对象替代 MagicMock，避免 await 问题
        args = type("Args", (), {
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
            "weeks": 0,
            "workers": 2,
            "headless": True,
            "output_dir": None,
            "verbose": False,
            "stats_only": False,
            "input_xlsx": None,
            "include_invalid": True,
        })()

        # 构造 filter_result 返回空 flow_ids
        mock_filter_result = type("FilterResult", (), {"flow_ids": [], "skipped_invalid": 0})()

        # 追踪后续步骤是否被调用
        extract_called = False

        async def fake_filter(*a, **kw):
            return mock_filter_result

        async def fake_extract(*a, **kw):
            nonlocal extract_called
            extract_called = True
            return []

        with patch("run_weekly_report._find_headless_shell", return_value="/fake/path"), \
             patch("run_weekly_report.async_playwright") as mock_pw, \
             patch("run_weekly_report.filter_and_get_flow_ids", side_effect=fake_filter), \
             patch("run_weekly_report.extract_all_parallel", side_effect=fake_extract):

            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_page.url = "https://dms-admin.trinapower.com"
            mock_context.new_page = AsyncMock(return_value=mock_page)

            # 正确 mock async_playwright
            pw_instance = AsyncMock()
            pw_instance.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
            mock_pw.return_value = pw_instance
            mock_pw.__aenter__ = AsyncMock(return_value=pw_instance)
            mock_pw.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.INFO):
                await run(args)

            assert "宽范围内无已办询价记录" in caplog.text
            assert not extract_called, "flow_ids 为空时不应调用 extract_all_parallel"

    @pytest.mark.asyncio
    async def test_non_empty_flow_ids_continues(self, caplog):
        """filter_and_get_flow_ids 返回非空列表时，run() 应继续执行后续步骤。"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from run_weekly_report import run

        # 使用简单对象替代 MagicMock，避免 await 问题
        args = type("Args", (), {
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
            "weeks": 0,
            "workers": 2,
            "headless": True,
            "output_dir": None,
            "verbose": False,
            "stats_only": False,
            "input_xlsx": None,
            "include_invalid": True,
        })()

        # 构造 filter_result 返回非空 flow_ids，添加 flow_status_map 属性
        mock_filter_result = type("FilterResult", (), {
            "flow_ids": ["FLOW001", "FLOW002"],
            "skipped_invalid": 0,
            "flow_status_map": {"FLOW001": "审批通过", "FLOW002": "进行中"},
        })()

        extract_called = False

        async def fake_filter(*a, **kw):
            return mock_filter_result

        async def fake_extract(*a, **kw):
            nonlocal extract_called
            extract_called = True
            return []

        with patch("run_weekly_report._find_headless_shell", return_value="/fake/path"), \
             patch("run_weekly_report.async_playwright") as mock_pw, \
             patch("run_weekly_report.filter_and_get_flow_ids", side_effect=fake_filter), \
             patch("run_weekly_report.extract_all_parallel", side_effect=fake_extract):

            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_page.url = "https://dms-admin.trinapower.com"
            mock_context.new_page = AsyncMock(return_value=mock_page)

            # 正确 mock async_playwright
            pw_instance = AsyncMock()
            pw_instance.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
            mock_pw.return_value = pw_instance
            mock_pw.__aenter__ = AsyncMock(return_value=pw_instance)
            mock_pw.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.INFO):
                await run(args)

            assert extract_called, "flow_ids 非空时应调用 extract_all_parallel"


class TestFilterRecordsByRegionTechTime:
    """测试按区域技术审批时间过滤记录的逻辑。"""

    def test_keeps_records_within_range(self):
        from run_weekly_report import _filter_records_by_region_tech_time
        records = [
            FlowRecord(flow_id="111111111111111", region_tech_approval_time="2026-06-03 10:00:00"),
            FlowRecord(flow_id="222222222222222", region_tech_approval_time="2026-06-05 10:00:00"),
        ]
        result = _filter_records_by_region_tech_time(records, "2026-06-01", "2026-06-07")
        assert len(result) == 2

    def test_drops_records_outside_range(self):
        from run_weekly_report import _filter_records_by_region_tech_time
        records = [
            FlowRecord(flow_id="111111111111111", region_tech_approval_time="2026-05-20 10:00:00"),
            FlowRecord(flow_id="222222222222222", region_tech_approval_time="2026-06-03 10:00:00"),
        ]
        result = _filter_records_by_region_tech_time(records, "2026-06-01", "2026-06-07")
        assert len(result) == 1
        assert result[0].flow_id == "222222222222222"

    def test_drops_records_without_region_time(self):
        from run_weekly_report import _filter_records_by_region_tech_time
        records = [
            FlowRecord(flow_id="111111111111111", region_tech_approval_time="--"),
            FlowRecord(flow_id="222222222222222", region_tech_approval_time="2026-06-03 10:00:00"),
        ]
        result = _filter_records_by_region_tech_time(records, "2026-06-01", "2026-06-07")
        assert len(result) == 1
        assert result[0].flow_id == "222222222222222"

    def test_boundary_inclusive(self):
        from run_weekly_report import _filter_records_by_region_tech_time
        records = [
            FlowRecord(flow_id="111111111111111", region_tech_approval_time="2026-06-01 00:00:00"),
            FlowRecord(flow_id="222222222222222", region_tech_approval_time="2026-06-07 23:59:59"),
        ]
        result = _filter_records_by_region_tech_time(records, "2026-06-01", "2026-06-07")
        assert len(result) == 2


class TestRegionTechTimeInRange:
    """测试共享谓词 _region_tech_time_in_range。

    该谓词同时供完整模式（_filter_records_by_region_tech_time）与
    仅统计模式（stats_from_excel）复用，此处覆盖 Excel 行的原始字符串场景。
    """

    def test_in_range(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("2026-06-03 10:00:00", "2026-06-01", "2026-06-07") is True

    def test_before_range(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("2026-05-20 10:00:00", "2026-06-01", "2026-06-07") is False

    def test_after_range(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("2026-06-10 10:00:00", "2026-06-01", "2026-06-07") is False

    def test_boundary_inclusive(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("2026-06-01 00:00:00", "2026-06-01", "2026-06-07") is True
        assert _region_tech_time_in_range("2026-06-07 23:59:59", "2026-06-01", "2026-06-07") is True

    def test_placeholder_dash(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("--", "2026-06-01", "2026-06-07") is False

    def test_placeholder_na(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("无", "2026-06-01", "2026-06-07") is False

    def test_empty(self):
        from run_weekly_report import _region_tech_time_in_range
        assert _region_tech_time_in_range("", "2026-06-01", "2026-06-07") is False
        assert _region_tech_time_in_range(None, "2026-06-01", "2026-06-07") is False

    def test_unparsable(self):
        from run_weekly_report import _region_tech_time_in_range
        # 无法解析为 YYYY-MM-DD 的格式应返回 False
        assert _region_tech_time_in_range("2026/06/03", "2026-06-01", "2026-06-07") is False
        assert _region_tech_time_in_range("未知", "2026-06-01", "2026-06-07") is False


# ==================== Restore sys.modules after all tests ====================
for _k, _v in _saved_sys_modules.items():
    sys.modules[_k] = _v
for _k in ("dms_credentials", "_compat", "playwright", "playwright.async_api",
           "playwright._impl", "playwright._impl._errors", "openpyxl", "openpyxl.styles"):
    if _k not in _saved_sys_modules and _k in sys.modules:
        del sys.modules[_k]
