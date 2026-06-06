#!/usr/bin/env python3
"""并行检查 DMS 运行环境。

检查项：
  1. DMS 登录环境变量（从当前环境/bashrc/bash_profile/profile/PowerShell）
  2. Playwright Chromium 浏览器是否已安装

用法：
  python check_env.py
  python check_env.py --check-browser   # 额外检查 Chromium

输出：
  环境变量：DMS_USER=xxx\nDMS_PASSWORD=xxx 或 NOT_FOUND
  Chromium：✅ 已安装 / ❌ 未安装
"""

import os
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402


def check_current_env():
    """检查当前环境变量"""
    user = os.environ.get('DMS_USER')
    password = os.environ.get('DMS_PASSWORD')
    if user and password:
        return ('current', user, password)
    return None


def check_bashrc():
    """从bashrc加载环境变量"""
    try:
        result = subprocess.run(
            ['bash', '-c', 'source ~/.bashrc 2>/dev/null && echo "$DMS_USER|||$DMS_PASSWORD"'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return ('bashrc', parts[0], parts[1])
    except Exception:
        pass
    return None


def check_bash_profile():
    """从bash_profile加载环境变量"""
    try:
        result = subprocess.run(
            ['bash', '-c', 'source ~/.bash_profile 2>/dev/null && echo "$DMS_USER|||$DMS_PASSWORD"'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return ('bash_profile', parts[0], parts[1])
    except Exception:
        pass
    return None


def check_profile():
    """从~/.profile加载环境变量"""
    try:
        result = subprocess.run(
            ['bash', '-c', 'source ~/.profile 2>/dev/null && echo "$DMS_USER|||$DMS_PASSWORD"'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return ('profile', parts[0], parts[1])
    except Exception:
        pass
    return None


def check_chromium() -> bool:
    """检查 Playwright Chromium 是否已安装。

    Returns:
        True 如果 Chromium 可用，否则 False
    """
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, '-c', '''
from playwright.sync_api import sync_playwright
try:
    p = sync_playwright().start()
    executable_path = p.chromium.executable_path
    p.stop()
    # 检查浏览器文件是否存在
    import os
    if os.path.exists(executable_path):
        print(f"Chromium 可执行文件: {executable_path}")
        exit(0)
    else:
        print(f"Chromium 路径存在但文件缺失: {executable_path}")
        exit(1)
except Exception as e:
    print(f"Chromium 未安装或不可用: {e}")
    exit(1)
'''],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  [Chromium] ✅ {result.stdout.strip().split(chr(10))[0] if result.stdout else '已安装'}", file=sys.stderr)
            return True
        else:
            print(f"  [Chromium] ❌ {result.stdout.strip() if result.stdout else '未安装'}", file=sys.stderr)
            return False
    except FileNotFoundError:
        print("  [Chromium] ❌ Playwright 未安装", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("  [Chromium] ⏳ 检测超时（视为未安装）", file=sys.stderr)
        return False


def check_powershell():
    """从PowerShell用户环境变量读取"""
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             '[System.Environment]::GetEnvironmentVariable("DMS_USER", "User") + "|||" + [System.Environment]::GetEnvironmentVariable("DMS_PASSWORD", "User")'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return ('powershell', parts[0], parts[1])
    except Exception:
        pass
    return None


def main():
    """并行检查所有环境变量来源，可选检查 Chromium。"""
    import argparse

    parser = argparse.ArgumentParser(description="检查 DMS 运行环境")
    parser.add_argument("--check-browser", action="store_true", help="额外检查 Playwright Chromium")
    args = parser.parse_args()

    # ===== 检查 Chromium（可选） =====
    if args.check_browser:
        print("=" * 40, file=sys.stderr)
        print("  浏览器环境检查", file=sys.stderr)
        print("=" * 40, file=sys.stderr)
        chromium_ok = check_chromium()
        if chromium_ok:
            print("  ✅ 浏览器环境就绪", file=sys.stderr)
        else:
            print("  ❌ 浏览器环境未就绪", file=sys.stderr)
            print("  请运行: playwright install chromium", file=sys.stderr)
            print("  或: python -m playwright install chromium", file=sys.stderr)
        print(file=sys.stderr)

    # ===== 检查 DMS 环境变量 =====
    checkers = [
        check_current_env,
        check_bashrc,
        check_bash_profile,
        check_profile,
        check_powershell
    ]

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(checker): checker.__name__ for checker in checkers}

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    source, user, password = result
                    print(f"DMS_USER={user}")
                    print(f"DMS_PASSWORD={password}")
                    print(f"SOURCE={source}", file=sys.stderr)
                    # 如果还检查了浏览器，这里正常退出
                    return
            except Exception:
                continue

    print("NOT_FOUND")
    print("未找到 DMS 登录环境变量", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
