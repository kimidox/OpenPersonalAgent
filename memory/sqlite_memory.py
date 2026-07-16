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
from memory.searcher import MemorySearcher, MemorySegmentData




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
        self._long_term_memory = LongTermMemory(
            memory_file_path=memory_file_path,
            user_id=username,
        )
        self._searcher = MemorySearcher()

    @property
    def username(self) -> str:
        return self._username

    def _ensure_conversation_row(self, db: Session, conversation_id: str, conversation_type: str = 'agent_conversation', default_skills: list[dict] | None = None) -> Conversations:
        row = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
        if row:
            return row
        user = _ensure_user_in_db(db, self._username)
        row = Conversations(
            conversation_id=conversation_id,
            user_id=str(user.uuid),
            title=conversation_id,
            active_skill_ids=[],
            type=conversation_type,
            default_skills=default_skills or [],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def ensure_conversation(self, conversation_id: str, *, title: str | None = None, conversation_type: str = 'agent_conversation', default_skills: list[dict] | None = None) -> str:
        cid = (conversation_id or "").strip()
        if not cid:
            return ""
        resolved_title = title if title is not None else cid
        with get_session() as db:
            row = db.query(Conversations).filter(Conversations.conversation_id == cid).first()
            if row:
                updated = False
                if not row.title:
                    row.title = resolved_title
                    updated = True
                if default_skills is not None and row.default_skills != default_skills:
                    row.default_skills = default_skills
                    updated = True
                if updated:
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
                type=conversation_type,
                default_skills=default_skills or [],
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return str(row.title) if row.title else cid

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """更新会话标题"""
        cid = (conversation_id or "").strip()
        if not cid:
            return
        with get_session() as db:
            row = db.query(Conversations).filter(Conversations.conversation_id == cid).first()
            if row:
                row.title = title
                row.updated_at = datetime.now()
                db.commit()

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        conversation_type: str = 'agent_conversation',
    ) -> None:
        with get_session() as db:
            self._ensure_conversation_row(db, conversation_id, conversation_type)
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
        
        # 关键修复：不再过滤 type=="tool_call" 的 assistant 消息。
        # 这些消息保存的是 LLM 发起的工具调用，必须在历史中还原为
        # 带 tool_calls 的 assistant 消息（由 Message.to_llm_dict 处理），
        # 否则后续的 tool 结果会变成"孤立 tool 消息"，违反 OpenAI 协议，
        # 导致 LLM 无法理解任务进度并重复执行工具。
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
                .order_by(Conversations.created_at.desc())
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

    def set_default_skills(self, conversation_id: str, default_skills: list[dict]) -> None:
        with get_session() as db:
            conv = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
            if conv:
                conv.default_skills = default_skills
                conv.updated_at = datetime.now()
                db.commit()

    def get_default_skills(self, conversation_id: str) -> list[dict]:
        with get_session() as db:
            conv = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
            if not conv or conv.default_skills is None:
                return []
            return conv.default_skills if isinstance(conv.default_skills, list) else []

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with get_session() as db:
            row = db.query(Conversations).filter(Conversations.conversation_id == conversation_id).first()
            if not row:
                return None
            return Conversation.from_orm(row)

    def get_long_term_memory(self) -> str:
        return self._long_term_memory.read()

    def search_long_term_memory(self, query: str, limit: int = 5) -> list[MemorySegmentData]:
        return self._long_term_memory.search(query, limit)

    def append_long_term_memory(self, content: str) -> None:
        self._long_term_memory.append(content)

    def update_long_term_memory(self, content: str) -> None:
        self._long_term_memory.update(content)

    def search_skill_memory(self, skill_id: str, query: str, limit: int = 5) -> list[MemorySegmentData]:
        return self._searcher.search(
            query=query,
            memory_type=MemorySearcher.SKILL,
            related_id=skill_id,
            limit=limit,
        )

    def append_skill_memory(self, skill_id: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        self._searcher.add_segment(
            memory_type=MemorySearcher.SKILL,
            content=content,
            related_id=skill_id,
            metadata=metadata,
        )

    def get_messages_for_compaction(
        self,
        conversation_id: str,
        keep_recent: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with get_session() as db:
            rows = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .order_by(Messages.id.asc())
                .all()
            )
        eligible_messages = []
        for row in rows:
            if row.role == "system":
                continue
            if row.ext and row.ext.get("type") == "compaction_summary":
                continue
            eligible_messages.append(Message.from_orm(row).to_record_dict())
        if len(eligible_messages) <= keep_recent:
            return [], eligible_messages
        to_compact = eligible_messages[:-keep_recent]
        to_keep = eligible_messages[-keep_recent:]
        return to_compact, to_keep

    def save_compaction_summary(
        self,
        conversation_id: str,
        summary: str,
        compacted_message_ids: list[str],
        conversation_type: str = 'agent_conversation',
    ) -> None:
        with get_session() as db:
            self._ensure_conversation_row(db, conversation_id, conversation_type)
            mid = str(uuid.uuid4())
            metadata = {
                "type": "compaction_summary",
                "compacted_count": len(compacted_message_ids),
            }
            db.add(
                Messages(
                    message_id=mid,
                    conversation_id=conversation_id,
                    role="system",
                    content=summary,
                    ext=metadata,
                )
            )
            for msg_id in compacted_message_ids:
                msg = (
                    db.query(Messages)
                    .filter(Messages.message_id == msg_id)
                    .first()
                )
                if msg:
                    if msg.ext is None:
                        msg.ext = {}
                    msg.ext["compacted"] = True
            db.commit()

    def get_compaction_summary(self, conversation_id: str) -> str | None:
        with get_session() as db:
            msg = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .filter(Messages.role == "system")
                .filter(Messages.ext["type"].as_string() == "compaction_summary")
                .order_by(Messages.id.desc())
                .first()
            )
            if not msg:
                return None
            return msg.content

    def get_recent_conversations_summary(self, limit: int = 5) -> str:
        conversations = self.list_user_conversations()[:limit]
        if not conversations:
            return ""
        summaries = []
        for conv in conversations:
            summary = self.get_compaction_summary(conv.conversation_id)
            if summary:
                title = conv.title or conv.conversation_id[:8]
                summaries.append(f"### {title}\n{summary}")
        return "\n\n---\n\n".join(summaries) if summaries else ""

    def migrate_from_files(self) -> dict[str, int]:
        result = {
            "long_term_memory": 0,
            "skill_memory": 0,
        }
        result["long_term_memory"] = self._long_term_memory.migrate_from_file()
        return result

    def get_conversations_with_messages(self) -> set[str]:
        """
        获取所有有消息记录的会话 ID

        使用单次 SQL DISTINCT 查询一次性获取所有有消息的会话 ID，
        避免 N+1 查询问题。

        Returns:
            所有有消息记录的会话 ID 集合
        """
        with get_session() as db:
            # 使用 DISTINCT 查询所有有消息的 conversation_id
            result = db.query(Messages.conversation_id).distinct().all()
            # 过滤掉 None 和空字符串，返回集合
            return {row[0] for row in result if row[0]}
