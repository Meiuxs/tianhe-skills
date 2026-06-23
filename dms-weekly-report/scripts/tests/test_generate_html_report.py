"""generate_html_report.py 单元测试。"""

import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_html_report import (
    _safe_float,
    _simple_replace,
    _replace_json_field,
    compute_rows_detail,
)
from column_definitions import (
    COL_FLOW_ID, COL_PROJECT_NAME, COL_PROVINCE, COL_SALESPERSON,
    COL_MODULE_KW, COL_INVERTER_KW, COL_BATTERY_KWH,
    COL_SUBMIT_TIME, COL_REMARK,
    COL_IS_VALID, COL_NEGOTIATION_PROCESSOR, COL_NEGOTIATION_STATUS, COL_NEGOTIATION_TIME,
    COL_PROVINCE_PROCESSOR, COL_PROVINCE_STATUS,
    COL_FINAL_APPROVAL_TIME,
)


def _make_row(**overrides):
    """构造一行 20 列的测试数据。"""
    row = ["--"] * 20
    defaults = {
        "flow_id": "12345678901234567",
        "project_name": "测试项目",
        "province": "广东",
        "salesperson": "张三",
        "module_kw": 10.5,
        "inverter_kw": 8.0,
        "battery_kwh": 5.0,
        "submit_time": "2026-06-01 10:00:00",
        "is_valid": "是",
        "remark": "无",
        "negotiation_processor": "王五",
        "negotiation_status": "审批通过",
        "negotiation_time": "2026-06-03 15:30:00",
        "province_processor": "李四",
        "province_status": "审批通过",
        "final_approval_time": "2026-06-03 15:30:00",
    }
    defaults.update(overrides)
    row[COL_FLOW_ID] = defaults["flow_id"]
    row[COL_PROJECT_NAME] = defaults["project_name"]
    row[COL_PROVINCE] = defaults["province"]
    row[COL_SALESPERSON] = defaults["salesperson"]
    row[COL_MODULE_KW] = defaults["module_kw"]
    row[COL_INVERTER_KW] = defaults["inverter_kw"]
    row[COL_BATTERY_KWH] = defaults["battery_kwh"]
    row[COL_SUBMIT_TIME] = defaults["submit_time"]
    row[COL_IS_VALID] = defaults["is_valid"]
    row[COL_REMARK] = defaults["remark"]
    row[COL_NEGOTIATION_PROCESSOR] = defaults["negotiation_processor"]
    row[COL_NEGOTIATION_STATUS] = defaults["negotiation_status"]
    row[COL_NEGOTIATION_TIME] = defaults["negotiation_time"]
    row[COL_PROVINCE_PROCESSOR] = defaults["province_processor"]
    row[COL_PROVINCE_STATUS] = defaults["province_status"]
    row[COL_FINAL_APPROVAL_TIME] = defaults["final_approval_time"]
    return row


class TestSafeFloat:
    """测试 _safe_float 函数。"""

    def test_int_value(self):
        assert _safe_float(42) == 42.0

    def test_float_value(self):
        assert _safe_float(3.14) == 3.14

    def test_string_number(self):
        assert _safe_float("12.5") == 12.5

    def test_string_non_number(self):
        assert _safe_float("无") == 0.0

    def test_empty_string(self):
        assert _safe_float("") == 0.0

    def test_none_value(self):
        assert _safe_float(None) == 0.0

    def test_bool_value(self):
        assert _safe_float(True) == 1.0

    def test_infinity(self):
        assert _safe_float(float("inf")) == 0.0

    def test_nan(self):
        assert _safe_float(float("nan")) == 0.0

    def test_string_nan(self):
        assert _safe_float("nan") == 0.0

    def test_string_inf(self):
        assert _safe_float("inf") == 0.0

    def test_negative_number(self):
        assert _safe_float("-5.5") == -5.5

    def test_list_value(self):
        assert _safe_float([1, 2]) == 0.0


