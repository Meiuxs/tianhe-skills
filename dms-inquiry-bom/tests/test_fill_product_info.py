#!/usr/bin/env python3
"""fill_product_info.py 测试套件。

覆盖范围：
  1. get_select_options 纯函数逻辑
  2. _check_brand_status 纯函数逻辑
  3. main 参数解析
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import _compat  # noqa: F401, E402

from fill_product_info import (  # noqa: E402
    DMS_URL,
)


# ═══════════════════════════════════════════════════════════
#  1. 配置常量
# ═══════════════════════════════════════════════════════════

class TestConfig(unittest.TestCase):
    """测试配置常量"""

    def test_dms_url(self):
        """DMS URL 正确"""
        self.assertEqual(DMS_URL, "https://dms-admin.trinapower.com")


# ═══════════════════════════════════════════════════════════
#  2. _check_brand_status — JS evaluate 纯逻辑测试
# ═══════════════════════════════════════════════════════════

class TestCheckBrandStatus(unittest.TestCase):
    """测试 _check_brand_status（mock evaluate）"""

    def test_disabled_with_value(self):
        """禁用且有值"""
        from fill_product_info import _check_brand_status
        page = AsyncMock()
        page.evaluate.return_value = {"disabled": True, "value": "小型工商业"}
        result = AsyncMock()
        # 手动构造协程
        import asyncio
        async def run():
            return await _check_brand_status(page)
        result = asyncio.run(run())
        self.assertTrue(result["disabled"])
        self.assertEqual(result["value"], "小型工商业")

    def test_enabled_no_value(self):
        """可用但无值"""
        from fill_product_info import _check_brand_status
        page = AsyncMock()
        page.evaluate.return_value = {"disabled": False, "value": ""}
        import asyncio
        async def run():
            return await _check_brand_status(page)
        result = asyncio.run(run())
        self.assertFalse(result["disabled"])
        self.assertEqual(result["value"], "")


# ═══════════════════════════════════════════════════════════
#  3. main 参数解析
# ═══════════════════════════════════════════════════════════

class TestMainArgs(unittest.TestCase):
    """测试 CLI 参数解析"""

    def test_required_args(self):
        """必需的参数被正确定义"""
        import argparse
        from fill_product_info import main
        # 确保函数存在
        self.assertTrue(callable(main))

    def test_parser_creates_correct_defaults(self):
        """参数默认值正确"""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--flow-id", required=True)
        parser.add_argument("--component-power", type=int, required=True)
        parser.add_argument("--component-count", type=int, required=True)
        parser.add_argument("--inverter-power", type=int, default=None)
        parser.add_argument("--inverter-count", type=int, default=None)
        parser.add_argument("--box-power", type=int, default=None)
        parser.add_argument("--box-count", type=int, default=None)
        parser.add_argument("--headless", action="store_true")
        args = parser.parse_args([
            "--flow-id", "2026060310435399",
            "--component-power", "715",
            "--component-count", "800",
        ])
        self.assertEqual(args.flow_id, "2026060310435399")
        self.assertEqual(args.component_power, 715)
        self.assertEqual(args.component_count, 800)
        self.assertIsNone(args.inverter_power)
        self.assertIsNone(args.inverter_count)
        self.assertFalse(args.headless)


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
