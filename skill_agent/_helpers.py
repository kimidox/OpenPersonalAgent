"""SkillAgent 包的纯函数、枚举和常量。

从原 skill_agent.py 中提取的模块级辅助定义，
与 SkillAgent 类无直接耦合，可独立使用。
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

from prompt import DynamicSystemPrompt


class ConversationState(Enum):
    IDLE = "idle"
    TOOL_CALLED = "tool_called"
    TOOL_EXECUTED = "tool_executed"
    COMPLETED = "completed"


class PlanMode(str, Enum):
    NO_PLAN = "no_plan"
    SIMPLE_TASK = "simple_task"
    COMPLEX_TASK = "complex_task"


SKILL_AGENT_AWAITING_USER_REPLY = "__SKILL_AGENT_AWAITING_USER_REPLY__"


def _ask_user_ui_log_payload(args: dict[str, Any]) -> str:
    """将 ask_user 工具参数格式化为 JSON 负载，用于 UI 日志展示。

    Args:
        args: ask_user 工具的参数字典，包含 question、context、choices 字段。

    Returns:
        格式化后的 JSON 字符串，包含清理过的 question、context 和 choices。
    """
    choices_raw = args.get("choices")
    choices: list[str] = []
    if isinstance(choices_raw, list):
        for c in choices_raw:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                choices.append(s)
    payload = {
        "question": str(args.get("question", "")).strip(),
        "context": str(args.get("context", "")).strip(),
        "choices": choices,
    }
    return json.dumps(payload, ensure_ascii=False)


def _message_text(message: Any) -> str:
    """安全提取消息对象的 content 文本，处理空值和空白。

    Args:
        message: 消息对象，需有 content 属性。

    Returns:
        去除首尾空白后的文本内容；如果 content 不存在、非字符串或为空则返回空字符串。
    """
    c = getattr(message, "content", None)
    if isinstance(c, str) and c.strip():
        return c.strip()
    return ""


def _history_without_system(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤掉 system 角色的消息，返回纯对话历史。

    Args:
        messages: 完整的消息列表（含 system 消息）。

    Returns:
        不包含 role="system" 的消息列表。
    """
    return [m for m in messages if m.get("role") != "system"]


def _build_system_prompt(catalog: str, constraints: str = "") -> str:
    """构建系统提示词，包含技能目录和对话约束。

    Args:
        catalog: 技能目录文本，填充到系统提示词的 TOOL_CATALOG 占位符。
        constraints: 对话约束文本，可选，填充到 CONSTRAINTS 占位符。

    Returns:
        完整的系统提示词字符串。
    """
    dp = DynamicSystemPrompt()
    dp.update_skill_catalog(catalog)
    if constraints.strip():
        dp.update_conversation_constraints(constraints.strip())
    return dp.build()


def _ensure_valid_json_args(args: Any) -> str:
    """确保参数是有效的 JSON 字符串。

    接受 str/dict/其他类型，始终返回有效的 JSON 字符串。
    如果输入是字符串但不是有效 JSON，返回 "{}"。
    """
    if isinstance(args, str):
        try:
            json.loads(args)
            return args
        except (json.JSONDecodeError, TypeError):
            return "{}"
    elif isinstance(args, dict):
        return json.dumps(args, ensure_ascii=False)
    else:
        return "{}"
