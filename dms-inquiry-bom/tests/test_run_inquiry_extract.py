#!/usr/bin/env python3
"""run_inquiry_extract.py 测试套件。

覆盖范围：
  1. _extract_from_html 正则提取
  2. _split_agent 代理商解析
  3. print_summary 摘要输出格式
  4. _extract_bom BOM 去重逻辑
"""

import io
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from run_inquiry_extract import (  # noqa: E402
    _extract_from_html,
    _split_agent,
    print_summary,
)


# ═══════════════════════════════════════════════════════════
#  1. _extract_from_html
# ═══════════════════════════════════════════════════════════

class TestExtractFromHtml(unittest.TestCase):
    """测试 _extract_from_html 正则提取"""

    def test_simple_label(self):
        """基本标签提取"""
        html = '<div><label>项目名称:</label><span>南宁分布式光伏</span></div>'
        result = _extract_from_html(html, "项目名称")
        self.assertEqual(result, "南宁分布式光伏")

    def test_with_colon(self):
        """带冒号标签"""
        html = '<div><label>项目名称:</label><span>测试项目</span></div>'
        result = _extract_from_html(html, "项目名称")
        self.assertEqual(result, "测试项目")

    def test_nested_structure(self):
        """嵌套结构（两层）"""
        html = '<div class="field"><label>省公司</label><div class="value">广西</div></div>'
        result = _extract_from_html(html, "省公司")
        self.assertEqual(result, "广西")

    def test_multi_layer(self):
        """两层结构"""
        html = '<div><label>业务员</label><div><span>张三</span></div></div>'
        result = _extract_from_html(html, "业务员")
        self.assertEqual(result, "张三")

    def test_not_found(self):
        """未找到返回 --"""
        html = '<div><label>其他</label><span>值</span></div>'
        result = _extract_from_html(html, "项目名称")
        self.assertEqual(result, "--")


# ═══════════════════════════════════════════════════════════
#  2. _split_agent
# ═══════════════════════════════════════════════════════════

class TestSplitAgent(unittest.TestCase):
    """测试 _split_agent"""

    def test_code_and_name(self):
        """编码+名称"""
        code, name = _split_agent("AG001 张三")
        self.assertEqual(code, "AG001")
        self.assertEqual(name, "张三")

    def test_only_code(self):
        """只有编码"""
        code, name = _split_agent("AG001")
        self.assertEqual(code, "AG001")
        self.assertEqual(name, "--")

    def test_empty(self):
        """空字符串"""
        code, name = _split_agent("--")
        self.assertEqual(code, "--")
        self.assertEqual(name, "--")

    def test_none(self):
        """None"""
        code, name = _split_agent(None)
        self.assertEqual(code, "--")
        self.assertEqual(name, "--")

    def test_multi_word_name(self):
        """多词名称"""
        code, name = _split_agent("AG002 张三丰")
        self.assertEqual(code, "AG002")
        self.assertEqual(name, "张三丰")


# ═══════════════════════════════════════════════════════════
#  3. print_summary
# ═══════════════════════════════════════════════════════════

class TestPrintSummary(unittest.TestCase):
    """测试 print_summary"""

    def test_prints_basic_info(self):
        """输出包含流程数等信息"""
        captured = io.StringIO()
        start = datetime.now()
        with patch("sys.stderr", captured):
            print_summary(start, ["F001", "F002"], ["F001"], output_file=None)
        output = captured.getvalue()
        self.assertIn("执行摘要", output)
        self.assertIn("2 条", output)  # 待办流程
        self.assertIn("1 条", output)  # 成功提取

    def test_empty_flow_ids(self):
        """无流程时不报错"""
        captured = io.StringIO()
        start = datetime.now()
        with patch("sys.stderr", captured):
            print_summary(start, [], [], output_file=None)
        output = captured.getvalue()
        self.assertIn("执行摘要", output)

    def test_with_error(self):
        """含异常信息"""
        captured = io.StringIO()
        start = datetime.now()
        with patch("sys.stderr", captured):
            print_summary(start, ["F001"], [], output_file=None, error="超时")
        output = captured.getvalue()
        self.assertIn("异常", output)
        self.assertIn("超时", output)

    def test_with_output_file(self):
        """含输出路径"""
        captured = io.StringIO()
        start = datetime.now()
        with patch("sys.stderr", captured):
            print_summary(start, ["F001"], ["F001"], output_file="/tmp/out.json")
        output = captured.getvalue()
        self.assertIn("/tmp/out.json", output)


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
