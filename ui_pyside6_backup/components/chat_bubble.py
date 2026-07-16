from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtWidgets import QTextEdit

from ui.styles.style_manager import StyleManager
from ui.utils.html_utils import generate_bubble_html, insert_row


def _plain_block_html(text: str) -> str:
    escaped = escape(text or "")
    lines = escaped.split("\n")
    return "<br>".join(lines)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _markdown_fragment_html(markdown: str) -> str:
    import markdown

    md = _normalize_newlines(markdown or "")
    if not md.strip():
        return ""
    wrapper_style = StyleManager.get_style("markdown_fragment_wrapper")
    html = markdown.markdown(md, extensions=["fenced_code", "tables", "toc"])
    return f'<div style="{wrapper_style}">{html}</div>'


class ChatBubble:
    @staticmethod
    def get_style(name: str) -> str:
        return StyleManager.get_style(name)

    @staticmethod
    def get_row_margin_style() -> str:
        return StyleManager.get_style("chat_message_row_table")

    @staticmethod
    def create_user_bubble(text: str) -> str:
        body = _plain_block_html(text)
        return generate_bubble_html(body, "user", "用户")

    @staticmethod
    def create_assistant_bubble(
        body_html: str, *, subtitle: str = "助手", token_usage: dict[str, Any] | None = None
    ) -> str:
        token_html = ""
        import config

        if config.TOKEN_USAGE_SHOW_IN_UI and token_usage:
            total = token_usage.get("total_tokens")
            if total is not None:
                token_html = f'<div style="color:#9ca3af;font-size:9pt;margin-top:8px;">Token: {total}</div>'
        full_body = f"{body_html}{token_html}"
        return generate_bubble_html(full_body, "assistant", subtitle)

    @staticmethod
    def create_assistant_markdown_bubble(
        markdown: str, *, subtitle: str = "助手", token_usage: dict[str, Any] | None = None
    ) -> str:
        body_html = _markdown_fragment_html(markdown)
        return ChatBubble.create_assistant_bubble(body_html, subtitle=subtitle, token_usage=token_usage)

    @staticmethod
    def create_think_bubble(body_html: str, *, subtitle: str = "助手-think") -> str:
        return generate_bubble_html(body_html, "think", subtitle)

    @staticmethod
    def create_think_markdown_bubble(markdown: str, *, subtitle: str = "助手-think") -> str:
        body_html = _markdown_fragment_html(markdown)
        return ChatBubble.create_think_bubble(body_html, subtitle=subtitle)

    @staticmethod
    def create_tool_bubble(text: str) -> str:
        safe = escape(_normalize_newlines(text))
        return generate_bubble_html(safe, "tool", "工具")

    @staticmethod
    def create_skill_doc_bubble(markdown: str) -> str:
        body_html = _markdown_fragment_html(markdown)
        return ChatBubble.create_assistant_bubble(body_html, subtitle="Skill 文档")

    @staticmethod
    def append_user(chat_view: QTextEdit, text: str) -> None:
        bubble = ChatBubble.create_user_bubble(text)
        insert_row(chat_view, bubble, align="right")

    @staticmethod
    def append_assistant(
        chat_view: QTextEdit,
        body_html: str,
        *,
        subtitle: str = "助手",
        token_usage: dict[str, Any] | None = None,
    ) -> None:
        bubble = ChatBubble.create_assistant_bubble(body_html, subtitle=subtitle, token_usage=token_usage)
        insert_row(chat_view, bubble, align="left")

    @staticmethod
    def append_assistant_markdown(
        chat_view: QTextEdit,
        markdown: str,
        *,
        subtitle: str = "助手",
        token_usage: dict[str, Any] | None = None,
    ) -> None:
        bubble = ChatBubble.create_assistant_markdown_bubble(markdown, subtitle=subtitle, token_usage=token_usage)
        insert_row(chat_view, bubble, align="left")

    @staticmethod
    def append_think(chat_view: QTextEdit, body_html: str, *, subtitle: str = "助手-think") -> None:
        bubble = ChatBubble.create_think_bubble(body_html, subtitle=subtitle)
        insert_row(chat_view, bubble, align="left")

    @staticmethod
    def append_think_markdown(chat_view: QTextEdit, markdown: str, *, subtitle: str = "助手-think") -> None:
        bubble = ChatBubble.create_think_markdown_bubble(markdown, subtitle=subtitle)
        insert_row(chat_view, bubble, align="left")

    @staticmethod
    def append_tool(chat_view: QTextEdit, text: str) -> None:
        bubble = ChatBubble.create_tool_bubble(text)
        insert_row(chat_view, bubble, align="left")

    @staticmethod
    def append_skill_doc(chat_view: QTextEdit, markdown: str) -> None:
        bubble = ChatBubble.create_skill_doc_bubble(markdown)
        insert_row(chat_view, bubble, align="left")