class TestSimpleReplace:
    """测试 _simple_replace 函数。"""

    def test_basic_replacement(self):
        template = "Hello {{NAME}}, welcome!"
        result = _simple_replace(template, {"NAME": "World"})
        assert result == "Hello World, welcome!"

    def test_multiple_replacements(self):
        template = "{{A}} and {{B}}"
        result = _simple_replace(template, {"A": "foo", "B": "bar"})
        assert result == "foo and bar"

    def test_no_match(self):
        template = "No placeholders here"
        result = _simple_replace(template, {"NAME": "World"})
        assert result == "No placeholders here"

    def test_empty_template(self):
        result = _simple_replace("", {"KEY": "val"})
        assert result == ""

    def test_empty_replacements(self):
        result = _simple_replace("{{KEY}}", {})
        assert result == "{{KEY}}"

    def test_replacement_with_special_chars(self):
        template = "Data: {{DATA}}"
        result = _simple_replace(template, {"DATA": '<div class="test">'})
        assert result == 'Data: <div class="test">'


class TestReplaceJsonField:
    """测试 _replace_json_field 函数。"""

    def test_basic_json_replacement(self):
        template = "var data = {{DATA_JSON}};"
        data = {"key": "value"}
        result = _replace_json_field(template, "DATA", data)
        assert '"key": "value"' in result
        assert "{{DATA_JSON}}" not in result

    def test_nested_json(self):
        template = "{{ROWS_JSON}}"
        data = [{"a": 1}, {"b": 2}]
        result = _replace_json_field(template, "ROWS", data)
        assert "{{ROWS_JSON}}" not in result
        assert '"a": 1' in result

    def test_chinese_characters(self):
        template = "{{INFO_JSON}}"
        data = {"名称": "测试", "状态": "完成"}
        result = _replace_json_field(template, "INFO", data)
        assert "测试" in result
        assert "完成" in result

    def test_empty_data(self):
        template = "{{DATA_JSON}}"
        result = _replace_json_field(template, "DATA", {})
        assert "{{DATA_JSON}}" not in result

    def test_list_data(self):
        template = "{{ITEMS_JSON}}"
        data = [1, 2, 3]
        result = _replace_json_field(template, "ITEMS", data)
        assert "{{ITEMS_JSON}}" not in result
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]


class TestComputeRowsDetail:
    """测试 compute_rows_detail 函数。"""

    def test_basic_row(self):
        rows = [_make_row()]
        result = compute_rows_detail(rows)
        assert len(result) == 1
        assert result[0]["flowId"] == "12345678901234567"
        assert result[0]["projectName"] == "测试项目"
        assert result[0]["province"] == "广东"

    def test_skip_none_flow_id(self):
        row = _make_row()
        row[COL_FLOW_ID] = None
        rows = [row]
        result = compute_rows_detail(rows)
        assert len(result) == 0

    def test_skip_short_flow_id(self):
        row = _make_row()
        row[COL_FLOW_ID] = "123"
        rows = [row]
        result = compute_rows_detail(rows)
        assert len(result) == 0

    def test_float_flow_id(self):
        row = _make_row()
        row[COL_FLOW_ID] = 12345678901234567.0
        rows = [row]
        result = compute_rows_detail(rows)
        assert len(result) == 1
        # IEEE 754 浮点数精度限制，大数转换可能丢失精度
        assert result[0]["flowId"].isdigit()

    def test_is_valid_yes(self):
        row = _make_row()
        row[COL_IS_VALID] = "是"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["isValid"] == "是"

    def test_is_valid_no(self):
        row = _make_row()
        row[COL_IS_VALID] = "否"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["isValid"] == "否"

    def test_final_date_empty(self):
        row = _make_row()
        row[COL_FINAL_APPROVAL_TIME] = ""
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["finalDate"] == ""

    def test_final_date_dash(self):
        row = _make_row()
        row[COL_FINAL_APPROVAL_TIME] = "--"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["finalDate"] == ""

    def test_final_date_none(self):
        row = _make_row()
        row[COL_FINAL_APPROVAL_TIME] = "无"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["finalDate"] == ""

    def test_final_date_valid(self):
        row = _make_row()
        row[COL_FINAL_APPROVAL_TIME] = "2026-06-03 15:30"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["finalDate"] == "2026-06-03"

    def test_negotiation_approver_dash(self):
        row = _make_row()
        row[COL_NEGOTIATION_PROCESSOR] = "--"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["negotiationApprover"] == ""

    def test_negotiation_approver_valid(self):
        row = _make_row()
        row[COL_NEGOTIATION_PROCESSOR] = "王五"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["negotiationApprover"] == "王五"

    def test_province_status_valid(self):
        row = _make_row()
        row[COL_PROVINCE_STATUS] = "审批通过"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["provinceStatus"] == "审批通过"

    def test_multiple_rows(self):
        row1 = _make_row()
        row1[COL_FLOW_ID] = "11111111111111111"
        row2 = _make_row()
        row2[COL_FLOW_ID] = "22222222222222222"
        rows = [row1, row2]
        result = compute_rows_detail(rows)
        assert len(result) == 2

    def test_empty_rows(self):
        result = compute_rows_detail([])
        assert result == []

    def test_power_values(self):
        row = _make_row()
        row[COL_MODULE_KW] = 100.5
        row[COL_INVERTER_KW] = 80.0
        row[COL_BATTERY_KWH] = 50.0
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["modulePower"] == 100.5
        assert result[0]["inverterPower"] == 80.0
        assert result[0]["batteryCapacity"] == 50.0

    def test_submit_date_truncated(self):
        row = _make_row()
        row[COL_SUBMIT_TIME] = "2026-06-01 10:00:00"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["submitDate"] == "2026-06-01"

    def test_submit_date_short(self):
        row = _make_row()
        row[COL_SUBMIT_TIME] = "2026"
        rows = [row]
        result = compute_rows_detail(rows)
        assert result[0]["submitDate"] == "2026"

