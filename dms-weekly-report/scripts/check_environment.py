#!/usr/bin/env python3
"""跨平台运行环境统一检查。

架构定位：
  本模块是环境检查层，被 SKILL.md 步骤 0（最先执行）通过 CLI 调用。
  在执行周报脚本前，一次性检查所有前置条件，Fail-fast 避免中途失败。

检查项（按开销升序）：
  1. Python 版本       — 要求 ≥ 3.9（推荐 3.11+）
  2. pip 版本          — 要求 ≥ 23.0
  3. 依赖包            — playwright、openpyxl 是否已安装
  4. Playwright Chromium — 浏览器二进制是否已下载
  5. DMS 登录凭据      — DMS_USER / DMS_PASSWORD 是否已配置

支持平台：Windows 10+ / macOS 12+ / Linux（含 X11 或 Wayland）

用法：
    # 检查全部（默认）
    python check_environment.py

    # 仅检查凭据和浏览器（跳过基础环境）
    python check_environment.py --quick

    # JSON 输出（供 Agent 解析）
    python check_environment.py --json

输出约定：
  - 全部通过 → exit(0)
  - 任一项失败 → exit(1)，stderr 输出具体问题和修复命令
  - --json 模式 → stdout 输出结构化 JSON，便于 Agent 程序化处理
"""

from __future__ import annotations

import _compat  # noqa: F401 — 必须最先导入，修复 Windows 中文乱码

# PowerShell error stream 用 cp936 解码导致乱码，统一走 stdout
import sys
sys.stderr = sys.stdout

import argparse
import json
import os
import platform
from dataclasses import dataclass, field
from typing import Any
import importlib.metadata

# ── 常量 ──

MIN_PYTHON = (3, 9)
MIN_PIP = (23, 0)
REQUIRED_PACKAGES = ["playwright", "openpyxl"]


# ── 数据结构 ──


@dataclass
class CheckResult:
    """单项检查结果。"""
    name: str
    passed: bool
    message: str = ""
    fix_hint: str = ""  # 修复建议命令
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
        }
        if self.fix_hint:
            d["fix_hint"] = self.fix_hint
        if self.details:
            d["details"] = self.details
        return d


# ── 检查函数 ──


