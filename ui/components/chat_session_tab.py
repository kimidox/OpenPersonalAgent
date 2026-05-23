from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ui.components.await_user_card import AwaitUserCard
from ui.components.message_list import MessageListWidget


class ChatSessionTab(QWidget):
    def __init__(self, conversation_id: str, parent: QWidget | None = None, pending_db_history: bool = False) -> None:
        super().__init__(parent)
        self.conversation_id = conversation_id
        self.pending_db_history: bool = pending_db_history
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.message_list = MessageListWidget(self)
        layout.addWidget(self.message_list, stretch=1)
        
        self.await_user_card = AwaitUserCard(self)
        self.await_user_card.setVisible(False)
        layout.addWidget(self.await_user_card)

    def has_active_await_user_prompt(self) -> bool:
        return self.await_user_card.has_active_prompt()

    def clear_await_user_ui(self) -> None:
        self.await_user_card.clear_prompt()

    def show_await_user_prompt(self, spec: dict[str, Any], on_confirm_send: Callable[[str], None] | None = None) -> None:
        self.await_user_card.show_prompt(spec, on_confirm_send=on_confirm_send)

    def add_message(self, msg_type: str, content: str, token_usage: dict[str, Any] | None = None) -> None:
        from ui.components.message_card import MessageType
        valid_type: MessageType = msg_type if msg_type in ("user", "assistant", "tool", "think", "tool_call") else "assistant"
        self.message_list.add_message(valid_type, content, token_usage)

    def scroll_to_bottom(self) -> None:
        self.message_list.scroll_to_bottom()

    def clear_messages(self) -> None:
        self.message_list.clear_all()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.message_list.update_all_cards_width()
