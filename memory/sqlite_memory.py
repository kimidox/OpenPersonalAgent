from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from config import WORKER_DIR
from database import get_session
from database.models import Conversations, Messages, User
from memory.conversation import Conversation
from memory.long_term_memory import LongTermMemory
from memory.memory import Memory
from memory.message import Message





def _ensure_user_in_db(db: Session, username: str) -> User:
    u = db.query(User).filter(User.username == username).first()
    if u:
        return u
    u = User(uuid=str(uuid.uuid4()), username=username)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class SqliteMemory(Memory):
    """基于 SQLite（SQLAlchemy）的 Memory：消息写入 `Messages`，会话与 skill 状态写入 `Conversations`。"""

    def __init__(self, *, username) -> None:
        self._username = username
        memory_file_path = f"{WORKER_DIR}/MEMORY.md"
        self._long_term_memory = LongTermMemory(memory_file_path)

    @property
    def username(self) -> str:
        return self._username

    def _ensure_conversation_row(self, db: Session, conversation_id: str) -> Conversations:
        row = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
        if row:
            return row
        user = _ensure_user_in_db(db, self._username)
        row = Conversations(
            conversation_id=conversation_id,
            user_id=str(user.uuid),
            title=conversation_id,
            active_skill_ids=[],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def ensure_conversation(self, conversation_id: str, *, title: str | None = None) -> str:
        cid = (conversation_id or "").strip()
        if not cid:
            return ""
        resolved_title = title if title is not None else cid
        with get_session() as db:
            row = db.query(Conversations).filter(Conversations.conversation_id == cid).first()
            if row:
                if not row.title:
                    row.title = resolved_title
                    row.updated_at = datetime.now()
                    db.commit()
                    db.refresh(row)
                return str(row.title) if row.title else cid
            user = _ensure_user_in_db(db, self._username)
            row = Conversations(
                conversation_id=cid,
                user_id=str(user.uuid),
                title=resolved_title,
                active_skill_ids=[],
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return str(row.title) if row.title else cid

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with get_session() as db:
            self._ensure_conversation_row(db, conversation_id)
            mid = str(uuid.uuid4())
            ext = dict(metadata) if metadata else None
            db.add(
                Messages(
                    message_id=mid,
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    ext=ext,
                )
            )
            db.commit()

    def get_messages(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with get_session() as db:
            q = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .order_by(Messages.id.asc())
            )
            rows = q.all()
        if limit is not None and limit > 0:
            rows = rows[-limit:]
        return [Message.from_orm(r).to_llm_dict() for r in rows]

    def get_message_records(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with get_session() as db:
            q = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .order_by(Messages.id.asc())
            )
            rows = q.all()
        if limit is not None and limit > 0:
            rows = rows[-limit:]
        return [Message.from_orm(r).to_record_dict() for r in rows]

    def list_user_conversations(self) -> list[Conversation]:
        with get_session() as db:
            user = db.query(User).filter(User.username == self._username).first()
            if not user:
                return []
            rows = (
                db.query(Conversations)
                .filter(Conversations.user_id == str(user.uuid))
                .order_by(Conversations.updated_at.desc())
                .all()
            )
        return [Conversation.from_orm(r) for r in rows]

    def clear_conversation(self, conversation_id: str) -> None:
        with get_session() as db:
            db.query(Messages).filter(Messages.conversation_id == conversation_id).delete()
            db.query(Conversations).filter(Conversations.conversation_id == conversation_id).delete()
            db.commit()

    def set_active_skills(self, conversation_id: str, skill_ids: list[str]) -> None:
        with get_session() as db:
            conv = self._ensure_conversation_row(db, conversation_id)
            conv.active_skill_ids = list(skill_ids)
            conv.updated_at = datetime.now()
            db.commit()

    def get_active_skills(self, conversation_id: str) -> list[str]:
        with get_session() as db:
            conv = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
            if not conv or conv.active_skill_ids is None:
                return []
            return [str(x) for x in conv.active_skill_ids]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with get_session() as db:
            row = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
            if not row:
                return None
            return Conversation.from_orm(row)

    def get_long_term_memory(self) -> str:
        return self._long_term_memory.read()

    def append_long_term_memory(self, content: str) -> None:
        self._long_term_memory.append(content)

    def update_long_term_memory(self, content: str) -> None:
        self._long_term_memory.update(content)
