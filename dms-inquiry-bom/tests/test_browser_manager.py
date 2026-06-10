#!/usr/bin/env python3
"""browser_manager.py 测试套件。

覆盖范围：
  1. is_on_login_page 判断逻辑（mock Page）
  2. get_credentials 委派（mock dms_credentials）
  3. BrowserManager 配置属性
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from browser_manager import (  # noqa: E402
    is_on_login_page,
    BrowserManager,
    DMS_URL,
    USER_DATA_DIR,
)


# ═══════════════════════════════════════════════════════════
#  1. is_on_login_page
# ═══════════════════════════════════════════════════════════

class TestIsOnLoginPage(unittest.TestCase):
    """测试 is_on_login_page"""

    def test_on_login_page(self):
        """在登录页时返回 True"""
        page = MagicMock()
        page.url = "https://iauth.trinapower.com/login"
        self.assertTrue(is_on_login_page(page))

    def test_not_on_login_page(self):
        """不在登录页时返回 False"""
        page = MagicMock()
        page.url = f"{DMS_URL}/#/process/process_center"
        self.assertFalse(is_on_login_page(page))

    def test_empty_url(self):
        """空 URL 返回 False"""
        page = MagicMock()
        page.url = ""
        self.assertFalse(is_on_login_page(page))


# ═══════════════════════════════════════════════════════════
#  2. get_credentials
# ═══════════════════════════════════════════════════════════

class TestGetCredentials(unittest.TestCase):
    """测试 get_credentials（mock 委派）"""

    def test_returns_from_dms_credentials(self):
        """从 dms_credentials 获取凭据"""
        import browser_manager as bm
        # 提取模块中缓存的 credentials 函数引用
        with patch("dms_credentials.get_credentials") as mock_get:
            mock_get.return_value = ("test@test.com", "password123")
            from browser_manager import get_credentials
            result = get_credentials()
            self.assertEqual(result, ("test@test.com", "password123"))
            mock_get.assert_called_once()


# ═══════════════════════════════════════════════════════════
#  3. BrowserManager 配置
# ═══════════════════════════════════════════════════════════

class TestBrowserManagerConfig(unittest.TestCase):
    """测试 BrowserManager 初始化配置"""

    def test_default_headless_false(self):
        """默认非无头模式"""
        mgr = BrowserManager()
        self.assertFalse(mgr.headless)

    def test_custom_headless(self):
        """可设置无头模式"""
        mgr = BrowserManager(headless=True)
        self.assertTrue(mgr.headless)

    def test_initial_state(self):
        """初始化后各属性为 None"""
        mgr = BrowserManager()
        self.assertIsNone(mgr._playwright)
        self.assertIsNone(mgr._browser)
        self.assertIsNone(mgr._context)
        self.assertFalse(mgr._is_logged_in)
        self.assertEqual(mgr._pages, [])

    def test_user_data_dir_exists(self):
        """用户数据目录路径已定义"""
        self.assertIsNotNone(USER_DATA_DIR)
        self.assertIn(".dms_browser_data", str(USER_DATA_DIR))


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
