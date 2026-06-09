#!/usr/bin/env python3
"""Role: 兼容层 — Windows 终端中文乱码修复。被所有涉及中文输出的脚本自动导入。

Windows 终端中文乱码修复。

在 Windows 上，默认终端编码可能是 GBK（CP936），
导致 Python print() 输出的中文显示为乱码。
此模块强制将 stdout/stderr 设为 UTF-8。

在需要输出中文的脚本中 import 即可：
    import _compat
"""

import os
import sys

if sys.platform == 'win32':
    import io

    # ── 终端环境检测 ──────────────────────────────────────────
    # Git Bash / MSYS2 / WSL 等终端本身支持 UTF-8，
    # 但 Python 仍可能检测到 Windows 控制台编码（如 cp936/GBK），
    # 导致按 GBK 编码输出 → UTF-8 终端解码为乱码。
    # 这里通过环境变量区分终端类型，选择合适的编码。
    _is_unix_like_terminal = bool(
        os.environ.get('MSYSTEM')                       # MSYS2 / Git Bash
        or os.environ.get('TERM', '') not in ('', 'dumb', 'windows')  # 类 Unix 终端
    )

    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream and hasattr(stream, 'buffer'):
            current = stream.encoding or ''
            current_upper = current.upper()

            # 已经是 UTF-8 直接跳过
            if current_upper in ('UTF-8', 'UTF8'):
                continue

            if _is_unix_like_terminal:
                # Git Bash / MSYS2 / WSL：终端支持 UTF-8，强制 UTF-8 输出
                encoding = 'utf-8'
            else:
                # 原生 Windows 控制台（cmd / PowerShell）：
                # 保留控制台编码（如 cp936），仅加 backslashreplace 防崩溃
                encoding = current

            setattr(sys, name, io.TextIOWrapper(
                stream.buffer,
                encoding=encoding,
                errors='backslashreplace'
            ))
