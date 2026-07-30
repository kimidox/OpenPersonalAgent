from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm.BaseChatModel import BaseChatModel


def tools_for_model(model: "BaseChatModel", definitions: list[dict]) -> list[dict]:
    """将 canonical 工具定义转为当前聊天模型客户端所需的 schema 列表。

    Business purpose:
        不同 LLM 模型对 tool schema 格式要求不同（如 GLM 不需要 type 字段），
        此函数根据模型类型返回适配的 schema 格式。

    Parameters:
        model: 当前使用的 LLM 模型实例
        definitions: 标准格式的工具定义列表

    Returns:
        模型适配后的工具 schema 列表

    Key branches:
        - GLMChatModel: 返回简化格式（去掉 type/function 包装）
        - 其他模型: 返回 OpenAI 标准格式

    Modification notes:
        2026-07-29: 延迟导入改为 isinstance 检查，降低 base_tool→llm 耦合

    Related tests:
        tests/test_schema.py (待补充)
    """
    # AI-BRANCH-MARKER
    # Reason: GLM 模型 tool schema 格式与 OpenAI 标准不同
    # Applies when: model 是 GLMChatModel 实例
    # Do not merge because: GLM 不接受 type/function 嵌套结构
    # Rules to preserve: 返回扁平的 {name, description, parameters} 格式
    # Last reviewed: 2026-07-29

    # 延迟导入：仅在需要时加载 GLMChatModel，避免 base_tool→llm 模块级依赖
    try:
        from llm.glm_chat_model import GLMChatModel
        is_glm = isinstance(model, GLMChatModel)
    except ImportError:
        is_glm = False

    if is_glm:
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
