"""Flet 状态管理模块

提供应用程序的状态管理，包括会话状态、流状态和 UI 状态。
使用 Flet 的响应式机制（Ref 和状态属性）进行状态管理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

import flet as ft

if TYPE_CHECKING:
    from memory.conversation import Conversation


class StreamType(Enum):
    """流类型枚举"""
    NONE = "none"
    CONTENT = "content"
    THINK = "think"


class InputState(Enum):
    """输入状态枚举"""
    ENABLED = "enabled"
    DISABLED = "disabled"
    AWAITING_USER = "awaiting_user"


@dataclass
class SessionInfo:
    """会话信息数据类"""
    conversation_id: str
    title: str | None = None
    pending_db_history: bool = False
    active_skill_ids: list[str] = field(default_factory=list)


@dataclass
class StreamBuffer:
    """流缓冲区数据类"""
    full_text: str = ""
    shown_chars: int = 0
    marker_start: str = ""
    marker_end: str = ""
    chars_per_tick: int = 2
    token_usage: dict[str, Any] | None = None

    def reset(self) -> None:
        """重置缓冲区"""
        self.full_text = ""
        self.shown_chars = 0
        self.marker_start = ""
        self.marker_end = ""
        self.token_usage = None

    def append_text(self, text: str) -> None:
        """追加文本"""
        self.full_text += text

    def is_complete(self) -> bool:
        """是否已显示完成"""
        return self.shown_chars >= len(self.full_text)

    def remaining_chars(self) -> int:
        """剩余未显示字符数"""
        return max(0, len(self.full_text) - self.shown_chars)


@dataclass
class ButtonStates:
    """按钮状态数据类"""
    send_enabled: bool = True
    stop_enabled: bool = False
    new_conversation_enabled: bool = True
    settings_enabled: bool = True


class SessionState:
    """会话状态管理

    管理当前活动会话和会话列表。
    使用回调函数实现状态变化通知。
    """

    def __init__(self) -> None:
        self._current_conversation_id: str | None = None
        self._sessions: dict[str, SessionInfo] = {}
        self._conversation_order: list[str] = []

        # 状态变化回调
        self._on_conversation_changed: Callable[[str], None] | None = None
        self._on_conversation_added: Callable[[str], None] | None = None
        self._on_conversation_removed: Callable[[str], None] | None = None
        self._on_conversations_loaded: Callable[[], None] | None = None

    def set_callbacks(
        self,
        on_conversation_changed: Callable[[str], None] | None = None,
        on_conversation_added: Callable[[str], None] | None = None,
        on_conversation_removed: Callable[[str], None] | None = None,
        on_conversations_loaded: Callable[[], None] | None = None,
    ) -> None:
        """设置状态变化回调函数"""
        self._on_conversation_changed = on_conversation_changed
        self._on_conversation_added = on_conversation_added
        self._on_conversation_removed = on_conversation_removed
        self._on_conversations_loaded = on_conversations_loaded

    def set_current_conversation(self, conversation_id: str | None) -> None:
        """设置当前会话"""
        if self._current_conversation_id == conversation_id:
            return
        self._current_conversation_id = conversation_id
        if conversation_id is not None and self._on_conversation_changed:
            self._on_conversation_changed(conversation_id)

    def get_current_conversation(self) -> str | None:
        """获取当前会话ID"""
        return self._current_conversation_id

    def add_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        pending_db_history: bool = False,
        active_skill_ids: list[str] | None = None,
    ) -> SessionInfo:
        """添加会话"""
        info = SessionInfo(
            conversation_id=conversation_id,
            title=title,
            pending_db_history=pending_db_history,
            active_skill_ids=active_skill_ids or [],
        )
        self._sessions[conversation_id] = info
        if conversation_id not in self._conversation_order:
            self._conversation_order.append(conversation_id)

        if self._on_conversation_added:
            self._on_conversation_added(conversation_id)

        return info

    def remove_conversation(self, conversation_id: str) -> bool:
        """移除会话"""
        if conversation_id not in self._sessions:
            return False
        del self._sessions[conversation_id]
        if conversation_id in self._conversation_order:
            self._conversation_order.remove(conversation_id)

        if self._on_conversation_removed:
            self._on_conversation_removed(conversation_id)

        if self._current_conversation_id == conversation_id:
            self._current_conversation_id = None
        return True

    def get_conversation(self, conversation_id: str) -> SessionInfo | None:
        """获取会话信息"""
        return self._sessions.get(conversation_id)

    def get_all_conversations(self) -> list[SessionInfo]:
        """获取所有会话（按顺序）"""
        return [
            self._sessions[cid]
            for cid in self._conversation_order
            if cid in self._sessions
        ]

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """更新会话标题"""
        info = self._sessions.get(conversation_id)
        if info is None:
            return False
        info.title = title
        return True

    def set_pending_db_history(self, conversation_id: str, pending: bool) -> bool:
        """设置数据库历史待处理标志"""
        info = self._sessions.get(conversation_id)
        if info is None:
            return False
        info.pending_db_history = pending
        return True

    def is_pending_db_history(self, conversation_id: str) -> bool:
        """检查是否有待处理的数据库历史"""
        info = self._sessions.get(conversation_id)
        return info.pending_db_history if info else False

    def clear_all(self) -> None:
        """清空所有会话"""
        self._sessions.clear()
        self._conversation_order.clear()
        self._current_conversation_id = None

    def load_from_conversations(self, conversations: list[Conversation]) -> None:
        """从会话列表加载"""
        self._sessions.clear()
        self._conversation_order.clear()
        for conv in conversations:
            cid = (conv.conversation_id or "").strip()
            if not cid:
                continue
            self.add_conversation(
                cid,
                title=conv.title,
                pending_db_history=True,
                active_skill_ids=conv.active_skill_ids,
            )

        if self._on_conversations_loaded:
            self._on_conversations_loaded()

    def has_conversation(self, conversation_id: str) -> bool:
        """检查会话是否存在"""
        return conversation_id in self._sessions

    def conversation_count(self) -> int:
        """获取会话数量"""
        return len(self._sessions)


class StreamState:
    """流状态管理

    管理流式输出的状态，包括流类型、缓冲区等。
    """

    def __init__(self) -> None:
        self._current_type: StreamType = StreamType.NONE
        self._current_session_id: str | None = None
        self._buffer: StreamBuffer = StreamBuffer()

        # 状态变化回调
        self._on_stream_started: Callable[[str], None] | None = None
        self._on_stream_tick: Callable[[str, int], None] | None = None
        self._on_stream_completed: Callable[[str, dict[str, Any] | None], None] | None = None
        self._on_stream_type_changed: Callable[[str], None] | None = None

    def set_callbacks(
        self,
        on_stream_started: Callable[[str], None] | None = None,
        on_stream_tick: Callable[[str, int], None] | None = None,
        on_stream_completed: Callable[[str, dict[str, Any] | None], None] | None = None,
        on_stream_type_changed: Callable[[str], None] | None = None,
    ) -> None:
        """设置状态变化回调函数"""
        self._on_stream_started = on_stream_started
        self._on_stream_tick = on_stream_tick
        self._on_stream_completed = on_stream_completed
        self._on_stream_type_changed = on_stream_type_changed

    def get_current_type(self) -> StreamType:
        """获取当前流类型"""
        return self._current_type

    def set_current_type(self, stream_type: StreamType) -> None:
        """设置当前流类型"""
        if self._current_type == stream_type:
            return
        self._current_type = stream_type
        if self._on_stream_type_changed:
            self._on_stream_type_changed(stream_type.value)

    def get_current_session_id(self) -> str | None:
        """获取当前会话ID"""
        return self._current_session_id

    def set_current_session_id(self, session_id: str | None) -> None:
        """设置当前会话ID"""
        self._current_session_id = session_id

    def get_buffer(self) -> StreamBuffer:
        """获取缓冲区"""
        return self._buffer

    def reset_buffer(self) -> None:
        """重置缓冲区"""
        self._buffer.reset()

    def start_stream(
        self,
        session_id: str,
        stream_type: StreamType,
        initial_text: str = "",
        *,
        marker_start: str = "",
        marker_end: str = "",
        chars_per_tick: int = 2,
    ) -> None:
        """开始流"""
        self._current_session_id = session_id
        self._current_type = stream_type
        self._buffer = StreamBuffer(
            full_text=initial_text,
            shown_chars=0,
            marker_start=marker_start,
            marker_end=marker_end,
            chars_per_tick=chars_per_tick,
        )

        if self._on_stream_started:
            self._on_stream_started(session_id)

    def append_to_stream(self, text: str) -> None:
        """追加文本到流"""
        self._buffer.append_text(text)

    def advance_stream(self, chars: int | None = None) -> int:
        """推进流显示"""
        if chars is None:
            chars = self._buffer.chars_per_tick
        next_shown = min(
            len(self._buffer.full_text),
            self._buffer.shown_chars + max(1, chars),
        )
        self._buffer.shown_chars = next_shown

        if self._on_stream_tick:
            self._on_stream_tick(self._current_session_id or "", next_shown)

        return next_shown

    def complete_stream(self, token_usage: dict[str, Any] | None = None) -> None:
        """完成流"""
        self._buffer.token_usage = token_usage
        if self._on_stream_completed:
            self._on_stream_completed(self._current_session_id or "", token_usage)

    def is_streaming(self) -> bool:
        """是否正在流式输出"""
        return self._current_type != StreamType.NONE and self._current_session_id is not None

    def is_active_for_session(self, session_id: str) -> bool:
        """指定会话是否有活跃流"""
        return (
            self.is_streaming()
            and self._current_session_id == session_id
        )

    def clear(self) -> None:
        """清除流状态"""
        self._current_type = StreamType.NONE
        self._current_session_id = None
        self._buffer.reset()

    def get_full_text(self) -> str:
        """获取完整文本"""
        return self._buffer.full_text

    def get_shown_chars(self) -> int:
        """获取已显示字符数"""
        return self._buffer.shown_chars

    def set_token_usage(self, token_usage: dict[str, Any] | None) -> None:
        """设置 token 使用情况"""
        self._buffer.token_usage = token_usage

    def get_token_usage(self) -> dict[str, Any] | None:
        """获取 token 使用情况"""
        return self._buffer.token_usage


class UIState:
    """UI 状态管理

    管理界面元素的启用状态、输入状态等。
    """

    PLACEHOLDER_DEFAULT = "输入业务问题后发送…"
    PLACEHOLDER_AWAITING_USER = "Agent 正在等待你的补充回复…"

    def __init__(self) -> None:
        self._button_states: ButtonStates = ButtonStates()
        self._input_state: InputState = InputState.ENABLED
        self._input_placeholder: str = self.PLACEHOLDER_DEFAULT
        self._enable_thinking: bool = False
        self._loading: bool = False
        self._error_message: str | None = None
        self._window_visible: bool = True

        # 状态变化回调
        self._on_send_button_changed: Callable[[bool], None] | None = None
        self._on_stop_button_changed: Callable[[bool], None] | None = None
        self._on_new_conversation_button_changed: Callable[[bool], None] | None = None
        self._on_settings_button_changed: Callable[[bool], None] | None = None
        self._on_input_state_changed: Callable[[str], None] | None = None
        self._on_input_placeholder_changed: Callable[[str], None] | None = None
        self._on_ui_reset: Callable[[], None] | None = None
        self._on_enable_thinking_changed: Callable[[bool], None] | None = None
        self._on_loading_changed: Callable[[bool], None] | None = None
        self._on_error_changed: Callable[[str | None], None] | None = None
        self._on_window_visibility_changed: Callable[[bool], None] | None = None

    def set_callbacks(
        self,
        on_send_button_changed: Callable[[bool], None] | None = None,
        on_stop_button_changed: Callable[[bool], None] | None = None,
        on_new_conversation_button_changed: Callable[[bool], None] | None = None,
        on_settings_button_changed: Callable[[bool], None] | None = None,
        on_input_state_changed: Callable[[str], None] | None = None,
        on_input_placeholder_changed: Callable[[str], None] | None = None,
        on_ui_reset: Callable[[], None] | None = None,
        on_enable_thinking_changed: Callable[[bool], None] | None = None,
        on_loading_changed: Callable[[bool], None] | None = None,
        on_error_changed: Callable[[str | None], None] | None = None,
        on_window_visibility_changed: Callable[[bool], None] | None = None,
    ) -> None:
        """设置状态变化回调函数"""
        self._on_send_button_changed = on_send_button_changed
        self._on_stop_button_changed = on_stop_button_changed
        self._on_new_conversation_button_changed = on_new_conversation_button_changed
        self._on_settings_button_changed = on_settings_button_changed
        self._on_input_state_changed = on_input_state_changed
        self._on_input_placeholder_changed = on_input_placeholder_changed
        self._on_ui_reset = on_ui_reset
        self._on_enable_thinking_changed = on_enable_thinking_changed
        self._on_loading_changed = on_loading_changed
        self._on_error_changed = on_error_changed
        self._on_window_visibility_changed = on_window_visibility_changed

    def get_send_button_enabled(self) -> bool:
        """获取发送按钮启用状态"""
        return self._button_states.send_enabled

    def set_send_button_enabled(self, enabled: bool) -> None:
        """设置发送按钮启用状态"""
        if self._button_states.send_enabled == enabled:
            return
        self._button_states.send_enabled = enabled
        if self._on_send_button_changed:
            self._on_send_button_changed(enabled)

    def get_stop_button_enabled(self) -> bool:
        """获取停止按钮启用状态"""
        return self._button_states.stop_enabled

    def set_stop_button_enabled(self, enabled: bool) -> None:
        """设置停止按钮启用状态"""
        if self._button_states.stop_enabled == enabled:
            return
        self._button_states.stop_enabled = enabled
        if self._on_stop_button_changed:
            self._on_stop_button_changed(enabled)

    def get_new_conversation_button_enabled(self) -> bool:
        """获取新建会话按钮启用状态"""
        return self._button_states.new_conversation_enabled

    def set_new_conversation_button_enabled(self, enabled: bool) -> None:
        """设置新建会话按钮启用状态"""
        if self._button_states.new_conversation_enabled == enabled:
            return
        self._button_states.new_conversation_enabled = enabled
        if self._on_new_conversation_button_changed:
            self._on_new_conversation_button_changed(enabled)

    def get_settings_button_enabled(self) -> bool:
        """获取设置按钮启用状态"""
        return self._button_states.settings_enabled

    def set_settings_button_enabled(self, enabled: bool) -> None:
        """设置设置按钮启用状态"""
        if self._button_states.settings_enabled == enabled:
            return
        self._button_states.settings_enabled = enabled
        if self._on_settings_button_changed:
            self._on_settings_button_changed(enabled)

    def get_input_state(self) -> InputState:
        """获取输入状态"""
        return self._input_state

    def set_input_state(self, state: InputState) -> None:
        """设置输入状态"""
        if self._input_state == state:
            return
        self._input_state = state
        if self._on_input_state_changed:
            self._on_input_state_changed(state.value)

    def is_input_enabled(self) -> bool:
        """输入是否启用"""
        return self._input_state == InputState.ENABLED

    def get_input_placeholder(self) -> str:
        """获取输入框占位符"""
        return self._input_placeholder

    def set_input_placeholder(self, placeholder: str) -> None:
        """设置输入框占位符"""
        if self._input_placeholder == placeholder:
            return
        self._input_placeholder = placeholder
        if self._on_input_placeholder_changed:
            self._on_input_placeholder_changed(placeholder)

    def set_awaiting_user_mode(self, awaiting: bool) -> None:
        """设置等待用户模式"""
        if awaiting:
            self.set_input_state(InputState.AWAITING_USER)
            self.set_input_placeholder(self.PLACEHOLDER_AWAITING_USER)
        else:
            self.set_input_state(InputState.ENABLED)
            self.set_input_placeholder(self.PLACEHOLDER_DEFAULT)

    def set_task_running(self, running: bool) -> None:
        """设置任务运行状态"""
        if running:
            self.set_send_button_enabled(False)
            self.set_input_state(InputState.DISABLED)
            self.set_stop_button_enabled(True)
        else:
            self.set_send_button_enabled(True)
            self.set_input_state(InputState.ENABLED)
            self.set_stop_button_enabled(False)

    def get_button_states(self) -> ButtonStates:
        """获取按钮状态"""
        return self._button_states

    def reset(self) -> None:
        """重置 UI 状态"""
        self._button_states = ButtonStates()
        self._input_state = InputState.ENABLED
        self._input_placeholder = self.PLACEHOLDER_DEFAULT
        self._loading = False
        self._error_message = None
        if self._on_ui_reset:
            self._on_ui_reset()

    def is_task_running(self) -> bool:
        """任务是否正在运行"""
        return self._button_states.stop_enabled and not self._button_states.send_enabled

    def get_enable_thinking(self) -> bool:
        """获取思考模式启用状态"""
        return self._enable_thinking

    def set_enable_thinking(self, enabled: bool) -> None:
        """设置思考模式启用状态"""
        if self._enable_thinking == enabled:
            return
        self._enable_thinking = enabled
        if self._on_enable_thinking_changed:
            self._on_enable_thinking_changed(enabled)

    def toggle_enable_thinking(self) -> bool:
        """切换思考模式"""
        self._enable_thinking = not self._enable_thinking
        if self._on_enable_thinking_changed:
            self._on_enable_thinking_changed(self._enable_thinking)
        return self._enable_thinking

    def get_loading(self) -> bool:
        """获取加载状态"""
        return self._loading

    def set_loading(self, loading: bool) -> None:
        """设置加载状态"""
        if self._loading == loading:
            return
        self._loading = loading
        if self._on_loading_changed:
            self._on_loading_changed(loading)

    def get_error_message(self) -> str | None:
        """获取错误消息"""
        return self._error_message

    def set_error_message(self, message: str | None) -> None:
        """设置错误消息"""
        self._error_message = message
        if self._on_error_changed:
            self._on_error_changed(message)

    def clear_error(self) -> None:
        """清除错误"""
        self.set_error_message(None)

    def get_window_visible(self) -> bool:
        """获取窗口可见性"""
        return self._window_visible

    def set_window_visible(self, visible: bool) -> None:
        """设置窗口可见性"""
        if self._window_visible == visible:
            return
        self._window_visible = visible
        if self._on_window_visibility_changed:
            self._on_window_visibility_changed(visible)


class AppState:
    """应用全局状态管理

    整合所有状态管理模块，提供统一的访问入口。
    """

    def __init__(self) -> None:
        self.session = SessionState()
        self.stream = StreamState()
        self.ui = UIState()

    def reset(self) -> None:
        """重置所有状态"""
        self.session.clear_all()
        self.stream.clear()
        self.ui.reset()