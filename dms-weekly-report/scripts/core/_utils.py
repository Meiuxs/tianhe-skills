"""核心工具函数（独立模块，避免循环导入）。

包含：
  - retry_async: 异步函数重试装饰器（指数退避）
"""

from __future__ import annotations

import asyncio
import functools
import logging

from playwright._impl._errors import TimeoutError as PlaywrightTimeout
from playwright._impl._errors import TargetClosedError

logger = logging.getLogger("dms_report")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


def retry_async(max_retries: int = MAX_RETRIES, base_delay: float = RETRY_BASE_DELAY):
    """异步函数重试装饰器，指数退避。

    仅重试以下可恢复异常:
      - PlaywrightTimeout: 网络/页面加载超时
      - OSError: 连接断开、DNS 解析失败等网络层错误
      - asyncio.TimeoutError: asyncio 原生超时
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (PlaywrightTimeout, OSError, asyncio.TimeoutError, TargetClosedError) as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning("%s 第 %d/%d 次失败: %s，%.1fs 后重试",
                                       func.__name__, attempt, max_retries, e, delay)
                        await asyncio.sleep(delay)
                    else:
                        logger.error("%s 重试 %d 次后仍失败: %s",
                                     func.__name__, max_retries, e)
            raise last_exc
        return wrapper
    return decorator
