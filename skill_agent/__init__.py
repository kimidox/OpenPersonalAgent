"""skill_agent 包 — 向后兼容的公共 API 入口。

所有公共符号从此处重新导出，确保外部 import 路径不变：
    from skill_agent import SkillAgent
    from skill_agent import SKILL_AGENT_AWAITING_USER_REPLY
    ...
"""
from skill_agent._helpers import (
    ConversationState,
    PlanMode,
    SKILL_AGENT_AWAITING_USER_REPLY,
    _ask_user_ui_log_payload,
    _message_text,
    _history_without_system,
    _build_system_prompt,
    _ensure_valid_json_args,
)
from skill_agent._agent import SkillAgent

__all__ = [
    "SkillAgent",
    "ConversationState",
    "PlanMode",
    "SKILL_AGENT_AWAITING_USER_REPLY",
    "_ask_user_ui_log_payload",
    "_message_text",
    "_history_without_system",
    "_build_system_prompt",
    "_ensure_valid_json_args",
]
