"""WebSocket 事件协议定义。

把 SkillAgent 的两路事件源统一为 WS 事件：
1. `log_callback(message, msg_type)` — 高频流式（assistant/think/tool_call/tool/...）
2. `AgentEvent(event_type, data, conversation_id)` — 结构化生命周期（agent.start/end 等）

每个出站事件为 JSON dict，含公共字段：
    {
      "event": "<name>",
      "event_id": <int, 单调递增, 按 conversation_id 维度>,
      "conversation_id": "<uuid>",
      "run_id": "<uuid>",
      "timestamp": <float, epoch 秒>,
      "data": {...}
    }

事件命名遵循 frontend-tauri-refactor.md 3.2 节。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from agent_events import AgentEvent, AgentEventType


# =====================================================================
# 事件名常量
# =====================================================================

# Agent 生命周期（来自 AgentEventType）
EVENT_AGENT_START = "agent.start"
EVENT_AGENT_END = "agent.end"
EVENT_TURN_START = "turn.start"
EVENT_TURN_END = "turn.end"
EVENT_TOOL_EXECUTE_START = "tool.execute.start"
EVENT_TOOL_EXECUTE_END = "tool.execute.end"
EVENT_STEERING_RECEIVED = "steering.received"
EVENT_FOLLOWUP_RECEIVED = "followup.received"
EVENT_ERROR = "error"

# 流式增量（来自 log_callback msg_type）
EVENT_STREAM_DELTA = "stream.delta"        # msg_type=assistant/think/tool_call
EVENT_TOOL_RESULT = "tool.result"          # msg_type=tool/base_tool
EVENT_TOKEN_USAGE = "token.usage"          # msg_type=token_usage
EVENT_AWAIT_USER = "await.user"            # msg_type=await_user
EVENT_PLAN = "plan"                         # msg_type=plan
EVENT_LLM_STATE = "llm.state"              # msg_type=llm_state_update
EVENT_LLM_WARNING = "llm.warning"          # msg_type=llm_state_warning

# 运行控制
EVENT_MESSAGE_COMPLETE = "message.complete"
EVENT_RUN_QUEUED = "run.queued"
EVENT_RUN_ABORTED = "run.aborted"

# 系统
EVENT_WINDOW_SHOW = "window.show"
EVENT_REPLAY_MISSED = "replay.missed"

# 悬浮球（阶段 5：球→backend 消息中需通知 Tauri 前端的）
EVENT_FLOATING_BALL_QUIT = "floating_ball.quit"


# log_callback msg_type → stream.delta chunk_type 映射
_MSG_TYPE_TO_CHUNK_TYPE = {
    "assistant": "content",
    "think": "think",
    "tool_call": "tool_call",
}


# AgentEventType → WS 事件名映射
_AGENT_EVENT_TYPE_TO_NAME = {
    AgentEventType.AGENT_START: EVENT_AGENT_START,
    AgentEventType.AGENT_END: EVENT_AGENT_END,
    AgentEventType.TURN_START: EVENT_TURN_START,
    AgentEventType.TURN_END: EVENT_TURN_END,
    AgentEventType.TOOL_EXECUTE_START: EVENT_TOOL_EXECUTE_START,
    AgentEventType.TOOL_EXECUTE_END: EVENT_TOOL_EXECUTE_END,
    AgentEventType.STEERING_RECEIVED: EVENT_STEERING_RECEIVED,
    AgentEventType.FOLLOWUP_RECEIVED: EVENT_FOLLOWUP_RECEIVED,
    AgentEventType.ERROR: EVENT_ERROR,
    # MESSAGE_UPDATE 暂不映射（无 UI 可消费场景）
}


# =====================================================================
# 事件构造
# =====================================================================

@dataclass
class WSEvent:
    """出站 WS 事件。

    `event_id` 由 WSManager 在广播时分配；构造时留 0。
    `data` 字段内容由事件类型决定，详见模块 docstring 与 3.2 节表格。
    """
    event: str
    conversation_id: str
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: int = 0  # 由 WSManager.broadcast 填充

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "event_id": self.event_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# =====================================================================
# 事件工厂（由 stream_bridge 调用）
# =====================================================================

def from_log_callback(
    message: str,
    msg_type: str,
    *,
    conversation_id: str,
    run_id: str,
) -> WSEvent | None:
    """把 SkillAgent log_callback 的 (message, msg_type) 转为 WS 事件。

    Returns:
        WSEvent 或 None（无法识别的 msg_type 跳过）。
    """
    # 兜底：把未映射的 "content" 也视为 assistant 流式内容
    # （SkillAgent 通常已映射，但防止直接调用方遗漏）
    if msg_type in ("assistant", "content", "think", "tool_call"):
        mapped_msg_type = "assistant" if msg_type == "content" else msg_type
        return WSEvent(
            event=EVENT_STREAM_DELTA,
            conversation_id=conversation_id,
            run_id=run_id,
            data={
                "msg_type": mapped_msg_type,
                "chunk_type": _MSG_TYPE_TO_CHUNK_TYPE.get(mapped_msg_type, "content"),
                "content": message,
                # tool_call 字段：复用 floating_ball_ipc.py 的 chunk 协议
                # SkillAgent 直接传字符串 content，无 chunk 边界信息
                "is_final": False,
            },
        )
    if msg_type in ("tool", "base_tool"):
        return WSEvent(
            event=EVENT_TOOL_RESULT,
            conversation_id=conversation_id,
            run_id=run_id,
            data={"content": message, "kind": msg_type},
        )
    if msg_type == "token_usage":
        try:
            usage = json.loads(message)
        except json.JSONDecodeError:
            usage = {"raw": message}
        return WSEvent(
            event=EVENT_TOKEN_USAGE,
            conversation_id=conversation_id,
            run_id=run_id,
            data={"usage": usage},
        )
    if msg_type == "await_user":
        try:
            spec = json.loads(message)
        except json.JSONDecodeError:
            spec = {"raw": message}
        return WSEvent(
            event=EVENT_AWAIT_USER,
            conversation_id=conversation_id,
            run_id=run_id,
            data={"spec": spec},
        )
    if msg_type == "plan":
        return WSEvent(
            event=EVENT_PLAN,
            conversation_id=conversation_id,
            run_id=run_id,
            data={"content": message},
        )
    if msg_type == "llm_state_update":
        try:
            state_data = json.loads(message)
        except json.JSONDecodeError:
            state_data = {"raw": message}
        return WSEvent(
            event=EVENT_LLM_STATE,
            conversation_id=conversation_id,
            run_id=run_id,
            data={
                "state": state_data.get("state", "IDLE"),
                "model": state_data.get("model"),
                "session_id": state_data.get("session_id"),
                "duration_ms": state_data.get("duration_ms", 0),
                "error_message": state_data.get("error_message"),
            },
        )
    if msg_type == "llm_state_warning":
        try:
            warning_data = json.loads(message)
        except json.JSONDecodeError:
            warning_data = {"raw": message}
        return WSEvent(
            event=EVENT_LLM_WARNING,
            conversation_id=conversation_id,
            run_id=run_id,
            data={
                "warning_type": warning_data.get("warning_type", "unknown"),
                "state": warning_data.get("state", "UNKNOWN"),
                "duration_ms": warning_data.get("duration_ms", 0),
                "message": warning_data.get("message", ""),
            },
        )
    # msg_type=mode / info / 其他：跳过
    return None


def from_agent_event(
    agent_event: AgentEvent,
    *,
    run_id: str,
) -> WSEvent | None:
    """把 SkillAgent 的 AgentEvent 转为 WS 事件。

    Returns:
        WSEvent 或 None（MESSAGE_UPDATE 等暂不转发）。
    """
    name = _AGENT_EVENT_TYPE_TO_NAME.get(agent_event.event_type)
    if name is None:
        return None
    return WSEvent(
        event=name,
        conversation_id=agent_event.conversation_id,
        run_id=run_id,
        data=dict(agent_event.data),
        timestamp=agent_event.timestamp,
    )


def message_complete(
    *,
    conversation_id: str,
    run_id: str,
    result: str,
    awaiting_user: bool,
) -> WSEvent:
    """run 结束时推送的完成事件。"""
    return WSEvent(
        event=EVENT_MESSAGE_COMPLETE,
        conversation_id=conversation_id,
        run_id=run_id,
        data={"result": result, "awaiting_user": awaiting_user},
    )


def run_aborted(
    *,
    conversation_id: str,
    run_id: str,
    reason: str,
) -> WSEvent:
    """run 因 sidecar 重启等原因被强制中断（用于崩溃恢复后告知前端）。"""
    return WSEvent(
        event=EVENT_RUN_ABORTED,
        conversation_id=conversation_id,
        run_id=run_id,
        data={"reason": reason},
    )


def replay_missed(*, conversation_id: str, last_event_id: int) -> WSEvent:
    """重连时 since 已过期，告知客户端改走 REST 重建。"""
    return WSEvent(
        event=EVENT_REPLAY_MISSED,
        conversation_id=conversation_id,
        run_id="",  # 系统事件，无关联 run
        data={"last_event_id": last_event_id},
    )


def new_run_id() -> str:
    """生成 run_id（UUID4）。"""
    return str(uuid.uuid4())
