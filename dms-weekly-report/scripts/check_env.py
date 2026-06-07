#!/usr/bin/env python3
"""检查 DMS 运行环境。

检查项：
  1. DMS 登录环境变量（当前进程 → shell profiles → PowerShell）
  2. Playwright Chromium 浏览器是否已安装

用法：
  python check_env.py
  python check_env.py --check-browser   # 额外检查 Chromium

输出：
  环境变量：DMS_USER=xxx\nDMS_PASSWORD=xxx 或 NOT_FOUND
  Chromium：✅ 已安装 / ❌ 未安装

优化说明：
  - P0: Win32 API 直读注册表替代 PowerShell 子进程（200ms→1ms）
  - P1: 支持 zsh 系 profile（macOS 默认 shell）
  - P1: 正则解析更多 export 格式（含单引号、无 export、尾部注释）
  - P2: 并行执行 bash + PowerShell 兜底子进程
  - P2: HOME 路径缓存避免重复 expanduser
"""

import os
import re
import sys
import glob
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

# ── 模块级常量 ──

# 预编译正则：export VAR="val" / VAR='val' / VAR=val（支持尾部 # 注释）
# 代替逐行 str.startswith + str.split，单次编译全局复用
_ENV_LINE_RE = re.compile(
    r'^(?:export\s+)?'                       # 可选的 export 关键字
    r'(DMS_USER|DMS_PASSWORD)\s*=\s*'        # 变量名=
    r'(?:'
    r'"((?:[^"\\]|\\.)*)"'                  # 双引号（支持 \" 转义）
    r"|'((?:[^'\\]|\\.)*)'"                 # 单引号（支持 \' 转义）
    r'|(\S+)'                                # 无引号纯值
    r')'
    r'(?:\s+#.*)?\s*$',                     # 行尾 # 注释
    re.MULTILINE,
)

# bash 可用性缓存（只检测一次）
_BASH_AVAILABLE: bool | None = None
# HOME 路径缓存（避免重复 expanduser）
_HOME: str | None = None


def _get_home() -> str:
    """缓存 HOME 路径，避免多次 os.path.expanduser('~') 调用。"""
    global _HOME
    if _HOME is None:
        _HOME = os.path.expanduser("~")
    return _HOME


def _bash_available() -> bool:
    """判断 bash 是否可执行，结果缓存避免重复子进程。"""
    global _BASH_AVAILABLE
    if _BASH_AVAILABLE is not None:
        return _BASH_AVAILABLE
    try:
        subprocess.run(['bash', '-c', 'echo ok'], capture_output=True, timeout=2)
        _BASH_AVAILABLE = True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _BASH_AVAILABLE = False
    return _BASH_AVAILABLE


# ── 环境变量解析 ──

def _parse_env_from_file(filepath: str):
    """从 shell profile 文件解析 DMS_USER / DMS_PASSWORD（正则版）。

    支持格式：
      export DMS_USER="value"
      DMS_USER="value"
      export DMS_USER='value'
      DMS_USER=plainvalue
      所有格式均支持行尾 # 注释

    Returns:
        (user, password) 元组，未找到为 (None, None)
    """
    if not os.path.isfile(filepath):
        return None, None
    user = password = None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _ENV_LINE_RE.match(line)
                if not m:
                    continue
                name, dq, sq, raw = m.group(1, 2, 3, 4)
                val = dq or sq or raw
                # 处理引号内的转义符
                if dq:
                    val = dq.replace('\\"', '"').replace('\\\\', '\\')
                elif sq:
                    val = sq.replace("\\'", "'").replace('\\\\', '\\')
                if val:
                    if name == "DMS_USER":
                        user = val
                    elif name == "DMS_PASSWORD":
                        password = val
    except Exception:
        return None, None
    return user, password


# ── 环境变量来源检测 ──

def check_current_env():
    """检查当前进程环境变量（O(1)，零子进程）。"""
    user = os.environ.get('DMS_USER')
    password = os.environ.get('DMS_PASSWORD')
    if user and password:
        return ('current', user, password)
    return None


def check_shell_profiles():
    """直接解析所有常见 shell profile（零子进程，纯文件 I/O）。

    覆盖 bash 系（.bashrc / .bash_profile / .profile）
    和 zsh 系（.zshenv / .zprofile / .zshrc，macOS Catalina+ 默认 shell）。
    """
    home = _get_home()
    profiles = [
        '.bashrc', '.bash_profile', '.profile',   # bash 系
        '.zshenv', '.zprofile', '.zshrc',          # zsh 系
    ]
    for rc in profiles:
        user, password = _parse_env_from_file(os.path.join(home, rc))
        if user and password:
            return (f"{rc[1:]}_direct", user, password)
    return None


