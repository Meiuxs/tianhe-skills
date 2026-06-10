#!/usr/bin/env python3
"""dms_credentials.py 的完整测试套件。

覆盖范围：
  1. 凭据解析函数
  2. Chromium 检查函数
  3. 预编译正则匹配
  4. CLI 入口（--check-browser）
"""

import io
import os
import sys
import unittest
from unittest.mock import patch

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from dms_credentials import (  # noqa: E402
    _ENV_LINE_RE,
    _parse_env_from_file,
    check_current_env,
    check_bash_profiles,
    check_powershell,
    resolve_credentials,
    get_credentials,
    source_label,
    check_chromium,
    check_chromium_headless_shell,
    _check_chromium_component,
    _glob_first,
    _get_home,
    _bash_available,
    SOURCE_LABELS,
    DMS_URL,
)


# ═══════════════════════════════════════════════════════════
#  1. 正则解析 (shell profile)
# ═══════════════════════════════════════════════════════════

class TestRegExpParsing(unittest.TestCase):
    """测试 _ENV_LINE_RE 正则的正确性"""

    def test_export_double_quote(self):
        """export DMS_USER="admin@test.com" 格式"""
        m = _ENV_LINE_RE.match('export DMS_USER="admin@test.com"')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "DMS_USER")
        self.assertEqual(m.group(2), "admin@test.com")

    def test_export_single_quote(self):
        """export DMS_PASSWORD='abc123' 格式"""
        m = _ENV_LINE_RE.match("export DMS_PASSWORD='abc123'")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "DMS_PASSWORD")
        self.assertEqual(m.group(3), "abc123")

    def test_plain_value(self):
        """DMS_USER=admin 格式（无引号）"""
        m = _ENV_LINE_RE.match("DMS_USER=admin")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(4), "admin")

    def test_with_trailing_comment(self):
        """DMS_USER="admin" # 这是注释 格式"""
        m = _ENV_LINE_RE.match('DMS_USER="admin" # 这是注释')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "admin")

    def test_escaped_quote_in_value(self):
        """DMS_USER='it\\'s me' 格式（转义引号）
        注意：在测试文件中需要用双反斜杠表示一个反斜杠"""
        m = _ENV_LINE_RE.match("DMS_USER='it\\'s me'")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3), "it\\'s me")

    def test_non_matching_line(self):
        """不包含 DMS_USER/PASSWORD 的行不匹配"""
        self.assertIsNone(_ENV_LINE_RE.match("export PATH=/usr/bin"))
        self.assertIsNone(_ENV_LINE_RE.match("# DMS_USER=admin"))
        self.assertIsNone(_ENV_LINE_RE.match(""))


# ═══════════════════════════════════════════════════════════
#  2. 文件解析
# ═══════════════════════════════════════════════════════════

class TestParseEnvFromFile(unittest.TestCase):
    """测试 _parse_env_from_file 从伪文件读取"""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                delete=False)
        self.tmp.write("""export DMS_USER="admin@test.com"
export DMS_PASSWORD='secret123'
# 注释行
export PATH=/usr/bin
""")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_parse_both(self):
        """同时解析 user 和 password"""
        user, password = _parse_env_from_file(self.tmp.name)
        self.assertEqual(user, "admin@test.com")
        self.assertEqual(password, "secret123")

    def test_parse_missing_file(self):
        """不存在的文件返回 (None, None)"""
        user, password = _parse_env_from_file("/nonexistent/.bashrc")
        self.assertIsNone(user)
        self.assertIsNone(password)


# ═══════════════════════════════════════════════════════════
#  3. 环境变量检查
# ═══════════════════════════════════════════════════════════

class TestCheckCurrentEnv(unittest.TestCase):
    """测试 check_current_env"""

    @patch.dict(os.environ, {"DMS_USER": "test@test.com", "DMS_PASSWORD": "pass123"}, clear=True)
    def test_env_found(self):
        """环境变量存在时返回 (source, user, password)"""
        result = check_current_env()
        self.assertIsNotNone(result)
        source, user, password = result
        self.assertEqual(source, "current")
        self.assertEqual(user, "test@test.com")
        self.assertEqual(password, "pass123")

    @patch.dict(os.environ, {}, clear=True)
    def test_env_not_found(self):
        """环境变量不存在时返回 None"""
        result = check_current_env()
        self.assertIsNone(result)

    @patch.dict(os.environ, {"DMS_USER": "test@test.com"}, clear=True)
    def test_only_user_no_password(self):
        """仅有 USER 没有 PASSWORD 时返回 None"""
        result = check_current_env()
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════
#  4. source_label 映射
# ═══════════════════════════════════════════════════════════

