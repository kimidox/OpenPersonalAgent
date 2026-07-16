"""
Markdown 渲染工具

提供 Markdown 到 Flet 组件的渲染功能。
"""
from __future__ import annotations

import re
from html import escape
from typing import Literal

import flet as ft


def normalize_newlines(text: str) -> str:
    """
    标准化换行符

    Args:
        text: 原始文本

    Returns:
        标准化后的文本
    """
    if not text:
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n")


def markdown_to_text(markdown: str) -> str:
    """
    将 Markdown 转换为纯文本（用于显示）

    Args:
        markdown: Markdown 文本

    Returns:
        纯文本
    """
    md = normalize_newlines(markdown)

    # 简单处理：去除 Markdown 标记
    # 注意：这是一个简化版本，Flet 的 ft.Markdown 会处理更复杂的语法

    # 去除代码块标记
    md = re.sub(r'```[\w]*\n?', '', md)
    md = re.sub(r'`([^`]+)`', r'\1', md)

    # 去除标题标记
    md = re.sub(r'^#{1,6}\s+', '', md, flags=re.MULTILINE)

    # 去除粗体和斜体
    md = re.sub(r'\*\*([^*]+)\*\*', r'\1', md)
    md = re.sub(r'\*([^*]+)\*', r'\1', md)
    md = re.sub(r'__([^_]+)__', r'\1', md)
    md = re.sub(r'_([^_]+)_', r'\1', md)

    # 去除链接，保留文本
    md = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', md)

    return md


def create_markdown_content(
    markdown: str,
    theme: Literal["light", "dark"] = "light",
    selectable: bool = True,
    on_tap_link=None,
) -> ft.Markdown:
    """
    创建 Markdown 内容组件

    Args:
        markdown: Markdown 文本
        theme: 主题模式
        selectable: 是否可选择文本
        on_tap_link: 链接点击回调

    Returns:
        Flet Markdown 组件
    """
    md = normalize_newlines(markdown)

    return ft.Markdown(
        value=md,
        selectable=selectable,
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        on_tap_link=on_tap_link,
        code_theme="github-dark" if theme == "dark" else "github",
        code_style_sheet=None,  # 使用默认样式
    )


def create_code_block(
    code: str,
    language: str = "",
    theme: Literal["light", "dark"] = "light",
    selectable: bool = True,
) -> ft.Container:
    """
    创建代码块组件

    Args:
        code: 代码内容
        language: 编程语言
        theme: 主题模式
        selectable: 是否可选择文本

    Returns:
        包含代码块的容器
    """
    # 构造 Markdown 代码块
    markdown = f"```{language}\n{code}\n```"

    return ft.Container(
        content=ft.Markdown(
            value=markdown,
            selectable=selectable,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme="github-dark" if theme == "dark" else "github",
        ),
        bgcolor="#1e1e1e" if theme == "dark" else "#f6f8fa",
        border_radius=8,
        padding=12,
    )


def estimate_message_height(
    text: str,
    max_width: int = 700,
    font_size: int = 14,
) -> int:
    """
    估算消息高度（用于自适应布局）

    Args:
        text: 消息文本
        max_width: 最大宽度
        font_size: 字体大小

    Returns:
        估算的高度（像素）
    """
    if not text:
        return 40

    # 简单估算：每行约 font_size * 1.5 的高度
    # 每行约 50-60 个字符（根据宽度估算）
    chars_per_line = max_width // (font_size // 2)

    lines = text.count('\n') + 1
    text_lines = max(1, len(text) // chars_per_line)

    total_lines = max(lines, text_lines)
    height = total_lines * int(font_size * 1.8)

    # 添加 padding 和 margin
    return max(40, height + 32)