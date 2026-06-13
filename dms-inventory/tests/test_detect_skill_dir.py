#!/usr/bin/env python3
"""detect_skill_dir.py 测试套件（自定位版）。

覆盖范围：
  1. get_skill_dir 返回有效路径
  2. 返回路径下有 scripts/ 目录
  3. 跨平台路径格式
"""

import os
import sys
import unittest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from detect_skill_dir import get_skill_dir


class TestGetSkillDir(unittest.TestCase):
    """测试 get_skill_dir 自定位函数"""

    def test_returns_non_empty_string(self):
        """返回非空字符串"""
        path = get_skill_dir()
        self.assertTrue(path)
        self.assertIsInstance(path, str)

    def test_returns_absolute_path(self):
        """返回绝对路径（跨平台）"""
        path = get_skill_dir()
        # Windows 以 盘符:\ 开头，Linux/Mac 以 / 开头
        self.assertTrue(os.path.isabs(path))

    def test_path_is_skill_root(self):
        """返回的是 skill 根目录（包含 scripts/ 子目录）"""
        path = get_skill_dir()
        self.assertTrue(os.path.isdir(os.path.join(path, 'scripts')))
        self.assertTrue(os.path.isfile(os.path.join(path, 'scripts', 'detect_skill_dir.py')))

    def test_matches_expected_path(self):
        """返回的路径等于开发目录"""
        path = get_skill_dir()
        self.assertEqual(path, SKILL_DIR)


class TestCrossPlatform(unittest.TestCase):
    """跨平台兼容性测试"""

    def test_path_uses_os_separator(self):
        """路径使用当前 OS 的路径分隔符"""
        path = get_skill_dir()
        # 验证路径中的分隔符与当前系统一致
        self.assertIn(os.sep, path)


if __name__ == '__main__':
    unittest.main()
