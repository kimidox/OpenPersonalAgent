from __future__ import annotations

from html import escape
from typing import Literal

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit

from ui.styles import StyleManager


BubbleType = Literal["user", "assistant", "tool", "think"]


def generate_bubble_html(
    body_html: str,
    bubble_type: BubbleType,
    subtitle: str = "",
) -> str:
    if bubble_type == "tool":
        outer_style = StyleManager.get_style("chat_tool_outer") or ""
        caption_style = StyleManager.get_style("chat_tool_caption") or ""
        body_style = StyleManager.get_style("chat_tool_text") or ""
    else:
        outer_style = StyleManager.get_style(f"chat_bubble_{bubble_type}_outer") or ""
        caption_style = StyleManager.get_style(f"chat_bubble_{bubble_type}_caption") or ""
        body_style = StyleManager.get_style(f"chat_bubble_{bubble_type}_body") or ""
    
    if not subtitle:
        if bubble_type == "user":
            subtitle = "用户"
        elif bubble_type == "assistant":
            subtitle = "助手"
        elif bubble_type == "tool":
            subtitle = "工具"
        elif bubble_type == "think":
            subtitle = "助手-think"
    
    return (
        f'<div style="{caption_style}">{escape(subtitle)}</div>'
        f'<div style="{outer_style}"><div style="{body_style}">{body_html}</div></div>'
    )


def generate_bubble_html_raw(
    outer_style: str,
    caption_style: str,
    body_style: str,
    caption: str,
    body: str,
) -> str:
    return (
        f'<div style="{outer_style}">'
        f'<div style="{caption_style}">{escape(caption)}</div>'
        f'<div style="{body_style}">{body}</div></div>'
    )


def generate_row_html(inner_html: str, align: str = "left", row_margin_style: str = "") -> str:
    al = "right" if align == "right" else "left"
    margin = f'style="{row_margin_style}"' if row_margin_style else ""
    row_margin = StyleManager.get_style("chat_message_row_table") or ""
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0" style="{row_margin}" {margin}>'
        f'<tr><td align="{al}">{inner_html}</td></tr></table>'
    )


def insert_row(
    chat_view: QTextEdit,
    inner_html: str,
    *,
    align: str = "left",
    row_margin_style: str = "",
    scroll_to_end: bool = True,
) -> None:
    row_html = generate_row_html(inner_html, align=align, row_margin_style=row_margin_style)
    chat_view.moveCursor(QTextCursor.End)
    chat_view.insertHtml(row_html)
    if scroll_to_end:
        _scroll_to_end(chat_view)


def _scroll_to_end(chat_view: QTextEdit) -> None:
    bar = chat_view.verticalScrollBar()
    bar.setValue(bar.maximum())
    chat_view.moveCursor(QTextCursor.End)
