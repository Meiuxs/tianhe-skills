#!/usr/bin/env python3
"""Role: 技能目录检测 — 扫描当前用户下所有 Agent 的 skill 安装目录。
自动发现 ~/ 下所有含 `skills` 子目录的目录（不限 Agent 类型），
兼容 Claude Code、WorkBuddy 等任意将 skills 安装到用户目录下的 Agent。

用法：
  python detect_skill_dir.py <skill_name>
  python detect_skill_dir.py dms-inventory   → 打印完整路径

支持的环境变量：
  SKILL_TARGET  — 手动指定目标目录（优先级最高），如 /path/to/skills
"""

import os
import sys


def find_all_skills_roots() -> list:
    """扫描当前用户 ~/ 下所有含 skills 子目录的目录。

    遍历用户主目录的直属子目录（含隐藏目录如 .claude、.workbuddy 等），
    对每个目录检查其下是否有名为 skills 的子目录，有则收集。

    Returns:
        list[str]: 找到的 skills 目录完整路径列表
    """
    home = os.path.expanduser('~')
    found = []

    try:
        for entry in os.scandir(home):
            if entry.is_dir():
                skills_dir = os.path.join(entry.path, 'skills')
                if os.path.isdir(skills_dir):
                    found.append(skills_dir)
    except PermissionError:
        pass

    return found


def detect_skill_dir(skill_name: str) -> str:
    """检测 skill 安装目录，返回完整路径。

    扫描策略：
      1. SKILL_TARGET 环境变量（手动覆盖，优先级最高）
      2. 扫描当前用户 ~/ 下所有含 skills 目录的位置

    Args:
        skill_name: skill 名称，如 'dms-inventory'

    Returns:
        完整路径，未找到则返回空字符串
    """

    # 1. 环境变量优先（手动覆盖）
    env_target = os.environ.get('SKILL_TARGET')
    if env_target:
        candidate = os.path.join(env_target, skill_name)
        if os.path.isdir(candidate):
            return candidate
        # SKILL_TARGET 可能是 skills 目录的父级，也可能是 skills 本身
        candidate2 = os.path.join(env_target, 'skills', skill_name)
        if os.path.isdir(candidate2):
            return candidate2

    # 2. 扫描用户目录下所有 skills 目录
    for skills_root in find_all_skills_roots():
        candidate = os.path.join(skills_root, skill_name)
        if os.path.isdir(candidate):
            return candidate

    return ''


def main():
    if len(sys.argv) < 2:
        print('[错误] 请指定 skill 名称，如: python detect_skill_dir.py dms-inventory',
              file=sys.stderr)
        sys.exit(1)

    skill_name = sys.argv[1]
    path = detect_skill_dir(skill_name)

    if path:
        print(path)
    else:
        found_dirs = find_all_skills_roots()
        if found_dirs:
            scanned = ', '.join(found_dirs)
        else:
            scanned = '（未找到任何 skills 目录）'
        print(
            f'[错误] 未找到 skill "{skill_name}" 的安装目录\n'
            f'  已扫描目录下的 skills/ 子目录: {scanned}\n'
            f'  提示: 可通过 SKILL_TARGET 环境变量指定目录',
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
