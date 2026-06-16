from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from ui.utils.markdown_utils import normalize_newlines
from ui.utils.text_utils import escape_html

if TYPE_CHECKING:
    from ui.components.chat_session_tab import ChatSessionTab


def parse_await_user_json(message: str) -> dict[str, Any]:
    raw = (message or "").strip()
    if not raw:
        return {"question": "", "context": "", "choices": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"question": raw, "context": "", "choices": []}
    if not isinstance(data, dict):
        return {"question": raw, "context": "", "choices": []}
    choices: list[str] = []
    cr = data.get("choices")
    if isinstance(cr, list):
        for c in cr:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                choices.append(s)
    return {
        "question": str(data.get("question") or "").strip(),
        "context": str(data.get("context") or "").strip(),
        "choices": choices,
    }


class MessageHandler(QObject):
    tool_message = Signal(str, object)
    tool_call_message = Signal(str, object)
    doc_message = Signal(str, object)
    assistant_message = Signal(str, object)
    think_message = Signal(str, object)
    await_user_message = Signal(dict, object)
    token_usage_message = Signal(dict, object)
    skill_content_message = Signal(str, object)
    mode_message = Signal(str, object)
    plan_message = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def handle_message(self, message: str, msg_type: str, session_tab: 'ChatSessionTab') -> None:
        if msg_type in ("tool", "base_tool"):
            self._handle_tool_message(message, session_tab)
        elif msg_type == "tool_call":
            self._handle_tool_call_message(message, session_tab)
        elif msg_type == "doc":
            self._handle_doc_message(message, session_tab)
        elif msg_type in ("assistant", "response", "content"):
            self._handle_assistant_message(message, session_tab)
        elif msg_type == "think":
            self._handle_think_message(message, session_tab)
        elif msg_type == "await_user":
            self._handle_await_user_message(message, session_tab)
        elif msg_type == "token_usage":
            self._handle_token_usage_message(message, session_tab)
        elif msg_type == "skill_content":
            self._handle_skill_content_message(message, session_tab)
        elif msg_type == "mode":
            self._handle_mode_message(message, session_tab)
        elif msg_type == "plan":
            self._handle_plan_message(message, session_tab)

    def _handle_tool_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        normalized = normalize_newlines(message)
        self.tool_message.emit(normalized, session_tab)

    def _handle_tool_call_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        normalized = normalize_newlines(message)
        self.tool_call_message.emit(normalized, session_tab)

    def _handle_doc_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        self.doc_message.emit(message, session_tab)

    def _handle_assistant_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        self.assistant_message.emit(message, session_tab)

    def _handle_think_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        self.think_message.emit(message, session_tab)

    def _handle_await_user_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        spec = parse_await_user_json(message)
        self.await_user_message.emit(spec, session_tab)

    def _handle_token_usage_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        try:
            data = json.loads(message)
            if isinstance(data, dict):
                self.token_usage_message.emit(data, session_tab)
        except json.JSONDecodeError:
            pass
            
    def _handle_skill_content_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        self.skill_content_message.emit(message, session_tab)

    def _handle_mode_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        self.mode_message.emit(message, session_tab)

    def _handle_plan_message(self, message: str, session_tab: 'ChatSessionTab') -> None:
        self.plan_message.emit(message, session_tab)
