from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def get_conversation_type_display_name(conversation_type: str) -> str:
    """获取会话类型的中文显示名称"""
    type_map = {
        'agent_conversation': '智能体会话',
        'record_conversation': '录音会话',
        'human_chat_conversation': '聊天会话'
    }
    return type_map.get(conversation_type, '会话')


@dataclass
class Conversation:
    """与 `database.models.Conversations` 对应的领域会话。"""

    conversation_id: str
    user_id: str
    title: str | None
    active_skill_ids: list[str] = field(default_factory=list)
    type: str = 'agent_conversation'
    default_skills: list[dict] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def get_display_title(self) -> str:
        """获取带会话的显示标题，包含会话类型"""
        title = self.title or "新会话"
        type_display = get_conversation_type_display_name(self.type)
        return f"{title} + {type_display}"

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
        default_skills = getattr(row, "default_skills", [])
        if not isinstance(default_skills, list):
            default_skills = []
        return cls(
            conversation_id=str(row.conversation_id),
            user_id=str(row.user_id),
            title=str(row.title) if row.title is not None else None,
            active_skill_ids=skills,
            type=getattr(row, "type", "agent_conversation"),
            default_skills=default_skills,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
