from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .conversation import Conversation


class Memory(ABC):
    """SkillAgent 侧记忆机制的抽象接口：会话消息与可选的会话状态（如已加载 Skill）。

    具体持久化（内存字典、SQLite 等）由子类实现；SkillAgent 可通过依赖注入使用。
    """

    @abstractmethod
    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """追加一条对话消息（role 如 system / user / assistant / tool）。"""

    @abstractmethod
    def get_messages(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按时间顺序返回消息列表；每条建议含 role、content、可选 metadata、created_at 等。"""

    @abstractmethod
    def clear_conversation(self, conversation_id: str) -> None:
        """删除该会话及其全部消息（含持久化中的会话行，与关闭标签页语义一致）。"""

    @abstractmethod
    def set_active_skills(self, conversation_id: str, skill_ids: list[str]) -> None:
        """记录当前会话已加载的 Skill id 列表（与 SkillAgent 中 active_skill_ids 对应）。"""

    @abstractmethod
    def get_active_skills(self, conversation_id: str) -> list[str]:
        """读取当前会话已加载的 Skill id 列表。"""

    @abstractmethod
    def ensure_conversation(self, conversation_id: str, *, title: str | None = None) -> str:
        """保证 `conversations` 中存在该会话行并提交；返回采用的展示标题（未指定时与 id 相同）。"""

    @abstractmethod
    def list_user_conversations(self) -> list[Conversation]:
        """列出当前 Memory 所绑定用户的全部会话（顺序由实现决定，建议按 `updated_at` 新近优先）。"""

    @abstractmethod
    def get_message_records(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按时间顺序返回消息记录，每条含 `role`、`content`、可选 `name`（tool）及可选 `metadata`（来自持久化的 ext）。"""

    @abstractmethod
    def get_long_term_memory(self) -> str:
        """读取长期记忆内容。"""

    @abstractmethod
    def append_long_term_memory(self, content: str) -> None:
        """追加内容到长期记忆。"""

    @abstractmethod
    def update_long_term_memory(self, content: str) -> None:
        """更新（覆盖）长期记忆内容。"""
