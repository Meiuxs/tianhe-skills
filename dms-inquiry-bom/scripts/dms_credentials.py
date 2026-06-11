#!/usr/bin/env python3
"""DMS 登录凭据与浏览器环境检测。

统一的凭据查找模块，供 dms-inquiry-bom 所有脚本共用。

检测顺序（开销从低到高）：
  1. 当前进程环境变量（O(1)，零子进程）
  2. shell profile 直接解析（纯文件 I/O，覆盖 bash 系 + zsh 系）
  3. bash -c 子进程兜底（需 bash 可用）
  4. Win32 API 注册表 / PowerShell 用户环境变量

用法：
    # 作为模块导入
    from dms_credentials import get_credentials, source_label, check_chromium, DMS_URL

    # 凭据查找：未找到时 exit(1)
    user, password = get_credentials(on_source=lambda s: print(s))

    # CLI 模式
    python dms_credentials.py --check-browser
"""

from __future__ import annotations

import glob
import os
import platform
import re
import subprocess
import sys
from typing import Callable

# 修复 Windows 中文乱码（仅 CLI 模式需要）
import _compat  # noqa: F401
from _compat import captured_run

# ==================== 全局配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"
"""DMS 系统基础 URL，所有脚本共享此配置。"""

# ── 模块级常量与缓存 ──

# 预编译正则：匹配 export VAR="val" / VAR='val' / VAR=val（支持尾部 # 注释）
_ENV_LINE_RE = re.compile(
    r'^(?:export\s+)?'
    r'(DMS_USER|DMS_PASSWORD)\s*=\s*'
    r'(?:'
    r'"((?:[^"\\]|\\.)*)"'
    r"|'((?:[^'\\]|\\.)*)'"
    r'|(\S+)'
    r')'
    r'(?:\s+#.*)?\s*$',
    re.MULTILINE,
)

# 缓存：bash 可用性（只检测一次）、HOME 路径（避免重复 expanduser）
_BASH_AVAILABLE: bool | None = None
_HOME: str | None = None

# source 键 → 可读标签
SOURCE_LABELS = {
    "current": "当前环境变量",
    "bashrc_direct": "~/.bashrc",
    "bash_profile_direct": "~/.bash_profile",
    "profile_direct": "~/.profile",
    "zshenv_direct": "~/.zshenv",
    "zprofile_direct": "~/.zprofile",
    "zshrc_direct": "~/.zshrc",
    "bash_subprocess": "bash profile（合并 source）",
    "win32_registry": "Windows 注册表",
    "powershell": "PowerShell 用户环境变量",
}


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
        subprocess.run(
            ["bash", "-c", "echo ok"],
            capture_output=True,
            timeout=2,
        )
        _BASH_AVAILABLE = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _BASH_AVAILABLE = False
    return _BASH_AVAILABLE


def _parse_env_from_file(filepath: str) -> tuple[str | None, str | None]:
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
    except OSError:
        return None, None
    return user, password


def check_current_env() -> tuple[str, str, str] | None:
    """检查当前进程环境变量（O(1)，零子进程）。"""
    user = os.environ.get("DMS_USER")
    password = os.environ.get("DMS_PASSWORD")
    if user and password:
        return ("current", user, password)
    return None


def check_bash_profiles() -> tuple[str, str, str] | None:
    """直接解析所有常见 shell profile（纯文件 I/O，零子进程）。

    覆盖 bash 系（.bashrc / .bash_profile / .profile）
    和 zsh 系（.zshenv / .zprofile / .zshrc，macOS Catalina+ 默认 shell）。
    失败且 bash 可用时合并 source 兜底。
    """
    home = _get_home()
    profiles = [
        ('.bashrc', 'bashrc_direct'),
        ('.bash_profile', 'bash_profile_direct'),
        ('.profile', 'profile_direct'),
        ('.zshenv', 'zshenv_direct'),
        ('.zprofile', 'zprofile_direct'),
        ('.zshrc', 'zshrc_direct'),
    ]
    for rc, source in profiles:
        user, password = _parse_env_from_file(os.path.join(home, rc))
        if user and password:
            return (source, user, password)

    # bash 子进程兜底（能捕获条件分支中设置的变量）
    if not _bash_available():
        return None

    cmd = (
        "source ~/.bashrc 2>/dev/null; "
        "source ~/.bash_profile 2>/dev/null; "
        "source ~/.profile 2>/dev/null; "
        'echo "$DMS_USER|||$DMS_PASSWORD"'
    )
    try:
        result = captured_run(
            ["bash", "-c", cmd],
            timeout=2,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("|||")
            if len(parts) == 2 and parts[0] and parts[1]:
                return ("bash_subprocess", parts[0], parts[1])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def check_powershell() -> tuple[str, str, str] | None:
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
        result = captured_run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                '[System.Environment]::GetEnvironmentVariable("DMS_USER", "User")'
                ' + "|||" + '
                '[System.Environment]::GetEnvironmentVariable("DMS_PASSWORD", "User")',
            ],
            timeout=2,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("|||")
            if len(parts) == 2 and parts[0] and parts[1]:
                return ("powershell", parts[0], parts[1])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def resolve_credentials() -> tuple[str, str, str] | None:
    """按开销升序查找凭据，返回 (source, user, password) 或 None。"""
    for checker in (check_current_env, check_bash_profiles, check_powershell):
        result = checker()
        if result:
            return result
    return None


