"""Jinja2 模板引擎封装。

职责：
  1. 管理模板搜索路径（references/templates/）
  2. 处理模板继承/包含（extends/include）
  3. 保持向后兼容：未传入的 {{PLACEHOLDER}} 变量原文保留，
     由 ContextBuilder 统一提供上下文
"""

from __future__ import annotations

import os
from typing import Any

from jinja2 import Environment, FileSystemLoader, Undefined


class _KeepPlaceholder(Undefined):
    """对未定义的 Jinja2 变量，保留 {{NAME}} 原文而非替换为空。

    这样组件模板中未迁移的 {{PLACEHOLDER}} 在 Jinja2 渲染后
    仍保留原文，由 ContextBuilder 提供的上下文逐步替换。
    """

    def __str__(self) -> str:
        return f"{{{{{self._undefined_name}}}}}"

    __repr__ = __str__


def _find_templates_dir() -> str:
    """返回 references/templates/ 的绝对路径。"""
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "references", "templates")
    )


def create_env(templates_dir: str | None = None) -> Environment:
    """创建并返回 Jinja2 Environment 实例。

    Args:
        templates_dir: 模板目录，默认 references/templates/。

    Returns:
        配置好的 Jinja2 Environment。
    """
    if templates_dir is None:
        templates_dir = _find_templates_dir()

    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,                         # 不自动转义，由 ContextBuilder 中的 _serialize_* 管控 XSS
        undefined=_KeepPlaceholder,                # 缺失变量保留 {{NAME}} 原文
        keep_trailing_newline=True,                # 保留模板末尾换行
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_template(
    template_name: str = "index.html",
    context: dict[str, Any] | None = None,
    templates_dir: str | None = None,
) -> str:
    """渲染 Jinja2 模板。

    Args:
        template_name: 模板文件名（默认 index.html）。
        context: Jinja2 上下文变量。
        templates_dir: 模板目录，默认 references/templates/。

    Returns:
        渲染后的字符串（其中未匹配的 {{PLACEHOLDER}} 原文保留）。
    """
    env = create_env(templates_dir)
    template = env.get_template(template_name)
    return template.render(**(context or {}))
