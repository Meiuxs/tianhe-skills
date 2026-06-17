#!/usr/bin/env python3
"""编码兼容性统一处理模块。

所有跨平台、跨终端的编码问题集中在此处理。
其他脚本只需 ``import _compat`` 即可自动获得 IO 编码修复，
并通过 ``_compat.captured_run()`` 确保子进程编码正确。

覆盖范围：
  1. stdout/stderr —— 强制 UTF-8 输出（避免 cp936 终端中文乱码）
  2. stdin          —— 强制 UTF-8 输入（确保 input() 正确读取中文）
  3. subprocess     —— ``captured_run()`` 封装，默认 UTF-8 捕获子进程输出
  4. ENCODING       —— 模块级常量，各脚本在 open() / json 等场景引用

用法：
    import _compat
    from _compat import captured_run, ENCODING

    # 子进程捕获（自动 UTF-8）
    result = captured_run(["bash", "-c", "echo 中文"])

    # 文件读写（引用统一编码常量）
    with open("file.txt", "w", encoding=ENCODING) as f:
        f.write("中文内容")
"""

import subprocess
import sys

# ── 统一编码常量 ────────────────────────────────────────────
# 所有 Python I/O 操作均以此为准，未来如需切编码只改此处
ENCODING: str = "utf-8"

# ── 子进程捕获工具 ──────────────────────────────────────────


def captured_run(*args, capture_output: bool = True,
                 encoding: str = ENCODING, **kwargs) -> subprocess.CompletedProcess:
    """默认以 UTF-8 模式捕获子进程输出，避免 Windows 上 cp936 乱码。

    等价于 ``subprocess.run(*args, capture_output=True, encoding='utf-8', **kwargs)``。
    调用方无需操心 ``text=True`` / ``universal_newlines`` 等参数，
    设定了 ``encoding`` 即自动启用文本模式。

    如需二进制读取，传入 ``encoding=None`` 即可回退到 bytes 模式。

    Args:
        *args: 位置参数，同 subprocess.run
        capture_output: 是否捕获 stdout/stderr，默认 True
        encoding: 解码编码，默认 UTF-8；设为 None 则使用 bytes 模式
        **kwargs: 其余参数同 subprocess.run

    Returns:
        subprocess.CompletedProcess
    """
    return subprocess.run(
        *args,
        capture_output=capture_output,
        encoding=encoding,
        **kwargs,
    )


# ── IO 流编码自动修复（仅在 Windows 上生效）────────────────
#
# 编码检测逻辑：
#   1. 读取 sys.stdout/stderr/stdin 的当前编码
#   2. 已为 UTF-8（如 Linux/macOS/Windows Terminal UTF-8 模式）→ 不做任何修改
#   3. 非 UTF-8（如 Windows 默认 cp936/GBK）→ 强制重包装为 UTF-8
#
# 适用场景说明：
#   本 Skill 为 AI Agent/Codex 驱动设计，脚本输出通过管道被 Agent 读取。
#   Agent 需要 UTF-8 编码的文本，而非系统本地编码（cp936/GBK），
#   因此即使交互终端可能显示异常（因终端期望 cp936），也优先保证 Agent 读取正确。
#   通过 errors='backslashreplace' 确保：无法显示的字符转为 \uXXXX 形式输出，不丢失信息。

if sys.platform == 'win32':
    import io

    # 设置控制台代码页为 UTF-8，避免 PowerShell error stream 用 cp936 解码
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass

    # 修复 stdout / stderr —— 将非 UTF-8 流重包装为 UTF-8
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream and hasattr(stream, 'buffer'):
            encoding = stream.encoding or ''
            if encoding.upper() not in ('UTF-8', 'UTF8'):
                setattr(sys, name, io.TextIOWrapper(
                    stream.buffer,
                    encoding=ENCODING,
                    errors='backslashreplace'
                ))
    # 修复 stdin —— 确保 input() 能正确读取中文输入
    # 仅对交互式终端（TTY）重包装；管道/重定向场景跳过，避免断开管道
    stream = getattr(sys, 'stdin', None)
    if stream and hasattr(stream, 'buffer') and stream.isatty():
        encoding = stream.encoding or ''
        if encoding.upper() not in ('UTF-8', 'UTF8'):
            setattr(sys, 'stdin', io.TextIOWrapper(
                stream.buffer,
                encoding=ENCODING,
                errors='replace',
            ))
