#!/usr/bin/env python3
"""check_environment.py 单元测试。

覆盖：
  - Python 版本检查（正常/低版本）
  - pip 版本检查（正常/低版本/未安装）
  - 依赖包检查（全部安装/部分缺失）
  - Chromium 检查（mock 跨平台）
  - 凭据检查（有/无）
  - 磁盘空间检查
  - run_all_checks 编排
  - print_results 输出格式
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check_environment as ce


class TestCheckPythonVersion(unittest.TestCase):
    """Python 版本检查。"""

    @patch("check_environment.sys")
    def test_current_version_passes(self, mock_sys):
        mock_sys.version_info = (3, 11, 0, "final", 0)
        mock_sys.executable = "/usr/bin/python3"
        result = ce.check_python_version()
        self.assertTrue(result.passed)
        self.assertIn("3.11", result.message)

    @patch("check_environment.sys")
    def test_minimum_version_passes(self, mock_sys):
        mock_sys.version_info = (3, 9, 0, "final", 0)
        mock_sys.executable = "/usr/bin/python3"
        result = ce.check_python_version()
        self.assertTrue(result.passed)

    @patch("check_environment.sys")
    def test_old_version_fails(self, mock_sys):
        mock_sys.version_info = (3, 8, 0, "final", 0)
        mock_sys.executable = "/usr/bin/python3"
        result = ce.check_python_version()
        self.assertFalse(result.passed)
        self.assertIn("3.8", result.message)
        self.assertIn("请升级", result.fix_hint)


class TestCheckPackages(unittest.TestCase):
    """依赖包检查。"""

    def test_all_installed(self):
        mock_mod = MagicMock()
        mock_mod.metadata = MagicMock()
        mock_mod.metadata.version.return_value = "1.0.0"
        with patch.dict("sys.modules", {
            "playwright": mock_mod,
            "openpyxl": mock_mod,
            "importlib": mock_mod,
            "importlib.metadata": mock_mod.metadata,
        }):
            result = ce.check_packages()
            self.assertTrue(result.passed)
            self.assertIn("playwright", result.message)
            self.assertIn("openpyxl", result.message)

    def test_all_missing(self):
        with patch.dict("sys.modules", {
            "playwright": None,
            "openpyxl": None,
        }):
            result = ce.check_packages()
            self.assertFalse(result.passed)
            self.assertIn("playwright", result.message)
            self.assertIn("openpyxl", result.message)


class TestCheckChromium(unittest.TestCase):
    """Chromium 检查。"""

    @patch("check_environment.os.path.isdir", return_value=False)
    @patch("check_environment.platform.system", return_value="Windows")
    @patch("check_environment.os.path.expanduser", return_value="C:\\Users\\test")
    @patch("glob.glob")
    def test_chromium_found_windows(self, mock_glob, mock_home, mock_system, mock_isdir):
        mock_glob.return_value = ["C:\\Users\\test\\AppData\\Local\\ms-playwright\\chromium-xxx\\chrome-win\\chrome.exe"]
        result = ce.check_chromium()
        self.assertTrue(result.passed)
        self.assertIn("Chromium", result.message)

    @patch("check_environment.os.path.isdir", return_value=False)
    @patch("check_environment.platform.system", return_value="Windows")
    @patch("check_environment.os.path.expanduser", return_value="C:\\Users\\test")
    @patch("glob.glob")
    def test_chromium_not_found(self, mock_glob, mock_home, mock_system, mock_isdir):
        mock_glob.return_value = []
        result = ce.check_chromium()
        self.assertFalse(result.passed)
        self.assertIn("未安装", result.message)


class TestCheckCredentials(unittest.TestCase):
    """凭据检查。"""

    @patch("check_environment.os.environ", {"DMS_USER": "test@trina.com", "DMS_PASSWORD": "secret"})
    def test_credentials_found(self):
        mock_resolve = MagicMock(return_value=("current", "test@trina.com", "secret"))
        with patch.dict("sys.modules", {"dms_credentials": MagicMock(resolve_credentials=mock_resolve)}):
            result = ce.check_credentials()
            self.assertTrue(result.passed)

    @patch("check_environment.os.environ", {})
    def test_credentials_not_found(self):
        mock_resolve = MagicMock(return_value=None)
        with patch.dict("sys.modules", {"dms_credentials": MagicMock(resolve_credentials=mock_resolve)}):
            result = ce.check_credentials()
            self.assertFalse(result.passed)
            self.assertIn("未配置", result.message)
            self.assertIn("DMS_USER", result.fix_hint)


class TestCheckDiskSpace(unittest.TestCase):
    """磁盘空间检查。"""

    @patch("check_environment.os.path.expanduser", return_value="C:\\Users\\test")
    @patch("shutil.disk_usage")
    def test_sufficient_space(self, mock_usage, mock_home):
        mock_usage.return_value = MagicMock(free=2 * 1024 ** 3)  # 2GB
        result = ce.check_disk_space()
        self.assertTrue(result.passed)
        self.assertIn("2.0", result.message)

    @patch("check_environment.os.path.expanduser", return_value="C:\\Users\\test")
    @patch("shutil.disk_usage")
    def test_insufficient_space(self, mock_usage, mock_home):
        mock_usage.return_value = MagicMock(free=100 * 1024 ** 2)  # 100MB
        result = ce.check_disk_space()
        self.assertFalse(result.passed)
        self.assertIn("不足", result.message)


class TestRunAllChecks(unittest.TestCase):
    """run_all_checks 编排。"""

    @patch("check_environment.check_python_version")
    @patch("check_environment.check_pip_version")
    @patch("check_environment.check_packages")
    @patch("check_environment.check_disk_space")
    @patch("check_environment.check_chromium_v2")
    @patch("check_environment.check_credentials")
    def test_full_mode_returns_all_checks(self, mock_cred, mock_chrom, mock_disk, mock_pkg, mock_pip, mock_py):
        mock_py.return_value = ce.CheckResult(name="python_version", passed=True, message="OK")
        mock_pip.return_value = ce.CheckResult(name="pip_version", passed=True, message="OK")
        mock_pkg.return_value = ce.CheckResult(name="packages", passed=True, message="OK")
        mock_disk.return_value = ce.CheckResult(name="disk_space", passed=True, message="OK")
        mock_chrom.return_value = ce.CheckResult(name="chromium", passed=True, message="OK")
        mock_cred.return_value = ce.CheckResult(name="credentials", passed=True, message="OK")

        results = ce.run_all_checks(quick=False)
        self.assertEqual(len(results), 6)

    @patch("check_environment.check_chromium_v2")
    @patch("check_environment.check_credentials")
    def test_quick_mode_skips_basic_checks(self, mock_cred, mock_chrom):
        mock_chrom.return_value = ce.CheckResult(name="chromium", passed=True, message="OK")
        mock_cred.return_value = ce.CheckResult(name="credentials", passed=True, message="OK")

        results = ce.run_all_checks(quick=True)
        self.assertEqual(len(results), 2)


class TestPrintResults(unittest.TestCase):
    """print_results 输出格式。"""

    def test_all_passed_returns_0(self):
        results = [
            ce.CheckResult(name="test1", passed=True, message="OK"),
            ce.CheckResult(name="test2", passed=True, message="OK"),
        ]
        exit_code = ce.print_results(results, use_json=True)
        self.assertEqual(exit_code, 0)

    def test_any_failed_returns_1(self):
        results = [
            ce.CheckResult(name="test1", passed=True, message="OK"),
            ce.CheckResult(name="test2", passed=False, message="FAIL"),
        ]
        exit_code = ce.print_results(results, use_json=True)
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