def check_python_version() -> CheckResult:
    """检查 Python 版本是否满足最低要求。"""
    ver = sys.version_info[:2]
    ver_str = f"{ver[0]}.{ver[1]}"
    if ver >= MIN_PYTHON:
        return CheckResult(
            name="python_version",
            passed=True,
            message=f"Python {ver_str} ({sys.executable})",
            details={"version": ver_str, "path": sys.executable},
        )
    return CheckResult(
        name="python_version",
        passed=False,
        message=f"Python {ver_str} 版本过低（{sys.executable}），要求 ≥ {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        fix_hint="请升级 Python 到 3.9 或更高版本",
        details={"version": ver_str, "required": f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"},
    )


def check_pip_version() -> CheckResult:
    """检查 pip 版本。"""
    try:
        import pip
        ver = tuple(int(x) for x in pip.__version__.split(".")[:2])
        ver_str = pip.__version__
        if ver >= MIN_PIP:
            return CheckResult(
                name="pip_version",
                passed=True,
                message=f"pip {ver_str} ({os.path.dirname(pip.__file__)})",
                details={"version": ver_str},
            )
        return CheckResult(
            name="pip_version",
            passed=False,
            message=f"pip {ver_str} 版本过低，要求 ≥ {MIN_PIP[0]}.{MIN_PIP[1]}",
            fix_hint=f"{sys.executable} -m pip install --upgrade pip",
            details={"version": ver_str, "required": f"{MIN_PIP[0]}.{MIN_PIP[1]}"},
        )
    except ImportError:
        return CheckResult(
            name="pip_version",
            passed=False,
            message="pip 未安装",
            fix_hint="请先安装 pip：python -m ensurepip --upgrade",
        )


def check_packages() -> CheckResult:
    """检查必需的 Python 包是否已安装。"""
    missing = []
    installed = []
    for pkg in REQUIRED_PACKAGES:
        try:
            __import__(pkg)
            try:
                ver = importlib.metadata.version(pkg)
            except importlib.metadata.PackageNotFoundError:
                ver = "?"
            installed.append(f"{pkg} {ver}")
        except ImportError:
            missing.append(pkg)

    if not missing:
        return CheckResult(
            name="packages",
            passed=True,
            message=f"已安装: {', '.join(installed)}",
            details={"installed": installed},
        )

    return CheckResult(
        name="packages",
        passed=False,
        message=f"缺少依赖包: {', '.join(missing)}",
        fix_hint=f"{sys.executable} -m pip install {' '.join(missing)}",
        details={"missing": missing, "installed": installed},
    )


def check_chromium() -> CheckResult:
    """检查 Playwright Chromium 浏览器是否已安装。

    跨平台路径检测，不启动 Playwright 引擎（轻量级）。
    同时检查 chromium 和 chromium_headless_shell 两个变体。
    launch_persistent_context 在 Windows 上无论 headless 参数如何都需要 headless-shell。
    """
    import glob

    home = os.path.expanduser("~")
    system = platform.system()

    # 两个变体都要检查
    variant_patterns: dict[str, list[str]] = {
        "chromium": [],
        "chromium_headless_shell": [],
    }

    if system == "Windows":
        pw_dir = os.path.join(home, "AppData", "Local", "ms-playwright")
        variant_patterns["chromium"] = [
            os.path.join(pw_dir, "chromium-*", "chrome-win*", "chrome.exe"),
        ]
        variant_patterns["chromium_headless_shell"] = [
            os.path.join(pw_dir, "chromium_headless_shell-*", "chrome-win", "headless_shell.exe"),
        ]
    elif system == "Darwin":
        pw_dir = os.path.join(home, "Library", "Caches", "ms-playwright")
        variant_patterns["chromium"] = [
            os.path.join(pw_dir, "chromium-*", "chrome-mac", "Chromium"),
        ]
        variant_patterns["chromium_headless_shell"] = [
            os.path.join(pw_dir, "chromium_headless_shell-*", "chrome-mac", "headless_shell"),
        ]
    elif system == "Linux":
        pw_dir = os.path.join(home, ".cache", "ms-playwright")
        variant_patterns["chromium"] = [
            os.path.join(pw_dir, "chromium-*", "chrome-linux", "chrome"),
        ]
        variant_patterns["chromium_headless_shell"] = [
            os.path.join(pw_dir, "chromium_headless_shell-*", "chrome-linux", "headless_shell"),
        ]

    found_chromium = any(glob.glob(p) for p in variant_patterns["chromium"])
    found_headless = any(glob.glob(p) for p in variant_patterns["chromium_headless_shell"])

    if found_chromium and found_headless:
        return CheckResult(
            name="chromium",
            passed=True,
            message=f"Chromium + headless-shell 已安装 ({pw_dir})",
            details={"platform": system, "chromium": True, "headless_shell": True},
        )

    _MIRROR_HINT = (
        "set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
        f" && {sys.executable} -m playwright install chromium"
    )

    if found_chromium and not found_headless:
        return CheckResult(
            name="chromium",
            passed=False,
            message=f"Chromium 已安装但 headless-shell 缺失，安装目录: {pw_dir}",
            fix_hint=_MIRROR_HINT,
            details={"platform": system, "chromium": True, "headless_shell": False},
        )

    # 检查目录是否存在但浏览器未下载
    if os.path.isdir(pw_dir):
        return CheckResult(
            name="chromium",
            passed=False,
            message=f"Playwright 目录已存在但浏览器未下载: {pw_dir}",
            fix_hint=_MIRROR_HINT,
            details={"platform": system, "chromium": False, "headless_shell": False},
        )

    return CheckResult(
        name="chromium",
        passed=False,
        message=f"Playwright Chromium 未安装，预期目录: {pw_dir}",
        fix_hint=_MIRROR_HINT,
        details={"platform": system, "chromium": False, "headless_shell": False},
    )


def check_chromium_v2() -> CheckResult:
    """检查 Playwright Chromium —— 使用 dms_credentials 中的实现。

    如果 dms_credentials 模块可用，复用其 check_chromium()；
    否则回退到本地 glob 检测。
    """
    home = os.path.expanduser("~")
    system = platform.system()
    if system == "Windows":
        pw_dir = os.path.join(home, "AppData", "Local", "ms-playwright")
    elif system == "Darwin":
        pw_dir = os.path.join(home, "Library", "Caches", "ms-playwright")
    else:
        pw_dir = os.path.join(home, ".cache", "ms-playwright")

    try:
        from dms_credentials import check_chromium as _check
        ok = _check()
        if ok:
            return CheckResult(
                name="chromium",
                passed=True,
                message=f"Chromium 已安装 ({pw_dir})",
            )
        if os.path.isdir(pw_dir):
            return CheckResult(
                name="chromium",
                passed=False,
                message=f"Playwright 目录已存在但浏览器未下载: {pw_dir}",
                fix_hint=(
                    "set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
                    f" && {sys.executable} -m playwright install chromium"
                ),
            )
        return CheckResult(
            name="chromium",
            passed=False,
            message=f"Playwright Chromium 未安装，预期目录: {pw_dir}",
            fix_hint=(
                "set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright"
                f" && {sys.executable} -m playwright install chromium"
            ),
        )
    except ImportError:
        return check_chromium()


def check_credentials() -> CheckResult:
    """检查 DMS 登录凭据是否已配置。

    跨平台检测顺序（复用 dms_credentials 模块）：
      1. 当前进程环境变量
      2. shell profile 文件（bash/zsh）
      3. bash -c 子进程兜底
      4. Windows 注册表 / PowerShell
    """
    try:
        from dms_credentials import resolve_credentials, source_label
        result = resolve_credentials()
        if result:
            source, user, password = result
            masked = user[:3] + "***" if len(user) > 3 else "***"
            return CheckResult(
                name="credentials",
                passed=True,
                message=f"凭据就绪 (来源: {source_label(source)})",
                details={"source": source, "user_masked": masked},
            )
        return CheckResult(
            name="credentials",
            passed=False,
            message="未配置 DMS_USER / DMS_PASSWORD 环境变量",
            fix_hint=(
                "临时设置: export DMS_USER=\"your_email@trinapower.com\" "
                "DMS_PASSWORD=\"your_password\"\n"
                "  永久设置: 追加到 ~/.bashrc 后 source ~/.bashrc"
            ),
        )
    except ImportError:
        # dms_credentials 模块不可用，直接检查环境变量
        user = os.environ.get("DMS_USER")
        password = os.environ.get("DMS_PASSWORD")
        if user and password:
            masked = user[:3] + "***" if len(user) > 3 else "***"
            return CheckResult(
                name="credentials",
                passed=True,
                message=f"凭据就绪 (来源: 当前环境变量)",
                details={"source": "current", "user_masked": masked},
            )
        return CheckResult(
            name="credentials",
            passed=False,
            message="未配置 DMS_USER / DMS_PASSWORD 环境变量",
            fix_hint=(
                "export DMS_USER=\"your_email@trinapower.com\" "
                "DMS_PASSWORD=\"your_password\""
            ),
        )


def check_disk_space() -> CheckResult:
    """检查磁盘剩余空间（Playwright 浏览器约需 400MB）。"""
    try:
        import shutil
        usage = shutil.disk_usage(os.path.expanduser("~"))
        free_gb = usage.free / (1024 ** 3)
        if free_gb >= 0.5:
            return CheckResult(
                name="disk_space",
                passed=True,
                message=f"磁盘剩余 {free_gb:.1f} GB",
                details={"free_gb": round(free_gb, 2)},
            )
        return CheckResult(
            name="disk_space",
            passed=False,
            message=f"磁盘剩余不足 ({free_gb:.2f} GB)，Playwright 浏览器需约 400MB",
            fix_hint="请清理磁盘空间后重试",
            details={"free_gb": round(free_gb, 2)},
        )
    except Exception:
        # 某些平台可能不支持 disk_usage
        return CheckResult(
            name="disk_space",
            passed=True,
            message="磁盘空间检查跳过（平台不支持）",
        )


# ── 编排 ──


def run_all_checks(quick: bool = False) -> list[CheckResult]:
    """执行全部检查，返回结果列表。

    Args:
        quick: 快速模式，仅检查凭据和浏览器（跳过 Python/pip/包/磁盘）
    """
    checks: list[CheckResult] = []

    if not quick:
        checks.append(check_python_version())
        checks.append(check_pip_version())
        checks.append(check_packages())
        checks.append(check_disk_space())

    checks.append(check_chromium_v2())
    checks.append(check_credentials())

    return checks


# ── 输出格式化 ──

_SYMBOL_PASS = "\u2705"
_SYMBOL_FAIL = "\u274c"
_SYMBOL_WARN = "\u26a0\ufe0f"


def print_results(results: list[CheckResult], *, use_json: bool = False) -> int:
    """打印检查结果，返回 exit code（0=全部通过, 1=有失败）。"""

    if use_json:
        output = {
            "passed": all(r.passed for r in results),
            "checks": [r.to_dict() for r in results],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output["passed"] else 1

    # 人类可读输出
    all_passed = all(r.passed for r in results)
    failed_count = sum(1 for r in results if not r.passed)

    print("=" * 50, file=sys.stderr)
    print("  DMS 周报 — 运行环境检查", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    for r in results:
        sym = _SYMBOL_PASS if r.passed else _SYMBOL_FAIL
        print(f"  {sym} {r.message}", file=sys.stderr)

    print("-" * 50, file=sys.stderr)

    if all_passed:
        print("  \u2705 全部检查通过，可以开始执行周报脚本", file=sys.stderr)
    else:
        print(f"  \u274c {failed_count} 项检查未通过，请修复后重试：", file=sys.stderr)
        print("", file=sys.stderr)
        for r in results:
            if not r.passed and r.fix_hint:
                print(f"  [{r.name}] 修复方法：", file=sys.stderr)
                for line in r.fix_hint.split("\n"):
                    print(f"    {line}", file=sys.stderr)

    print("=" * 50, file=sys.stderr)
    return 0 if all_passed else 1


# ── CLI ──


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DMS 周报 — 跨平台运行环境检查",
        epilog=(
            "检查项：\n"
            "  1. Python 版本（≥ 3.9）\n"
            "  2. pip 版本（≥ 23.0）\n"
            "  3. 依赖包（playwright、openpyxl）\n"
            "  4. Playwright Chromium 浏览器\n"
            "  5. DMS 登录凭据（DMS_USER / DMS_PASSWORD）\n"
            "\n"
            "支持平台：Windows 10+ / macOS 12+ / Linux\n"
            "\n"
            "示例:\n"
            "  python check_environment.py              # 完整检查\n"
            "  python check_environment.py --quick       # 仅检查凭据和浏览器\n"
            "  python check_environment.py --json        # JSON 输出"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quick", action="store_true",
                        help="快速模式：仅检查凭据和浏览器（跳过 Python/pip/包/磁盘）")
    parser.add_argument("--json", action="store_true",
                        help="JSON 输出（供 Agent 程序化解析）")
    args = parser.parse_args()

    results = run_all_checks(quick=args.quick)
    exit_code = print_results(results, use_json=args.json)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
