#!/usr/bin/env python3
"""DMS 登录凭据与浏览器环境检测（dms-weekly-report 独立版）。

检测顺序（开销从低到高）：
  1. 当前进程环境变量
  2. ~/.bashrc / ~/.bash_profile / ~/.profile（直读 export 行，失败则 bash 兜底）
  3. PowerShell 用户级环境变量
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from typing import Callable

_BASH_AVAILABLE: bool | None = None

SOURCE_LABELS = {
    "current": "当前环境变量",
    "bashrc_direct": "~/.bashrc",
    "bash_profile_direct": "~/.bash_profile",
    "profile_direct": "~/.profile",
    "bash_profile": "bash profile（合并 source）",
    "powershell": "PowerShell 用户环境变量",
}


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
    """从 shell profile 解析 export DMS_USER / DMS_PASSWORD。"""
    if not os.path.isfile(filepath):
        return None, None
    user = password = None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export DMS_USER="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        user = val
                elif line.startswith("export DMS_PASSWORD="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
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
    """直读 profile 文件；失败且 bash 可用时合并 source 兜底。"""
    for path, source in (
        (os.path.expanduser("~/.bashrc"), "bashrc_direct"),
        (os.path.expanduser("~/.bash_profile"), "bash_profile_direct"),
        (os.path.expanduser("~/.profile"), "profile_direct"),
    ):
        user, password = _parse_env_from_file(path)
        if user and password:
            return (source, user, password)

    if not _bash_available():
        return None

    cmd = (
        "source ~/.bashrc 2>/dev/null; "
        "source ~/.bash_profile 2>/dev/null; "
        "source ~/.profile 2>/dev/null; "
        'echo "$DMS_USER|||$DMS_PASSWORD"'
    )
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("|||")
            if len(parts) == 2 and parts[0] and parts[1]:
                return ("bash_profile", parts[0], parts[1])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def check_powershell() -> tuple[str, str, str] | None:
    """从 PowerShell 用户环境变量读取（-NoProfile 加速）。"""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                '[System.Environment]::GetEnvironmentVariable("DMS_USER", "User")'
                ' + "|||" + '
                '[System.Environment]::GetEnvironmentVariable("DMS_PASSWORD", "User")',
            ],
            capture_output=True,
            text=True,
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


def check_chromium() -> bool:
    """轻量级 Chromium 检查——filesystem glob，不启动 Playwright 引擎。"""
    home = os.path.expanduser("~")

    patterns = [
        os.path.join(
            home,
            "AppData",
            "Local",
            "ms-playwright",
            "chromium-*",
            "chrome-win*",
            "chrome.exe",
        ),
        os.path.join(
            home, ".cache", "ms-playwright", "chromium-*", "chrome-linux", "chrome"
        ),
        os.path.join(
            home,
            "Library",
            "Caches",
            "ms-playwright",
            "chromium-*",
            "chrome-mac",
            "Chromium",
        ),
    ]
    for pattern in patterns:
        if glob.glob(pattern):
            print("  [Chromium] ✅ 已安装", file=sys.stderr)
            return True

    print("  [Chromium] ❌ 未安装", file=sys.stderr)
    return False
