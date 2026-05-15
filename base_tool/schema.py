from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.BaseChatModel import BaseChatModel


def tools_for_model(model: "BaseChatModel", definitions: list[dict]) -> list[dict]:
    """将 canonical 工具定义转为当前聊天模型客户端所需的 schema 列表。"""
    from llm.glm_chat_model import GLMChatModel
    
    if isinstance(model, GLMChatModel):
        return [
            {"name": d["name"], "description": d["description"], "parameters": d["parameters"]}
            for d in definitions
        ]
    out: list[dict] = []
    for d in definitions:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": d["name"],
                    "description": d["description"],
                    "parameters": d["parameters"],
                },
            }
        )
    return out
