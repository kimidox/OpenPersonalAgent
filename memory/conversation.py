from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Conversation:
    """与 `database.models.Conversations` 对应的领域会话。"""

    conversation_id: str
    user_id: str
    title: str | None
    active_skill_ids: list[str] = field(default_factory=list)
    type: str = 'agent_conversation'
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_orm(cls, row: Any) -> Conversation:
        from database.models import Conversations as ConversationsRow

        if not isinstance(row, ConversationsRow):
            raise TypeError(f"expected Conversations ORM row, got {type(row)!r}")
        raw = getattr(row, "active_skill_ids", None)
        if isinstance(raw, list):
            skills = [str(x) for x in raw]
        else:
            skills = []
        return cls(
            conversation_id=str(row.conversation_id),
            user_id=str(row.user_id),
            title=str(row.title) if row.title is not None else None,
            active_skill_ids=skills,
            type=getattr(row, "type", "agent_conversation"),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
