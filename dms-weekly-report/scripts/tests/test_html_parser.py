"""core/html_parser.py 单元测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.html_parser import extract_from_html, split_agent


class TestExtractFromHtml:
    """测试 extract_from_html 函数。"""

    def test_direct_match(self):
        html = '<th>项目名称</th><td>测试项目</td>'
        assert extract_from_html(html, "项目名称") == "测试项目"

    def test_nested_match(self):
        html = '<th>项目名称</th><th><div>嵌套值</div></th>'
        assert extract_from_html(html, "项目名称") == "嵌套值"

    def test_not_found(self):
        html = '<th>其他字段</th><td>其他值</td>'
        assert extract_from_html(html, "项目名称") == "--"

    def test_label_with_colon(self):
        html = '<th>项目名称:</th><td>有冒号的值</td>'
        assert extract_from_html(html, "项目名称") == "有冒号的值"

    def test_empty_html(self):
        assert extract_from_html("", "项目名称") == "--"

    def test_special_chars(self):
        html = '<th>瓦单价(元/瓦)</th><td>1.25</td>'
        assert extract_from_html(html, "瓦单价(元/瓦)") == "1.25"

    def test_cross_row_no_match(self):
        html = '<th>项目名称</th></tr><tr><th>其他字段</th><td>其他值</td>'
        assert extract_from_html(html, "项目名称") == "--"

    def test_cross_row_td_no_match(self):
        html = '<th>项目名称</th></tr><tr><td></td><td>下一行的值</td>'
        assert extract_from_html(html, "项目名称") == "--"

    def test_multiline_nested_value(self):
        html = '<th>项目名称</th><th>\n  <div>\n    多行值\n  </div>\n</th>'
        assert extract_from_html(html, "项目名称") == "多行值"

    def test_value_with_html_entities(self):
        html = '<th>项目名称</th><td>项目&nbsp;A&amp;B</td>'
        result = extract_from_html(html, "项目名称")
        assert "项目" in result


class TestSplitAgent:
    """测试 split_agent 函数。"""

    def test_code_and_name(self):
        assert split_agent("AGENT-001 某公司") == ("AGENT-001", "某公司")

    def test_code_only(self):
        assert split_agent("AGENT-001") == ("AGENT-001", "--")

    def test_empty(self):
        assert split_agent("") == ("--", "--")

    def test_dash(self):
        assert split_agent("--") == ("--", "--")

    def test_multi_word_name(self):
        code, name = split_agent("AG-001 深圳 天合 光能")
        assert code == "AG-001"
        assert name == "深圳 天合 光能"

    def test_none_input(self):
        assert split_agent(None) == ("--", "--")

    def test_multiple_spaces(self):
        assert split_agent("C001  某公司") == ("C001", "某公司")

    def test_tab_separated(self):
        assert split_agent("C001\t某公司") == ("C001", "某公司")

    def test_leading_trailing_spaces(self):
        code, name = split_agent("  C001  某公司  ")
        assert code == "C001"
        assert name == "某公司"
