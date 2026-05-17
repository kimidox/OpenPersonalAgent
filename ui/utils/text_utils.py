from __future__ import annotations

from html import escape


def escape_html(text: str) -> str:
    return escape(text)


def plain_block_html(text: str) -> str:
    t = text.replace("\r\n", "\n")
    t = t.replace("\\r\\n", "\n").replace("\\n", "\n")
    return f"<p>{escape(t).replace(chr(10), '<br/>')}</p>"
