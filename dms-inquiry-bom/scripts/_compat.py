#!/usr/bin/env python3
"""Windows 终端中文乱码修复。

在 Windows 上，默认终端编码可能是 GBK（CP936），
导致 Python print() 输出的中文显示为乱码。
此模块强制将 stdout/stderr 设为 UTF-8。

在需要输出中文的脚本中 import 即可：
    import _compat
"""

import sys

if sys.platform == 'win32':
    import io
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream and hasattr(stream, 'buffer'):
            encoding = stream.encoding or ''
            if encoding.upper() not in ('UTF-8', 'UTF8'):
                setattr(sys, name, io.TextIOWrapper(
                    stream.buffer,
                    encoding='utf-8',
                    errors='backslashreplace'
                ))
