from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Message:
    """与 `database.models.Messages` 对应的领域消息（供 Memory 与业务层使用）。"""

    message_id: str
    conversation_id: str
    role: str
    content: str
    ext: dict[str, Any] | None = None
    created_at: datetime | None = None

    def to_llm_dict(self) -> dict[str, Any]:
        """拼装为 `BaseChatModel.complete_with_tools` 所需的 message 字典。

        关键修复：还原 OpenAI tool calling 协议要求的消息结构。
        - assistant 工具调用记录（ext.type == "tool_call"）还原为
          {"role": "assistant", "content": ..., "tool_calls": [...]}
          使后续的 tool 结果消息有正确的前置 assistant 消息关联。
        - tool 消息同时附带 tool_call_id（与前置 assistant.tool_calls[].id 对应），
          以满足 OpenAI 新格式与部分国产模型（Qwen/GLM）的校验要求。
        """
        ext = self.ext or {}

        # assistant 工具调用记录：还原为带 tool_calls 的 assistant 消息
        if self.role == "assistant" and ext.get("type") == "tool_call":
            name = str(ext.get("name", ""))
            args = ext.get("args") or "{}"
            if isinstance(args, (dict, list)):
                args = __import__("json").dumps(args, ensure_ascii=False)
            call_id = str(ext.get("tool_call_id") or "call_unknown")
            tool_calls = [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": str(args)},
            }]
            # content 可为 None（纯工具调用）或推理文本
            content = self.content if self.content else None
            return {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            }

        # 普通消息
        d: dict[str, Any] = {"role": self.role, "content": self.content}

        # tool 消息：附带 name 和 tool_call_id
        if self.role == "tool" and ext.get("name"):
            d["name"] = str(ext["name"])
            # 兜底：旧数据可能未持久化 tool_call_id，使用与 assistant 一致的默认值
            call_id = str(ext.get("tool_call_id") or "call_unknown")
            d["tool_call_id"] = call_id
        return d

    def to_record_dict(self) -> dict[str, Any]:
        """含 `metadata`（来自 ext）的记录，供 UI 恢复历史；不含 system 时可与 LLM 字典同构并附加元数据。"""
        d = dict(self.to_llm_dict())
        if self.ext:
            d["metadata"] = dict(self.ext)
        return d

    @classmethod
    def from_orm(cls, row: Any) -> Message:
        from database.models import Messages as MessagesRow

        if not isinstance(row, MessagesRow):
            raise TypeError(f"expected Messages ORM row, got {type(row)!r}")
        return cls(
            message_id=str(row.message_id),
            conversation_id=str(row.conversation_id),
            role=str(row.role),
            content=str(row.content) if row.content is not None else "",
            ext=dict(row.ext) if row.ext is not None else None,
            created_at=row.created_at,
        )