class TestSourceLabel(unittest.TestCase):
    """测试 source_label 映射"""

    def test_known_source(self):
        """已知 source 返回中文标签"""
        self.assertIn("环境变量", source_label("current"))

    def test_unknown_source(self):
        """未知 source 原样返回"""
        self.assertEqual(source_label("custom_source"), "custom_source")


# ═══════════════════════════════════════════════════════════
#  5. Chromium 检查（共享函数 + 包装函数）
# ═══════════════════════════════════════════════════════════

class TestCheckChromiumComponent(unittest.TestCase):
    """测试 _check_chromium_component 共享函数"""

    @patch("dms_credentials._glob_first")
    def test_chromium_found(self, mock_glob):
        """Chromium 组件存在时返回 True"""
        mock_glob.return_value = "/path/to/chrome.exe"

        # 捕获打印输出
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            result = _check_chromium_component("Chromium", "  [Chromium]", {
                "win32": "/some/pattern",
            })
        self.assertTrue(result)

    @patch("dms_credentials._glob_first")
    def test_chromium_not_found(self, mock_glob):
        """Chromium 组件不存在时返回 False"""
        mock_glob.return_value = None

        captured = io.StringIO()
        with patch("sys.stderr", captured):
            result = _check_chromium_component("Chromium", "  [Chromium]", {
                "win32": "/some/pattern",
            })
        self.assertFalse(result)

    @patch("dms_credentials._glob_first")
    def test_headless_shell_found(self, mock_glob):
        """Headless Shell 文件存在时返回 True"""
        mock_glob.return_value = "/path/to/chrome-headless-shell.exe"

        captured = io.StringIO()
        with patch("sys.stderr", captured):
            with patch("os.path.isfile", return_value=True):
                result = _check_chromium_component("Headless Shell", "  [Headless Shell]", {
                    "win32": "/some/pattern",
                })
        self.assertTrue(result)

    @patch("dms_credentials._glob_first")
    def test_headless_shell_found_but_not_file(self, mock_glob):
        """Headless Shell 路径存在但不是文件时返回 False"""
        mock_glob.return_value = "/path/to/chrome-headless-shell.exe"

        captured = io.StringIO()
        with patch("sys.stderr", captured):
            with patch("os.path.isfile", return_value=False):
                result = _check_chromium_component("Headless Shell", "  [Headless Shell]", {
                    "win32": "/some/pattern",
                })
        self.assertFalse(result)


class TestCheckChromium(unittest.TestCase):
    """测试 check_chromium 和 check_chromium_headless_shell 包装函数"""

    @patch("dms_credentials._check_chromium_component")
    def test_chromium_wrapper(self, mock_cc):
        """check_chromium 委托给 _check_chromium_component"""
        mock_cc.return_value = True
        result = check_chromium()
        self.assertTrue(result)
        mock_cc.assert_called_once()

    @patch("dms_credentials._check_chromium_component")
    def test_chromium_headless_wrapper(self, mock_cc):
        """check_chromium_headless_shell 委托给 _check_chromium_component"""
        mock_cc.return_value = False
        result = check_chromium_headless_shell()
        self.assertFalse(result)
        mock_cc.assert_called_once()


# ═══════════════════════════════════════════════════════════
#  6. _glob_first
# ═══════════════════════════════════════════════════════════

class TestGlobFirst(unittest.TestCase):
    """测试 _glob_first"""

    def test_no_match(self):
        """不匹配时返回 None"""
        result = _glob_first("__nonexistent_pattern_xyz__*")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════
#  7. DMS_URL 常量
# ═══════════════════════════════════════════════════════════

class TestDmsUrl(unittest.TestCase):
    """DMS_URL 常量"""

    def test_url_is_str(self):
        self.assertIsInstance(DMS_URL, str)
        self.assertTrue(DMS_URL.startswith("https://"))


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
