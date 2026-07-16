from __future__ import annotations

import re
from html import escape

from PySide6.QtWidgets import QTextEdit


# 复用 QTextEdit 实例，避免每次渲染 markdown 都创建重量级组件（性能优化）。
# QTextEdit 依赖 QApplication，故延迟到首次使用时创建。
_md_converter: QTextEdit | None = None


def _get_md_converter() -> QTextEdit:
    global _md_converter
    if _md_converter is None:
        _md_converter = QTextEdit()
    return _md_converter


def normalize_newlines(text: str) -> str:
    if not text:
        return text
    # 仅处理真实的换行符，不触碰字面量的反斜杠+n，
    # 否则会破坏代码内容中包含 "\n" 字符串的文本（如 print("\n")）。
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    return t


def markdown_to_html_fragment(markdown: str, wrapper_style: str = "") -> str:
    md = normalize_newlines(markdown)
    converter = _get_md_converter()
    converter.setMarkdown(md)
    raw = converter.toHtml()
    # 用非贪婪匹配提取 body 内容，避免多个标签时匹配过多
    m = re.search(r"<body[^>]*>(.*?)</body>", raw, re.DOTALL | re.IGNORECASE)
    inner = m.group(1).strip() if m else ""
    if not inner:
        return f"<p>{escape(md).replace(chr(10), '<br/>')}</p>"
    if wrapper_style:
        return f'<div style="{wrapper_style}">{inner}</div>'
    return inner
