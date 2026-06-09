#!/usr/bin/env python3
"""单元测试：run_weekly_report.py 中不依赖 Playwright 的纯函数。"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 将被测试模块加入路径
sys.path.insert(0, str(Path(__file__).parent))

import pytest

# 直接导入需要测试的模块和函数
# 为了避免执行时触发 playwright/dms_credentials import，我们用 mock 的方式
# 好在 run_weekly_report.py 中大部分纯函数只依赖 re/dataclasses 等标准库

# 复制被测试的常量和函数到测试上下文
# 也可以直接 import，但 run_weekly_report.py 在 import 时会触发 playwright 导入
# 所以我们先 mock 掉外部依赖，再 import

# ==================== 工具：mock 外部依赖后 import ====================

import importlib.util
import types

# 先加载模块但不执行 import 语句中的第三方包
# 方案：创建一个 mock module，让 sys.modules 中有 playwright 的桩
mock_playwright = types.ModuleType("playwright")
mock_playwright.async_api = types.ModuleType("playwright.async_api")

class MockPlaywrightTimeout(Exception):
    pass

mock_playwright.async_api.TimeoutError = MockPlaywrightTimeout
mock_playwright.async_api.async_playwright = None

mock_playwright_impl = types.ModuleType("playwright._impl")
mock_playwright_impl._errors = types.ModuleType("playwright._impl._errors")
mock_playwright_impl._errors.TargetClosedError = type("TargetClosedError", (Exception,), {})
mock_playwright_impl._errors.TimeoutError = MockPlaywrightTimeout

mock_openpyxl = types.ModuleType("openpyxl")

class MockWorkbook:
    def __init__(self):
        self.active = MockWorksheet()
    def save(self, path):
        pass

from collections import defaultdict

class MockDimension:
    def __init__(self):
        self.width = None
        self.height = None

class MockWorksheet:
    title = ""
    max_row = 0

    def __init__(self):
        self.column_dimensions = defaultdict(MockDimension)
        self.row_dimensions = defaultdict(MockDimension)

    def cell(self, row, column, value=None):
        return MockCell()
    def __getitem__(self, key):
        return MockCell()

    def cell(self, row, column, value=None):
        return MockCell()
    def __getitem__(self, key):
        return MockCell()

class MockCell:
    font = None
    fill = None
    border = None
    alignment = None
    value = None

mock_openpyxl.Workbook = MockWorkbook
mock_openpyxl.load_workbook = lambda *a, **kw: MockWorkbook()

mock_openpyxl.styles = types.ModuleType("openpyxl.styles")
def mock_side(*a, **kw): return object()
def mock_alignment(*a, **kw): return object()
def mock_border(*a, **kw): return object()
def mock_font(*a, **kw): return object()
def mock_patternfill(*a, **kw): return object()
mock_openpyxl.styles.Side = mock_side
mock_openpyxl.styles.Alignment = mock_alignment
mock_openpyxl.styles.Border = mock_border
mock_openpyxl.styles.Font = mock_font
mock_openpyxl.styles.PatternFill = mock_patternfill

mock_openpyxl.utils = types.ModuleType("openpyxl.utils")
def mock_get_column_letter(i): return chr(64 + i)
mock_openpyxl.utils.get_column_letter = mock_get_column_letter

mock_compat = types.ModuleType("_compat")

mock_dms_creds = types.ModuleType("dms_credentials")
def _mock_get_credentials(**kwargs):
    return ("test@test.com", "password123")
def _mock_source_label(source):
    return "mock"
mock_dms_creds.get_credentials = _mock_get_credentials
mock_dms_creds.source_label = _mock_source_label

# 注册 mock
sys.modules["playwright"] = mock_playwright
sys.modules["playwright.async_api"] = mock_playwright.async_api
sys.modules["playwright._impl"] = mock_playwright_impl
sys.modules["playwright._impl._errors"] = mock_playwright_impl._errors
sys.modules["openpyxl"] = mock_openpyxl
sys.modules["openpyxl.styles"] = mock_openpyxl.styles
sys.modules["_compat"] = mock_compat
sys.modules["dms_credentials"] = mock_dms_creds

# 现在可以安全 import 被测试模块
# 注意：py_compile 已通过，但直接 import 可能还有问题，我们用 spec_from_file_location
spec = importlib.util.spec_from_file_location(
    "run_weekly_report",
    str(Path(__file__).parent / "run_weekly_report.py"),
)
report = importlib.util.module_from_spec(spec)
sys.modules["run_weekly_report"] = report  # 让 dataclass 解析能通过 sys.modules 查找到自身
spec.loader.exec_module(report)


# ==================== 测试：工具函数 ====================


class TestIsOnLoginPage:
    def test_login_domain(self):
        assert report.is_on_login_page("https://iauth.trinapower.com/login") is True
        assert report.is_on_login_page("https://iauth.trinapower.com/oauth") is True

    def test_non_login_domain(self):
        assert report.is_on_login_page("https://dms-admin.trinapower.com") is False
        assert report.is_on_login_page("https://example.com") is False

    def test_empty_url(self):
        assert report.is_on_login_page("") is False


class TestGetWeekRange:
    def test_returns_tuple_of_two_strings(self):
        start, end = report.get_week_range(0)
        assert isinstance(start, str)
        assert isinstance(end, str)
        assert re.match(r"\d{4}-\d{2}-\d{2}", start)
        assert re.match(r"\d{4}-\d{2}-\d{2}", end)

    def test_start_is_monday(self):
        start, _ = report.get_week_range(0)
        dt = datetime.strptime(start, "%Y-%m-%d")
        assert dt.weekday() == 0  # Monday

    def test_last_week_start_is_monday(self):
        start, _ = report.get_week_range(1)
        dt = datetime.strptime(start, "%Y-%m-%d")
        assert dt.weekday() == 0

    def test_two_weeks_ago(self):
        start, end = report.get_week_range(2)
        assert start < end


class TestExtractFromHtml:
    def test_direct_match(self):
        html = '<th>项目名称:</th><td>天合光能项目</td>'
        assert report._extract_from_html(html, "项目名称") == "天合光能项目"

    def test_nested_match(self):
        # 测试第二级回退匹配: label</th><th><div>value
        html = '<th>项目名称:</th><th><div>天合光能项目</div></th>'
        assert report._extract_from_html(html, "项目名称") == "天合光能项目"

    def test_not_found(self):
        html = '<th>其他字段:</th><td>值</td>'
        assert report._extract_from_html(html, "不存在的字段") == "--"

    def test_label_with_colon(self):
        html = '<th>省公司:</th><td>江苏</td>'
        assert report._extract_from_html(html, "省公司") == "江苏"

    def test_colon_in_label(self):
        """测试 label 本身含有冒号的情况（如 瓦单价(元/瓦):）。"""
        html = '<th>瓦单价(元/瓦):</th><td>1.25</td>'
        assert report._extract_from_html(html, "瓦单价(元/瓦)") == "1.25"

    def test_empty_html(self):
        assert report._extract_from_html("", "字段") == "--"


class TestSplitAgent:
    def test_code_and_name(self):
        assert report._split_agent("AG001 天合代理商") == ("AG001", "天合代理商")

    def test_code_only(self):
        assert report._split_agent("AG001") == ("AG001", "--")

    def test_empty(self):
        assert report._split_agent("") == ("--", "--")
        assert report._split_agent("--") == ("--", "--")

    def test_multi_word_name(self):
        assert report._split_agent("AG002 天合光能有限公司") == ("AG002", "天合光能有限公司")


class TestExtractPower:
    def test_kW_direct(self):
        assert report._extract_power("销售组件_550kW_单晶") == 550.0

    def test_w_to_kw_conversion(self):
        val = report._extract_power("销售组件_500W_单晶")
        assert val is not None and abs(val - 0.5) < 0.001

    def test_no_match(self):
        assert report._extract_power("电缆_10mm2") is None

    def test_decimal_power(self):
        val = report._extract_power("逆变器_33.3kW_三相")
        assert val is not None and abs(val - 33.3) < 0.01

    def test_case_insensitive(self):
        assert report._extract_power("组件_100Kw_") == 100.0


class TestExtractCapacity:
    def test_kWh_direct(self):
        assert report._extract_capacity("电池_100kWh_磷酸铁锂") == 100.0

    def test_wh_to_kwh_conversion(self):
        val = report._extract_capacity("电池_500Wh_")
        assert val is not None and abs(val - 0.5) < 0.001

    def test_no_match(self):
        assert report._extract_capacity("逆变器_33kW_") is None

    def test_decimal_capacity(self):
        val = report._extract_capacity("储能_50.5kWh_")
        assert val is not None and abs(val - 50.5) < 0.01


# ==================== 测试：BOM 计算类 ====================


def _make_item(code: str, name: str, qty: int | float = 1) -> report.BOMItem:
    return report.BOMItem(code=code, name=name, qty=qty, unit="台")


class TestCalcModulePower:
    def test_single_module(self):
        items = [_make_item("M01", "销售组件_550kW_单晶", 2)]
        assert isinstance(report._calc_module_power(items), float)
        assert report._calc_module_power(items) == 1100.0

    def test_no_module(self):
        items = [_make_item("I01", "逆变器_33kW_三相")]
        assert report._calc_module_power(items) == "无"

    def test_empty(self):
        assert report._calc_module_power([]) == "无"

    def test_mixed_items(self):
        items = [
            _make_item("M01", "销售组件_550kW_单晶", 2),
            _make_item("I01", "逆变器_33kW_三相", 1),
        ]
        assert report._calc_module_power(items) == 1100.0

    def test_component_in_name(self):
        items = [_make_item("M01", "组件_330W_单晶", 3)]
        val = report._calc_module_power(items)
        assert isinstance(val, float) and abs(val - 0.99) < 0.01


class TestCalcInverterPower:
    def test_single_inverter(self):
        items = [_make_item("I01", "逆变器_33kW_三相", 2)]
        assert report._calc_inverter_power(items) == 66.0

    def test_no_inverter(self):
        items = [_make_item("M01", "销售组件_550kW_单晶")]
        assert report._calc_inverter_power(items) == "无"

    def test_empty(self):
        assert report._calc_inverter_power([]) == "无"


class TestCalcBatteryCapacity:
    def test_single_battery(self):
        items = [_make_item("B01", "电池_100kWh_磷酸铁锂", 2)]
        assert report._calc_battery_capacity(items) == 200.0

    def test_storage_battery(self):
        items = [_make_item("S01", "储能_200kWh_", 1)]
        assert report._calc_battery_capacity(items) == 200.0

    def test_no_battery(self):
        items = [_make_item("I01", "逆变器_33kW_")]
        assert report._calc_battery_capacity(items) == "无"

    def test_empty(self):
        assert report._calc_battery_capacity([]) == "无"


class TestBuildRemark:
    def test_inverter_only(self):
        items = [_make_item("I01", "光储逆变器_33kW_")]
        assert "光储逆变器" in report._build_remark(items)

    def test_grid_cabinet(self):
        items = [_make_item("G01", "并网柜_100kW_")]
        assert "有并网柜" in report._build_remark(items)

    def test_grid_box_without_cabinet(self):
        items = [_make_item("G01", "并网箱_100kW_")]
        assert "有并网箱" in report._build_remark(items)

    def test_grid_box_ignored_when_cabinet_present(self):
        # 有并网柜时，不再标记有并网箱
        items = [
            _make_item("G01", "并网柜_100kW_"),
            _make_item("G02", "并网箱_50kW_"),
        ]
        remark = report._build_remark(items)
        assert "有并网柜" in remark
        assert "有并网箱" not in remark

    def test_dc_cable(self):
        items = [_make_item("C01", "直流电缆_10mm2")]
        assert "有直流线" in report._build_remark(items)

    def test_no_remark(self):
        items = [_make_item("X01", "普通物料")]
        assert report._build_remark(items) == "无"

    def test_empty(self):
        assert report._build_remark([]) == "无"

    def test_multiple_remarks(self):
        items = [
            _make_item("I01", "光储逆变器_33kW_"),
            _make_item("G01", "并网柜_100kW_"),
        ]
        remark = report._build_remark(items)
        assert "光储逆变器" in remark
        assert "有并网柜" in remark


# ==================== 测试：TableProcessResult ====================


class TestTableProcessResult:
    def test_default_values(self):
        r = report.TableProcessResult()
        assert r.flow_ids == []
        assert r.seen_ids == set()
        assert r.skipped_invalid == 0
        assert r.skipped_dup == 0
        assert r.valid_rows == 0

    def test_mutation_isolation(self):
        r1 = report.TableProcessResult()
        r2 = report.TableProcessResult()
        r1.flow_ids.append("test")
        assert len(r2.flow_ids) == 0  # 确保 field(default_factory) 正确工作


# ==================== 测试：去重逻辑 ====================


class TestDedupLogic:
    def test_dedup_filters_existing_ids(self):
        """验证去重逻辑能正确过滤已存在的流程编号。"""
        existing = [
            ("111111111111111111",),
            ("222222222222222222",),
        ]

        rows_data: list[list[str]] = [
            ["111111111111111111", "旧项目（重复）"],
            ["333333333333333333", "新项目"],
        ]

        # 模拟去重逻辑
        existing_ids: set[str] = set()
        for row in existing:
            v = row[0]
            if v and re.match(r"^\d{15,}$", str(v)):
                existing_ids.add(str(v))

        new_rows = [r for r in rows_data if r[0] not in existing_ids]
        assert len(new_rows) == 1
        assert new_rows[0][0] == "333333333333333333"

    def test_non_flow_id_ignored(self):
        """非流程编号的短 ID 不应参与去重比较。"""
        existing = [("short",)]
        rows_data = [["short", "测试数据"]]

        existing_ids = set()
        for row in existing:
            v = row[0]
            if v and re.match(r"^\d{15,}$", str(v)):
                existing_ids.add(str(v))

        new_rows = [r for r in rows_data if r[0] not in existing_ids]
        assert len(new_rows) == 1  # short ID 未被过滤


# ==================== 测试：仅统计模式 ====================


class TestStatsFromExcel:
    def test_date_filter(self):
        """验证日期范围筛选逻辑（stats_from_excel 的核心逻辑）。"""
        rows = [
            ["111111111111111111", "项目A", "", "", "", "", "", "", "", "", "", "2026-06-01 10:00", "", "", "", "", "", "", ""],
            ["222222222222222222", "项目B", "", "", "", "", "", "", "", "", "", "2026-05-15 10:00", "", "", "", "", "", "", ""],
            ["not_flow_id", "项目C", "", "", "", "", "", "", "", "", "", "2026-06-03", "", "", "", "", "", "", ""],
        ]
        start_date, end_date = "2026-06-01", "2026-06-30"

        filtered = []
        for row in rows:
            flow_id = str(row[0]) if row[0] else ""
            if not re.match(r"^\d{15,}$", flow_id):
                continue
            submit_time = str(row[11]) if row[11] else ""
            if submit_time not in ("--", "无", ""):
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
                if date_match:
                    row_date = date_match.group(1)
                    if row_date < start_date or row_date > end_date:
                        continue
            filtered.append(row)

        assert len(filtered) == 1
        assert filtered[0][0] == "111111111111111111"

    def test_date_filter_no_match(self):
        """日期范围无匹配时返回空。"""
        rows = [["111111111111111111", "项目A", "", "", "", "", "", "", "", "", "", "2026-05-01", ""]]
        start_date, end_date = "2026-06-01", "2026-06-30"

        filtered = []
        for row in rows:
            flow_id = str(row[0]) if row[0] else ""
            if not re.match(r"^\d{15,}$", flow_id):
                continue
            submit_time = str(row[11]) if row[11] else ""
            if submit_time not in ("--", "无", ""):
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", submit_time)
                if date_match:
                    row_date = date_match.group(1)
                    if row_date < start_date or row_date > end_date:
                        continue
            filtered.append(row)
        assert len(filtered) == 0


# ==================== 测试：print_summary ====================


class TestPrintSummary:
    def test_no_records(self, capsys):
        report.print_summary(
            start_time=datetime.now(),
            start_date="2026-01-01",
            end_date="2026-01-07",
            flow_ids=None,
            records=None,
        )
        captured = capsys.readouterr()
        assert "2026-01-01 ~ 2026-01-07" in captured.out
        assert "执行摘要" in captured.out

    def test_with_records(self, capsys):
        from datetime import datetime, timedelta

        rec = report.FlowRecord(flow_id="12345678901234567890", ordered="是")
        report.print_summary(
            start_time=datetime.now() - timedelta(seconds=60),
            start_date="2026-01-01",
            end_date="2026-01-07",
            flow_ids=["12345678901234567890"],
            records=[rec],
            excel_path="/tmp/out.xlsx",
        )
        captured = capsys.readouterr()
        assert "已下单" in captured.out
        assert "1 条" in captured.out

    def test_check_failed_shown(self, capsys):
        rec = report.FlowRecord(flow_id="1", ordered="检查失败")
        report.print_summary(
            start_time=datetime.now(),
            start_date="2026-01-01",
            end_date="2026-01-07",
            flow_ids=["1"],
            records=[rec],
        )
        captured = capsys.readouterr()
        assert "检查失败" in captured.out

    def test_check_failed_hidden_when_zero(self, capsys):
        rec = report.FlowRecord(flow_id="1", ordered="是")
        report.print_summary(
            start_time=datetime.now(),
            start_date="2026-01-01",
            end_date="2026-01-07",
            flow_ids=["1"],
            records=[rec],
        )
        captured = capsys.readouterr()
        assert "检查失败" not in captured.out

    def test_error_displayed(self, capsys):
        report.print_summary(
            start_time=datetime.now(),
            start_date="2026-01-01",
            end_date="2026-01-07",
            flow_ids=[],
            records=[],
            error="登录失败",
        )
        captured = capsys.readouterr()
        assert "登录失败" in captured.out


# ==================== 测试：retry_async 装饰器 ====================


class TestRetryAsync:
    def test_success_first_try(self):
        call_count = 0

        @report.retry_async(max_retries=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        import asyncio
        result = asyncio.run(succeed())
        assert result == "ok"
        assert call_count == 1

    def test_retry_then_succeed(self):
        call_count = 0

        @report.retry_async(max_retries=3, base_delay=0.01)
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise report.PlaywrightTimeout("timed out")
            return "ok"

        import asyncio
        result = asyncio.run(fail_twice())
        assert result == "ok"
        assert call_count == 3

    def test_exhaust_retries(self):
        call_count = 0

        @report.retry_async(max_retries=2, base_delay=0.01)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise report.PlaywrightTimeout("always fail")

        import asyncio
        with pytest.raises(report.PlaywrightTimeout):
            asyncio.run(always_fail())
        assert call_count == 2


# ==================== generate_html_report.py 测试 ====================

class TestTemplateReplace:
    def test_simple_replace(self):
        from generate_html_report import _simple_replace
        template = "<title>{{TITLE}}</title><p>{{CONTENT}}</p>"
        result = _simple_replace(template, {"TITLE": "周报", "CONTENT": "数据"})
        assert result == "<title>周报</title><p>数据</p>"

    def test_replace_json_field(self):
        from generate_html_report import _replace_json_field
        template = "const DATA = {{PERIOD_DATA_JSON}};"
        data = {"全部": {"count": 5}}
        result = _replace_json_field(template, "PERIOD_DATA", data)
        assert '"全部"' in result
        assert '"count": 5' in result


class TestComputeKpis:
    def test_basic(self):
        from generate_html_report import compute_kpis
        rows = [
            ["202606010000001", "项目A", "", "", "贵州", "张三", 100.0, 80.0, 20.0, "", "", "2026-06-01", "", "否", "", "", "", "", ""],
            ["202606010000002", "项目B", "", "", "贵州", "李四", 200.0, 150.0, 50.0, "", "", "2026-06-02", "", "是", "", "", "", "", ""],
            ["202606010000003", "项目C", "", "", "云南", "张三", 0, 0, 0, "", "", "2026-06-03", "", "否", "", "", "", "", ""],
        ]
        kpis = compute_kpis(rows)
        assert kpis["total_projects"] == 3
        assert kpis["total_salespersons"] == 2
        assert kpis["ordered_count"] == 1
        assert kpis["not_ordered_count"] == 2
        assert kpis["module_power"] == "300.00"
        assert kpis["inverter_power"] == "230.00"
        assert kpis["battery_capacity"] == "70.00"
        assert kpis["ratio"] == "1.30"

    def test_empty_rows(self):
        from generate_html_report import compute_kpis
        kpis = compute_kpis([])
        assert kpis["total_projects"] == 0
        assert kpis["ordered_count"] == 0
        assert kpis["ratio"] == "--"

    def test_string_values(self):
        from generate_html_report import compute_kpis
        rows = [
            ["202606010000001", "项目A", "", "", "贵州", "张三", "100", "80", "20", "", "", "2026-06-01", "", "否"],
        ]
        kpis = compute_kpis(rows)
        assert kpis["total_projects"] == 1
        assert kpis["module_power"] == "100.00"


class TestComputeWangjian:
    def test_basic(self):
        from generate_html_report import compute_wangjian_stats
        rows = [
            ["202606010000001", "", "", "", "", "", 0, 0, 0, "", "", "", "", "", "", "", "王剑", "审批通过", ""],
            ["202606010000002", "", "", "", "", "", 0, 0, 0, "", "", "", "", "", "", "", "王剑", "审批通过", ""],
            ["202606010000003", "", "", "", "", "", 0, 0, 0, "", "", "", "", "", "", "", "王剑", "审批拒绝", ""],
            ["202606010000004", "", "", "", "", "", 0, 0, 0, "", "", "", "", "", "", "", "李四", "审批通过", ""],
        ]
        stats = compute_wangjian_stats(rows)
        assert stats["approved"] == 2
        assert stats["total"] == 3
        assert stats["rate"] == "66%"

    def test_no_wangjian(self):
        from generate_html_report import compute_wangjian_stats
        rows = [
            ["202606010000001", "", "", "", "", "", 0, 0, 0, "", "", "", "", "", "", "", "李四", "审批通过", ""],
        ]
        stats = compute_wangjian_stats(rows)
        assert stats["approved"] == 0
        assert stats["total"] == 0


class TestComputeProvince:
    def test_basic(self):
        from generate_html_report import compute_province_ranking
        rows = [
            ["202606010000001", "", "", "", "贵州", "", 100.0, 0, 0],
            ["202606010000002", "", "", "", "贵州", "", 200.0, 0, 0],
            ["202606010000003", "", "", "", "云南", "", 150.0, 0, 0],
        ]
        ranking = compute_province_ranking(rows)
        assert len(ranking) == 2
        assert ranking[0]["province"] == "贵州"
        assert ranking[0]["count"] == 2
        assert ranking[0]["module"] == 300.0
        assert ranking[1]["rank"] == 2

    def test_empty(self):
        from generate_html_report import compute_province_ranking
        assert compute_province_ranking([]) == []


class TestComputeApprovalDays:
    def test_basic(self):
        from generate_html_report import compute_approval_days
        rows = [
            ["202606010000001", "", "", "", "", "", 0, 0, 0, "", "", "2026-06-01", "", "", "", "", "", "", "2026-06-05"],
            ["202606010000002", "", "", "", "", "", 0, 0, 0, "", "", "2026-06-02", "", "", "", "", "", "", "2026-06-04"],
            ["202606010000003", "", "", "", "", "", 0, 0, 0, "", "", "2026-06-10", "", "", "", "", "", "", ""],
        ]
        days = compute_approval_days(rows)
        assert days["avg"] == 3.0
        assert days["min"] == 2
        assert days["max"] == 4
        assert days["sample_count"] == 2

    def test_no_data(self):
        from generate_html_report import compute_approval_days
        days = compute_approval_days([])
        assert days["avg"] == 0
        assert days["sample_count"] == 0