def source_label(source: str) -> str:
    """将内部 source 键转为可读标签。"""
    return SOURCE_LABELS.get(source, source)


def get_credentials(
    *,
    on_source: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """读取 DMS 登录凭据；未找到时打印提示并 exit(1)。"""
    result = resolve_credentials()
    if not result:
        print("[错误] 未配置 DMS_USER / DMS_PASSWORD 环境变量", file=sys.stderr)
        print("  请参照 SKILL.md 的「凭据配置」节进行设置", file=sys.stderr)
        raise SystemExit(1)

    source, user, password = result
    if on_source:
        on_source(source)
    return user, password


def _glob_first(pattern: str) -> str | None:
    """返回匹配 pattern 的第一个路径，或 None。"""
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def _check_chromium_component(component_name: str, label: str,
                               patterns: dict) -> bool:
    """通用 Chromium 组件检查（filesystem glob，不启动 Playwright 引擎）。

    Args:
        component_name: 组件名称（如 "Chromium"、"Headless Shell"），用于输出
        label: 输出标签（如 "[Chromium]"）
        patterns: {platform: glob_pattern} 映射
                  其中 platform 为 sys.platform 值（win32/linux/darwin）

    Returns:
        bool: 是否已安装
    """
    plat = sys.platform
    pattern = patterns.get(plat, patterns.get("win32"))
    matched = _glob_first(pattern)
    if matched:
        # headless shell 还需验证是文件不是目录
        if component_name == "Chromium":
            print(f"  {label} ✅ 已安装", file=sys.stderr)
            return True
        elif os.path.isfile(matched):
            print(f"  {label} ✅ 已安装", file=sys.stderr)
            return True
        else:
            print(f"  {label} ❌ 未安装（路径存在但不可用: {matched}）", file=sys.stderr)
            return False

    print(f"  {label} ❌ 未安装", file=sys.stderr)
    return False


def check_chromium() -> bool:
    """轻量级 Chromium 检查——filesystem glob，不启动 Playwright 引擎。"""
    home = _get_home()
    patterns = {
        "win32": os.path.join(
            home, "AppData", "Local", "ms-playwright",
            "chromium-*", "chrome-win*", "chrome.exe",
        ),
        "linux": os.path.join(
            home, ".cache", "ms-playwright",
            "chromium-*", "chrome-linux", "chrome",
        ),
        "darwin": os.path.join(
            home, "Library", "Caches", "ms-playwright",
            "chromium-*", "chrome-mac", "Chromium",
        ),
    }
    return _check_chromium_component("Chromium", "  [Chromium]", patterns)


def check_chromium_headless_shell() -> bool:
    """轻量级 Chromium Headless Shell 检查——确认可执行文件实际存在。"""
    home = _get_home()
    patterns = {
        "win32": os.path.join(
            home, "AppData", "Local", "ms-playwright",
            "chromium_headless_shell-*", "chrome-headless-shell-win64",
            "chrome-headless-shell.exe",
        ),
        "linux": os.path.join(
            home, ".cache", "ms-playwright",
            "chromium_headless_shell-*", "chrome-linux",
            "chrome-headless-shell",
        ),
        "darwin": os.path.join(
            home, "Library", "Caches", "ms-playwright",
            "chromium_headless_shell-*", "chrome-mac",
            "chrome-headless-shell",
        ),
    }
    return _check_chromium_component("Headless Shell", "  [Headless Shell]", patterns)


# ── CLI 入口 ──


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="检查 DMS 运行环境")
    parser.add_argument("--check-browser", action="store_true",
                        help="额外检查 Playwright Chromium")
    args = parser.parse_args()

    if args.check_browser:
        print("=" * 40, file=sys.stderr)
        print("  浏览器环境检查", file=sys.stderr)
        print("=" * 40, file=sys.stderr)
        chromium_ok = check_chromium()
        headless_ok = check_chromium_headless_shell()

        if chromium_ok:
            print("  ✅ 浏览器环境就绪", file=sys.stderr)
            if not headless_ok:
                print("  ⚠️ headless shell 未安装，--headless 模式不可用", file=sys.stderr)
                print("     如需无头模式请运行:", file=sys.stderr)
                print("     playwright install chromium\n", file=sys.stderr)
            else:
                print("  ✅ 无头模式可用\n", file=sys.stderr)
        else:
            print("  ❌ 浏览器环境未就绪", file=sys.stderr)
            print("  请运行: playwright install chromium", file=sys.stderr)
            print("  或: python -m playwright install chromium\n", file=sys.stderr)

    result = resolve_credentials()
    if result:
        source, user, password = result
        masked = user[:3] + "***" if len(user) > 3 else "***"
        print(f"DMS_USER={masked}")
        print(f"DMS_PASSWORD=****")
        print(f"SOURCE={source_label(source)}", file=sys.stderr)
        return

    print("NOT_FOUND")
    print("未找到 DMS 登录环境变量", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
