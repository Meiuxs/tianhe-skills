#!/usr/bin/env python3
"""Role: 技能目录自定位 — 通过 __file__ 确定本 skill 的安装根目录。
不依赖任何 Agent 特定的路径扫描，跨平台兼容（Windows / Linux / macOS）。

用法：
  # 直接运行（打印 skill 根目录路径）
  python detect_skill_dir.py

  # 作为模块导入
  from detect_skill_dir import get_skill_dir
  path = get_skill_dir()

原理：
  本脚本位于 <skill_root>/scripts/detect_skill_dir.py，
  dirname(dirname(__file__)) 即为 skill 根目录。
"""

import os
import sys


def get_skill_dir() -> str:
    """自定位 skill 根目录。

    脚本路径: <skill_root>/scripts/detect_skill_dir.py
    → dirname(dirname(__file__)) = skill_root

    Returns:
        str: skill 根目录的绝对路径（跨平台，Windows 用 \\, Linux/Mac 用 /）

    Raises:
        RuntimeError: 脚本被移动到意外位置时
    """
    # __file__ 是脚本的绝对路径（Python 自动解析）
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.dirname(scripts_dir)

    # 轻量验证：检查 scripts/ 目录是否存在（避免误移位置）
    scripts_name = os.path.basename(scripts_dir)
    if scripts_name != 'scripts':
        raise RuntimeError(
            f'detect_skill_dir.py 不在 scripts/ 目录下（当前: {scripts_dir}）'
        )

    return skill_dir


def main():
    try:
        print(get_skill_dir())
    except RuntimeError as e:
        print(f'[错误] {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