def check_bash_subprocess():
    """bash -c 子进程兜底（需 bash 可用）。

    依次 source 所有 profile，能捕获条件分支（if/fish）中设置的变量，
    弥补直接文件解析的盲区。
    """
    if not _bash_available():
        return None
    cmd = (
        'source ~/.bashrc 2>/dev/null; '
        'source ~/.bash_profile 2>/dev/null; '
        'source ~/.profile 2>/dev/null; '
        'echo "$DMS_USER|||$DMS_PASSWORD"'
    )
    try:
        result = subprocess.run(
            ['bash', '-c', cmd],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return ('bash_subprocess', parts[0], parts[1])
    except Exception:
        pass
    return None


def check_powershell():
    """从 Windows 用户环境变量读取。

    双层降级：
      ① Win32 API 直读注册表 HKCU\Environment（~1ms，零进程）
      ② 兜底 PowerShell -NoProfile 子进程（~50-200ms）
    """
    # ── 快速路径：Win32 API 直读注册表 ──
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                user, _ = winreg.QueryValueEx(key, "DMS_USER")
                password, _ = winreg.QueryValueEx(key, "DMS_PASSWORD")
                if user and password:
                    return ("win32_registry", user, password)
        except (FileNotFoundError, OSError, ImportError):
            pass

    # ── 兜底：PowerShell 子进程 ──
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             '[System.Environment]::GetEnvironmentVariable("DMS_USER", "User")'
             ' + "|||" + '
             '[System.Environment]::GetEnvironmentVariable("DMS_PASSWORD", "User")'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                return ('powershell', parts[0], parts[1])
    except Exception:
        pass
    return None


# ── 浏览器检查 ──

def check_chromium() -> bool:
    """轻量级 Chromium 检查——直接 glob 文件系统，不启动 Playwright 引擎。

    覆盖 Windows / Linux / macOS 三平台安装路径。
    """
    home = _get_home()

    # Windows: ms-playwright/chromium-*/chrome-win*/chrome.exe
    pattern = os.path.join(home, "AppData", "Local", "ms-playwright",
                           "chromium-*", "chrome-win*", "chrome.exe")
    if glob.glob(pattern):
        print("  [Chromium] ✅ 已安装", file=sys.stderr)
        return True

    # Linux: .cache/ms-playwright/chromium-*/chrome-linux/chrome
    pattern_nix = os.path.join(home, ".cache", "ms-playwright",
                               "chromium-*", "chrome-linux", "chrome")
    if glob.glob(pattern_nix):
        print("  [Chromium] ✅ 已安装", file=sys.stderr)
        return True

    # macOS: Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium
    pattern_mac = os.path.join(home, "Library", "Caches", "ms-playwright",
                               "chromium-*", "chrome-mac", "Chromium")
    if glob.glob(pattern_mac):
        print("  [Chromium] ✅ 已安装", file=sys.stderr)
        return True

    print("  [Chromium] ❌ 未安装", file=sys.stderr)
    return False


# ── 主入口 ──

def main():
    """顺序检查所有环境变量来源，可选检查 Chromium。

    检测路径：
      ① 当前进程环境变量（O(1)，零开销）
      ② shell profile 直接解析（纯文件 I/O，零子进程）
      ③ 并行兜底：bash 子进程 + PowerShell 子进程
    """
    import argparse

    parser = argparse.ArgumentParser(description="检查 DMS 运行环境")
    parser.add_argument("--check-browser", action="store_true",
                        help="额外检查 Playwright Chromium")
    args = parser.parse_args()

    # ===== 检查 Chromium（可选）=============
    if args.check_browser:
        print("=" * 40, file=sys.stderr)
        print("  浏览器环境检查", file=sys.stderr)
        print("=" * 40, file=sys.stderr)
        ok = check_chromium()
        if ok:
            print("  ✅ 浏览器环境就绪\n", file=sys.stderr)
        else:
            print("  ❌ 浏览器环境未就绪\n", file=sys.stderr)

    # ===== 检查 DMS 环境变量 ================
    # ① 当前进程（O(1)，零开销）
    result = check_current_env()
    if result:
        source, user, password = result
        print(f"DMS_USER={user}")
        print(f"DMS_PASSWORD={password}")
        print(f"SOURCE={source}", file=sys.stderr)
        return

    # ② shell profile 直接解析（纯文件 I/O，零子进程）
    result = check_shell_profiles()
    if result:
        source, user, password = result
        print(f"DMS_USER={user}")
        print(f"DMS_PASSWORD={password}")
        print(f"SOURCE={source}", file=sys.stderr)
        return

    # ③ 并行兜底（bash + PowerShell 同时跑）
    with ThreadPoolExecutor(max_workers=2) as pool:
        bash_future = pool.submit(check_bash_subprocess)
        ps_future = pool.submit(check_powershell)
        for f in as_completed([bash_future, ps_future]):
            try:
                result = f.result(timeout=5)
            except Exception:
                continue
            if result:
                source, user, password = result
                print(f"DMS_USER={user}")
                print(f"DMS_PASSWORD={password}")
                print(f"SOURCE={source}", file=sys.stderr)
                return

    print("NOT_FOUND")
    print("未找到 DMS 登录环境变量", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