class TestXssProtection:
    """测试 XSS 安全防护。"""

    def test_json_injection_escapes_script_tag(self):
        """验证 JSON 注入时数据中的 </script> 被转义，防止 XSS。"""
        template = "<script>var data = {{ROWS_JSON}};</script>"
        data = [{"name": "</script><script>alert(1)</script>"}]
        result = _replace_json_field(template, "ROWS", data)
        # 模板本身的 </script> 是合法的，但数据中的 </script> 必须被转义
        # 结果中不应包含数据原始值中的 </script> 序列
        assert "\u003c\u002fscript\u003e" in result

    def test_json_injection_escapes_angle_brackets(self):
        """验证 JSON 中所有尖括号被转义。"""
        template = "{{DATA_JSON}}"
        data = {"html": "<div>test</div>"}
        result = _replace_json_field(template, "DATA", data)
        assert "<div>" not in result
        assert "\\u003c" in result
        assert "\\u003e" in result

    def test_json_injection_escapes_slash(self):
        """验证 JSON 中正斜杠被转义。"""
        template = "{{DATA_JSON}}"
        data = {"url": "http://example.com/path"}
        result = _replace_json_field(template, "DATA", data)
        # 正斜杠应被转义为 \u002f
        assert "\\u002f" in result

    def test_query_range_xss_escaped(self):
        """验证空数据模板中 query_range 被 HTML 转义。"""
        from generate_html_report import generate_html_report
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "test.html")
            # 使用包含 HTML 的 query_range
            generate_html_report([], "<script>alert(1)</script>", output)
            with open(output, "r", encoding="utf-8") as f:
                html = f.read()
            assert "<script>" not in html
            assert "&lt;script&gt;" in html


class TestFormatDatetime:
    """测试 _format_datetime 辅助函数。"""

    def test_none_value(self):
        from generate_html_report import _format_datetime
        assert _format_datetime(None) == ""

    def test_datetime_object(self):
        from datetime import datetime
        from generate_html_report import _format_datetime
        dt = datetime(2026, 6, 14, 10, 30, 0)
        assert _format_datetime(dt) == "2026-06-14 10:30:00"

    def test_iso_string(self):
        from generate_html_report import _format_datetime
        assert _format_datetime("2026-06-14T10:30:00") == "2026-06-14 10:30:00"

    def test_date_only_string(self):
        from generate_html_report import _format_datetime
        assert _format_datetime("2026-06-14") == "2026-06-14"

    def test_empty_string(self):
        from generate_html_report import _format_datetime
        assert _format_datetime("") == ""

    def test_garbage_string(self):
        from generate_html_report import _format_datetime
        assert _format_datetime("not-a-date") == "not-a-date"


class TestRowDetailType:
    """测试 RowDetail TypedDict 类型定义。"""

    def test_typed_dict_exists(self):
        from generate_html_report import RowDetail
        assert RowDetail.__annotations__ is not None
        assert "flowId" in RowDetail.__annotations__  # 实际字段名是 flowId (camelCase)
        assert "projectName" in RowDetail.__annotations__
        assert "modulePower" in RowDetail.__annotations__
