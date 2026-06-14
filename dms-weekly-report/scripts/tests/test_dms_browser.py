"""core/dms_browser.py 纯函数单元测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dms_browser import (
    is_on_login_page,
    get_week_range,
    _extract_from_html,
    _split_agent,
    FlowRecord,
    TableProcessResult,
)
from column_definitions import LOGIN_CHECK_DOMAIN


class TestIsOnLoginPage:
    """测试 is_on_login_page 函数。"""

    def test_login_page(self):
        assert is_on_login_page(f"https://{LOGIN_CHECK_DOMAIN}/auth/login") is True

    def test_dms_page(self):
        assert is_on_login_page("https://dms-admin.trinapower.com/dashboard") is False

    def test_empty_url(self):
        assert is_on_login_page("") is False

    def test_partial_match(self):
        assert is_on_login_page(f"https://sub.{LOGIN_CHECK_DOMAIN}/path") is True


class TestGetWeekRange:
    """测试 get_week_range 函数。"""

    def test_returns_tuple(self):
        result = get_week_range()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_format(self):
        start, end = get_week_range()
        assert len(start) == 10
        assert len(end) == 10
        assert start.count("-") == 2
        assert end.count("-") == 2

    def test_start_is_earlier(self):
        start, end = get_week_range()
        assert start <= end

    def test_weeks_ago(self):
        start0, end0 = get_week_range(0)
        start1, end1 = get_week_range(1)
        assert start1 < start0

    def test_two_weeks_ago(self):
        start0, _ = get_week_range(0)
        start2, _ = get_week_range(2)
        from datetime import datetime, timedelta
        d0 = datetime.strptime(start0, "%Y-%m-%d")
        d2 = datetime.strptime(start2, "%Y-%m-%d")
        diff_days = (d0 - d2).days
        assert 12 <= diff_days <= 16


class TestExtractFromHtml:
    """测试 _extract_from_html 函数。"""

    def test_direct_match(self):
        html = '<th>项目名称</th><td>测试项目</td>'
        assert _extract_from_html(html, "项目名称") == "测试项目"

    def test_nested_match(self):
        html = '<th>项目名称</th><th><div>嵌套值</div></th>'
        result = _extract_from_html(html, "项目名称")
        assert result == "嵌套值"

    def test_not_found(self):
        html = '<th>其他字段</th><td>其他值</td>'
        assert _extract_from_html(html, "项目名称") == "--"

    def test_label_with_colon(self):
        html = '<th>项目名称:</th><td>有冒号的值</td>'
        assert _extract_from_html(html, "项目名称") == "有冒号的值"

    def test_empty_html(self):
        assert _extract_from_html("", "项目名称") == "--"

    def test_special_chars(self):
        html = '<th>瓦单价(元/瓦)</th><td>1.25</td>'
        assert _extract_from_html(html, "瓦单价(元/瓦)") == "1.25"


class TestSplitAgent:
    """测试 _split_agent 函数。"""

    def test_code_and_name(self):
        assert _split_agent("AGENT-001 某公司") == ("AGENT-001", "某公司")

    def test_code_only(self):
        assert _split_agent("AGENT-001") == ("AGENT-001", "--")

    def test_empty(self):
        assert _split_agent("") == ("--", "--")

    def test_dash(self):
        assert _split_agent("--") == ("--", "--")

    def test_multi_word_name(self):
        code, name = _split_agent("AG-001 深圳 天合 光能")
        assert code == "AG-001"
        assert name == "深圳 天合 光能"

    def test_none_input(self):
        assert _split_agent(None) == ("--", "--")


class TestFlowRecord:
    """测试 FlowRecord 数据类。"""

    def test_default_values(self):
        rec = FlowRecord()
        assert rec.flow_id == ""
        assert rec.project_name == "--"
        assert rec.ordered == "否"
        assert rec.module_kw == 0.0

    def test_custom_values(self):
        rec = FlowRecord(
            flow_id="123",
            project_name="测试",
            module_kw=99.5,
        )
        assert rec.flow_id == "123"
        assert rec.project_name == "测试"
        assert rec.module_kw == 99.5


class TestTableProcessResult:
    """测试 TableProcessResult 数据类。"""

    def test_default_values(self):
        result = TableProcessResult()
        assert result.flow_ids == []
        assert result.seen_ids == set()
        assert result.skipped_invalid == 0
        assert result.skipped_dup == 0
        assert result.valid_rows == 0

    def test_mutation_isolation(self):
        r1 = TableProcessResult()
        r2 = TableProcessResult()
        r1.flow_ids.append("123")
        assert "123" not in r2.flow_ids
