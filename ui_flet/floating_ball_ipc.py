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

    # 主进程 -> 悬浮聊天窗口
    CHAT_RECEIVE_MESSAGE = "chat_receive_message"  # 接收聊天消息（助手回复）
    CHAT_RECEIVE_HISTORY = "chat_receive_history"  # 接收历史消息


def make_message(msg_type: MessageType, **payload: Any) -> dict[str, Any]:
    """构造一条 IPC 消息"""
    return {"type": msg_type, **payload}
