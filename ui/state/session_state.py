from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Signal

from memory.conversation import Conversation


@dataclass
class SessionInfo:
    conversation_id: str
    title: str | None = None
    pending_db_history: bool = False
    active_skill_ids: list[str] = field(default_factory=list)


class SessionState(QObject):
    conversation_changed = Signal(str)
    conversation_added = Signal(str)
    conversation_removed = Signal(str)
    conversations_loaded = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_conversation_id: str | None = None
        self._sessions: dict[str, SessionInfo] = {}
        self._conversation_order: list[str] = []

    def set_current_conversation(self, conversation_id: str | None) -> None:
        if self._current_conversation_id == conversation_id:
            return
        self._current_conversation_id = conversation_id
        if conversation_id is not None:
            self.conversation_changed.emit(conversation_id)

    def get_current_conversation(self) -> str | None:
        return self._current_conversation_id

    def add_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        pending_db_history: bool = False,
        active_skill_ids: list[str] | None = None,
    ) -> SessionInfo:
        info = SessionInfo(
            conversation_id=conversation_id,
            title=title,
            pending_db_history=pending_db_history,
            active_skill_ids=active_skill_ids or [],
        )
        self._sessions[conversation_id] = info
        if conversation_id not in self._conversation_order:
            self._conversation_order.append(conversation_id)
        self.conversation_added.emit(conversation_id)
        return info

    def remove_conversation(self, conversation_id: str) -> bool:
        if conversation_id not in self._sessions:
            return False
        del self._sessions[conversation_id]
        if conversation_id in self._conversation_order:
            self._conversation_order.remove(conversation_id)
        self.conversation_removed.emit(conversation_id)
        if self._current_conversation_id == conversation_id:
            self._current_conversation_id = None
        return True

    def get_conversation(self, conversation_id: str) -> SessionInfo | None:
        return self._sessions.get(conversation_id)

    def get_all_conversations(self) -> list[SessionInfo]:
        return [
            self._sessions[cid]
            for cid in self._conversation_order
            if cid in self._sessions
        ]

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        info = self._sessions.get(conversation_id)
        if info is None:
            return False
        info.title = title
        return True

    def set_pending_db_history(self, conversation_id: str, pending: bool) -> bool:
        info = self._sessions.get(conversation_id)
        if info is None:
            return False
        info.pending_db_history = pending
        return True

    def is_pending_db_history(self, conversation_id: str) -> bool:
        info = self._sessions.get(conversation_id)
        return info.pending_db_history if info else False

    def clear_all(self) -> None:
        self._sessions.clear()
        self._conversation_order.clear()
        self._current_conversation_id = None

    def load_from_conversations(self, conversations: list[Conversation]) -> None:
        self._sessions.clear()
        self._conversation_order.clear()
        for conv in conversations:
            cid = (conv.conversation_id or "").strip()
            if not cid:
                continue
            self.add_conversation(
                cid,
                title=conv.title,
                pending_db_history=True,
                active_skill_ids=conv.active_skill_ids,
            )
        self.conversations_loaded.emit()

    def has_conversation(self, conversation_id: str) -> bool:
        return conversation_id in self._sessions

    def conversation_count(self) -> int:
        return len(self._sessions)
