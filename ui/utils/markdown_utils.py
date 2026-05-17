from __future__ import annotations

import re
from html import escape

from PySide6.QtWidgets import QTextEdit


def normalize_newlines(text: str) -> str:
    if not text:
        return text
    t = text.replace("\r\n", "\n")
    t = t.replace("\\r\\n", "\n").replace("\\n", "\n")
    return t


def markdown_to_html_fragment(markdown: str, wrapper_style: str = "") -> str:
    md = normalize_newlines(markdown)
    tmp = QTextEdit()
    tmp.setMarkdown(md)
    raw = tmp.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", raw, re.DOTALL | re.IGNORECASE)
    inner = m.group(1).strip() if m else ""
    if not inner:
        return f"<p>{escape(md).replace(chr(10), '<br/>')}</p>"
    if wrapper_style:
        return f'<div style="{wrapper_style}">{inner}</div>'
    return inner
