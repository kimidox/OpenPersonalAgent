"""
悬浮球 IPC 协议

主 Flet 进程与桌面悬浮球子进程之间通过 multiprocessing.Queue 交换消息。
消息为字典，必须包含 "type" 字段。
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """悬浮球 IPC 消息类型"""

    # 子进程 -> 主进程
    SHOW_MAIN_WINDOW = "show_main_window"      # 显示/激活主窗口
    TOGGLE_CHAT = "toggle_chat"                # 展开/收起悬浮聊天窗
    START_RECORDING = "start_recording"        # 开始录音
    STOP_RECORDING = "stop_recording"          # 停止录音
    QUIT_APPLICATION = "quit_application"      # 退出应用

    # 悬浮聊天窗口 -> 主进程
    CHAT_SEND_MESSAGE = "chat_send_message"    # 发送聊天消息
    CHAT_REQUEST_HISTORY = "chat_request_history"  # 请求历史消息

    # 主进程 -> 子进程
    EXIT = "exit"                              # 通知子进程退出
    SET_THEME = "set_theme"                    # 更新主题色
    SHOW_WINDOW = "show_window"                # 显示悬浮球窗口（预启动模式）
    HIDE_WINDOW = "hide_window"                # 隐藏悬浮球窗口（预启动模式）

    # 主进程 -> 悬浮聊天窗口
    CHAT_RECEIVE_MESSAGE = "chat_receive_message"  # 接收聊天消息（助手回复）
    CHAT_RECEIVE_HISTORY = "chat_receive_history"  # 接收历史消息

    # LLM 状态管理
    LLM_STATE_UPDATE = "llm_state_update"      # LLM通信状态更新消息
    LLM_STATE_WARNING = "llm_state_warning"     # LLM状态告警消息（用于超时检测）


# LLM_STATE_UPDATE 消息格式:
# {
#     "type": "llm_state_update",
#     "state": "RECEIVING_STREAM",  # 状态名称字符串
#     "timestamp": 1234567890.123,   # 状态转换时间戳
#     "model": "qwen-plus",          # 模型名称（可选）
#     "session_id": "abc123",        # 会话ID（可选）
#     "duration_ms": 5000,           # 持续时间（毫秒，可选）
#     "error_message": "Network timeout"  # 错误消息（可选）
# }
#
# LLM_STATE_WARNING 消息格式:
# {
#     "type": "llm_state_warning",
#     "warning_type": "timeout",     # 告警类型（如 timeout, error 等）
#     "timestamp": 1234567890.123,   # 告警发生时间戳
#     "state": "RECEIVING_STREAM",   # 当前状态
#     "duration_ms": 30000,          # 超时时长（毫秒）
#     "model": "qwen-plus",          # 模型名称（可选）
#     "session_id": "abc123",        # 会话ID（可选）
#     "message": "Stream timeout"    # 告警描述消息（可选）
# }
#
# ============================================================================
# 工具调用流式消息格式（通过 stream_callback 传递）
# ============================================================================
#
# 消息类型: "tool_call" 或 "tool_call_stream"
# - "tool_call": 工具调用的流式增量消息（推荐使用）
# - "tool_call_stream": 别名，与 "tool_call" 等价
#
# 消息格式:
# stream_callback(content, msg_type)
# - content: JSON 字符串，包含以下字段：
#   {
#       "content": "调用工具 `tool_name` · {args}",  # 显示文本
#       "chunk_type": "name" | "arguments",           # 增量类型
#       "is_final": false | true,                     # 是否完成
#       "tool_name": "get_weather",                   # 工具名称（可选）
#       "tool_arguments": "{}",                       # 工具参数（可选）
#   }
# - msg_type: "tool_call" 或 "tool_call_stream"
#
# 增量消息示例：
# 1. 名称增量：
#    content = {"content": "调用工具 `get`", "chunk_type": "name", "is_final": false}
#    stream_callback(json.dumps(content), "tool_call")
#
# 2. 参数增量：
#    content = {"content": "调用工具 `get_weather` · {\"city\": \"Bei", "chunk_type": "arguments", "is_final": false}
#    stream_callback(json.dumps(content), "tool_call")
#
# 3. 完成消息：
#    content = {"content": "调用工具 `get_weather` · {\"city\": \"Beijing\"}", "chunk_type": "arguments", "is_final": true}
#    stream_callback(json.dumps(content), "tool_call")
#
# 向后兼容性：
# - 旧版本前端（不支持 tool_call）：
#   * 接收到 msg_type="tool_call" 时，应忽略该消息或优雅降级
#   * 不应影响现有的 "assistant" 和 "think" 消息处理
# - 新版本前端：
#   * 应支持处理 msg_type="tool_call" 和 "tool_call_stream"
#   * 应同时支持流式和非流式的工具调用消息（过渡期）
#   * 非流式消息：msg_type="tool"，content 为完整文本（旧格式）
#   * 流式消息：msg_type="tool_call"，content 为 JSON（新格式）
#
# 实现说明：
# - 后端通过 StreamParser._emit_tool_call_chunk() 发送增量数据
# - 前端通过 _handle_stream_message() 接收并处理流式消息
# - 流类型：StreamType.TOOL_CALL（已定义在 ui_flet/state.py）
# - 前端应使用打字机效果逐步显示工具调用信息
#
# ============================================================================


def make_message(msg_type: MessageType, **payload: Any) -> dict[str, Any]:
    """构造一条 IPC 消息"""
    return {"type": msg_type, **payload}


def make_llm_state_update_message(
    state: str,
    timestamp: float,
    model: str | None = None,
    session_id: str | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None
) -> dict[str, Any]:
    """
    构造LLM状态更新消息

    Args:
        state: 状态名称字符串（如 "RECEIVING_STREAM"）
        timestamp: 状态转换时间戳（Unix时间戳，浮点数）
        model: 模型名称（可选）
        session_id: 会话ID（可选）
        duration_ms: 持续时间（毫秒，可选）
        error_message: 错误消息（可选）

    Returns:
        构造好的IPC消息字典
    """
    payload: dict[str, Any] = {
        "state": state,
        "timestamp": timestamp
    }

    if model is not None:
        payload["model"] = model
    if session_id is not None:
        payload["session_id"] = session_id
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if error_message is not None:
        payload["error_message"] = error_message

    return make_message(MessageType.LLM_STATE_UPDATE, **payload)


def make_llm_state_warning_message(
    warning_type: str,
    timestamp: float,
    state: str,
    duration_ms: int | None = None,
    model: str | None = None,
    session_id: str | None = None,
    message: str | None = None
) -> dict[str, Any]:
    """
    构造LLM状态告警消息

    Args:
        warning_type: 告警类型（如 "timeout", "error" 等）
        timestamp: 告警发生时间戳（Unix时间戳，浮点数）
        state: 当前状态
        duration_ms: 超时时长（毫秒，可选）
        model: 模型名称（可选）
        session_id: 会话ID（可选）
        message: 告警描述消息（可选）

    Returns:
        构造好的IPC消息字典
    """
    payload: dict[str, Any] = {
        "warning_type": warning_type,
        "timestamp": timestamp,
        "state": state
    }

    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if model is not None:
        payload["model"] = model
    if session_id is not None:
        payload["session_id"] = session_id
    if message is not None:
        payload["message"] = message

    return make_message(MessageType.LLM_STATE_WARNING, **payload)
