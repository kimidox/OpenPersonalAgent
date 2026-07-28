from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from database import get_session
from database.models import Conversations, Messages, User
from memory.conversation import Conversation
from memory.memory import Memory
from memory.message import Message

# 注意：WORKER_DIR 虽然未在本文件中使用，但保持导入以避免破坏依赖链
try:
    from config import WORKER_DIR
except ImportError:
    WORKER_DIR = None




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
        content: str | list[dict[str, Any]],
        *,
        metadata: dict[str, Any] | None = None,
        conversation_type: str = 'agent_conversation',
    ) -> None:
        """
        追加消息到会话历史。

        参数：
            conversation_id: 会话 ID
            role: 消息角色（user/assistant/system/tool）
            content: 消息内容，可以是字符串或多模态内容列表
                     字符串格式：纯文本消息
                     列表格式：多模态消息，包含 text 和 image_url 元素
            metadata: 额外的元数据
            conversation_type: 会话类型

        处理逻辑：
            - 如果 content 是字符串：直接存储（向后兼容）
            - 如果 content 是列表：遍历处理多模态内容
                - 对于 image_url 元素：提取 base64 数据，保存为图片文件
                - 替换为 image_ref 格式（包含文件路径信息）
            - 将处理后的 content 序列化为字符串存入数据库
        """
        # 获取 logger
        logger = logging.getLogger(__name__)

        # 处理后的 content（最终存入数据库的内容）
        processed_content: str

        # 检测 content 类型
        if isinstance(content, str):
            # 向后兼容：字符串类型直接存储
            processed_content = content
            logger.debug(f"[append_message] 字符串内容，直接存储（长度: {len(content)}）")

        elif isinstance(content, list):
            # 多模态消息处理
            logger.info(f"[append_message] 检测到多模态消息（元素数量: {len(content)}）")

            # 处理后的内容列表
            processed_list = []
            image_count = 0

            # 遍历列表中的每个元素
            for idx, element in enumerate(content):
                if not isinstance(element, dict):
                    # 非 dict 元素，保持原样（可能不太符合规范，但保留容错）
                    processed_list.append(element)
                    logger.warning(f"[append_message] 元素 {idx} 不是 dict 类型: {type(element)}")
                    continue

                element_type = element.get("type")

                if element_type == "text":
                    # 文本元素，直接保留
                    processed_list.append(element)
                    logger.debug(f"[append_message] 元素 {idx}: 文本内容")

                elif element_type == "image_url":
                    # 图片元素，需要处理
                    image_url_data = element.get("image_url", {})
                    image_url = image_url_data.get("url", "")

                    if not image_url or not image_url.startswith("data:image/"):
                        # 无效的 image_url，保留原样
                        processed_list.append(element)
                        logger.warning(f"[append_message] 元素 {idx}: 无效的 image_url 格式")
                        continue

                    try:
                        # 导入图片存储服务
                        from document_parser.file_storage import save_image_from_base64

                        # 保存图片文件
                        # 从 image_url 提取原始文件名（如果有）
                        original_name = element.get("file_name") or None

                        # 调用图片存储服务
                        save_result = save_image_from_base64(
                            data_url=image_url,
                            original_name=original_name
                        )

                        # 构造 image_ref 元素
                        image_ref_element = {
                            "type": "image_ref",
                            "file_name": save_result["file_name"],
                            "file_path": save_result["file_path"],
                            "mime_type": save_result["mime_type"],
                        }

                        processed_list.append(image_ref_element)
                        image_count += 1

                        logger.info(
                            f"[append_message] 元素 {idx}: 图片已保存 "
                            f"(文件名: {save_result['file_name']}, "
                            f"MIME: {save_result['mime_type']})"
                        )

                    except Exception as e:
                        # 保存失败，保留原始 image_url（可能不太理想，但避免数据丢失）
                        processed_list.append(element)
                        logger.error(
                            f"[append_message] 元素 {idx}: 图片保存失败 - {e}",
                            exc_info=True
                        )

                elif element_type == "image_ref":
                    # 已经是 image_ref 格式，直接保留
                    processed_list.append(element)
                    logger.debug(f"[append_message] 元素 {idx}: 已是 image_ref 格式")

                else:
                    # 其他类型元素（如 tool_use 等），保持原样
                    processed_list.append(element)
                    logger.debug(f"[append_message] 元素 {idx}: 其他类型 {element_type}")

            # 记录处理的图片总数
            if image_count > 0:
                logger.info(f"[append_message] 共处理 {image_count} 张图片")

            # 将处理后的列表序列化为 JSON 字符串
            processed_content = json.dumps(processed_list, ensure_ascii=False)

        else:
            # 其他类型（不应该出现），转换为字符串
            processed_content = str(content)
            logger.warning(
                f"[append_message] content 类型异常: {type(content)}，已转换为字符串"
            )

        # 存入数据库
        with get_session() as db:
            self._ensure_conversation_row(db, conversation_id, conversation_type)
            mid = str(uuid.uuid4())
            ext = dict(metadata) if metadata else None
            db.add(
                Messages(
                    message_id=mid,
                    conversation_id=conversation_id,
                    role=role,
                    content=processed_content,
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
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with get_session() as db:
            q = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .order_by(Messages.id.asc())
            )
            rows = q.all()
        if offset > 0:
            rows = rows[offset:]
        if limit is not None and limit > 0:
            rows = rows[:limit]
        return [Message.from_orm(r).to_record_dict() for r in rows]

    def count_messages(self, conversation_id: str) -> int:
        """返回会话的消息总数（单次 COUNT 查询）"""
        with get_session() as db:
            count = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .count()
            )
            return count

    def get_messages_slice(
        self,
        conversation_id: str,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        分页查询消息（SQL LIMIT + OFFSET，避免全量加载）

        Args:
            conversation_id: 会话 ID
            offset: 偏移量（从最新消息开始计数，0 表示最新）
            limit: 返回数量

        Returns:
            消息记录列表（按时间正序，最旧的消息在前）
        """
        with get_session() as db:
            # 使用子查询获取总数，然后计算偏移
            total_count = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .count()
            )

            # 计算实际偏移量（从旧到新排序，offset=0 表示最新的消息）
            # 例如：总数100，offset=0, limit=20 -> 查询最旧的20条（id 1-20）
            #       总数100，offset=20, limit=20 -> 查询id 21-40
            # 但我们想要的是：offset=0, limit=20 -> 查询最新的20条（id 81-100）
            # 所以需要：actual_offset = total_count - offset - limit
            actual_offset = max(0, total_count - offset - limit)

            rows = (
                db.query(Messages)
                .filter(Messages.conversation_id == conversation_id)
                .order_by(Messages.id.asc())
                .offset(actual_offset)
                .limit(limit)
                .all()
            )

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
