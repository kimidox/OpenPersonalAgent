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

    def pop_last_turn(self, conversation_id: str) -> dict[str, Any] | None:
        """删除会话中最后一条 user 消息及其之后的所有消息，返回该 user 消息记录。

        用于「重新生成」：删除后重新提交该 query，由 Agent 在 run 中重新持久化。
        默认未实现，由支持的子类（如 SqliteMemory）覆盖。
        """
        raise NotImplementedError(f"{type(self).__name__} 不支持 pop_last_turn")

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
    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """更新会话标题。"""

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
    def count_messages(self, conversation_id: str) -> int:
        """返回会话的消息总数（用于分页）。"""

    @abstractmethod
    def get_messages_slice(
        self,
        conversation_id: str,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        按时间顺序返回指定范围的消息（分页查询）。

        Args:
            conversation_id: 会话 ID
            offset: 偏移量（从最新消息开始计数，0 表示最新）
            limit: 返回数量

        Returns:
            消息记录列表（按时间正序，最旧的消息在前）
        """
