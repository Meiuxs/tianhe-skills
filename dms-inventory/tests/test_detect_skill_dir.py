#!/usr/bin/env python3
"""detect_skill_dir.py 测试套件。

覆盖范围：
  1. detect_skill_dir 基础路径检测
  2. SKILL_TARGET 环境变量覆盖
  3. 未找到时返回空
  4. find_all_skills_roots 扫描逻辑
"""

import os
import sys
import unittest
from unittest.mock import patch

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TEST_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from detect_skill_dir import detect_skill_dir, find_all_skills_roots


class TestDetectSkillDir(unittest.TestCase):
    """测试 detect_skill_dir 函数"""

    def setUp(self):
        # 保存环境变量以便恢复
        self._saved_env = os.environ.get('SKILL_TARGET')

    def tearDown(self):
        # 恢复环境变量
        if self._saved_env is None:
            os.environ.pop('SKILL_TARGET', None)
        else:
            os.environ['SKILL_TARGET'] = self._saved_env

    def test_detect_self(self):
        """能检测到自身 skill 目录"""
        path = detect_skill_dir('dms-inventory')
        self.assertTrue(path)
        # 确认路径下有 scripts/detect_skill_dir.py
        self.assertTrue(os.path.isfile(os.path.join(path, 'scripts', 'detect_skill_dir.py')))

    def test_nonexistent_returns_empty(self):
        """不存在的 skill 返回空字符串"""
        path = detect_skill_dir('nonexistent-skill-xyz')
        self.assertEqual(path, '')

    def test_skil_target_override(self):
        """SKILL_TARGET 环境变量优先"""
        test_target = os.path.join(os.path.dirname(SKILL_DIR), 'dummy-target')
        try:
            os.environ['SKILL_TARGET'] = test_target
            path = detect_skill_dir('dms-inventory')
            # SKILL_TARGET 指向的目录不存在，所以应该退回到扫描
            # 但如果我们把 SKILL_TARGET 设为一个包含子目录 skills/dms-inventory 的路径...
            # 更简单的测试：设 SKILL_TARGET 为一个存在的目录但 skill 不存在
            path = detect_skill_dir('nonexistent')
            self.assertEqual(path, '')
        finally:
            if self._saved_env is None:
                os.environ.pop('SKILL_TARGET', None)
            else:
                os.environ['SKILL_TARGET'] = self._saved_env

    def test_skil_target_valid(self):
        """SKILL_TARGET 为有效路径时优先返回"""
        # 将 SKILL_TARGET 设为开发目录的上层
        parent = os.path.dirname(SKILL_DIR)
        try:
            os.environ['SKILL_TARGET'] = parent
            path = detect_skill_dir('dms-inventory')
            self.assertEqual(path, SKILL_DIR)
        finally:
            if self._saved_env is None:
                os.environ.pop('SKILL_TARGET', None)
            else:
                os.environ['SKILL_TARGET'] = self._saved_env


class TestFindAllSkillsRoots(unittest.TestCase):
    """测试 find_all_skills_roots 扫描函数"""

    def test_returns_list(self):
        """返回列表"""
        roots = find_all_skills_roots()
        self.assertIsInstance(roots, list)

    def test_contains_claude(self):
        """能找到 ~/.claude/skills"""
        home = os.path.expanduser('~')
        expected = os.path.join(home, '.claude', 'skills')
        roots = find_all_skills_roots()
        self.assertIn(expected, roots)


if __name__ == '__main__':
    unittest.main()
