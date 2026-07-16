from __future__ import annotations

from html import escape


def escape_html(text: str) -> str:
    return escape(text)


def plain_block_html(text: str) -> str:
    # 仅处理真实换行符，不转换字面量的 "\n"，避免破坏代码内容
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    return f"<p>{escape(t).replace(chr(10), '<br/>')}</p>"
