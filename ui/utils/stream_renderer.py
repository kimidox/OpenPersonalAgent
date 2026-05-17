from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from ui.components.message_list import MessageListWidget
from ui.utils.markdown_utils import normalize_newlines


_STREAM_TIMER_MS = 30
_STREAM_CHARS_PER_TICK = 3


class StreamRenderer(QObject):
    stream_completed = Signal(str)
    stream_tick = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer: QTimer | None = None
        self._state: dict[str, Any] | None = None

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def _render_tick(self) -> None:
        if self._state is None:
            self._stop_timer()
            return
        
        message_list: MessageListWidget = self._state["message_list"]
        full: str = self._state["full"]
        n = len(full)
        step = int(self._state.get("chars_per_tick") or _STREAM_CHARS_PER_TICK)
        next_shown = min(n, int(self._state["shown"]) + max(1, step))
        
        message_list.update_last_message(full[:next_shown])
        
        self._state["shown"] = next_shown
        self.stream_tick.emit(next_shown)
        
        if next_shown >= n:
            token_usage = self._state.get("token_usage")
            message_list.finalize_last_message(token_usage)
            self.stream_completed.emit(full)
            self._state = None
            self._stop_timer()

    def start_stream(
        self, message_list: MessageListWidget, text: str, stream_type: str = "assistant",
        conversation_id: str | None = None
    ) -> None:
        full = normalize_newlines(text or "")
        if not full.strip():
            return
        
        # 检查是否已经有正在进行的相同会话和类型的流式渲染
        if self._state is not None:
            same_list = self._state["message_list"] == message_list
            same_type = self._state.get("stream_type") == stream_type
            same_conv = (conversation_id is None or 
                        self._state.get("conversation_id") == conversation_id)
            if same_list and same_type and same_conv:
                # 相同会话，相同类型，追加到同一个气泡
                self._state["full"] += full
                return
            else:
                # 不同会话或不同类型，完成之前的流
                self._force_complete_current_stream()
        
        # 创建新的气泡
        msg_type = "think" if stream_type == "think" else "assistant"
        message_list.add_message(msg_type, "")
        
        self._state = {
            "message_list": message_list,
            "conversation_id": conversation_id,
            "full": full,
            "shown": 0,
            "chars_per_tick": _STREAM_CHARS_PER_TICK,
            "stream_type": stream_type,
            "token_usage": None,
        }
        
        self._timer = QTimer(self)
        self._timer.setInterval(_STREAM_TIMER_MS)
        self._timer.timeout.connect(self._render_tick)
        self._timer.start()
        self._render_tick()

    def _force_complete_current_stream(self) -> None:
        if self._state is None:
            return
        self._stop_timer()
        message_list: MessageListWidget = self._state["message_list"]
        full_text: str = self._state["full"]
        token_usage = self._state.get("token_usage")
        message_list.update_last_message(full_text)
        message_list.finalize_last_message(token_usage)
        self.stream_completed.emit(full_text)
        self._state = None

    def append_text(self, text: str) -> None:
        if self._state is None:
            return
        normalized = normalize_newlines(text)
        self._state["full"] += normalized

    def complete_stream(self, token_usage: dict[str, Any] | None = None) -> None:
        if self._state is None:
            return
        if token_usage:
            self._state["token_usage"] = token_usage
        self._force_complete_current_stream()

    def is_streaming(self) -> bool:
        return self._state is not None

    def get_stream_type(self) -> str:
        if self._state is None:
            return ""
        return self._state.get("stream_type", "assistant")

    def get_conversation_id(self) -> str | None:
        if self._state is None:
            return None
        return self._state.get("conversation_id")

    def get_current_text(self) -> str:
        if self._state is None:
            return ""
        return self._state["full"]

    def get_shown_count(self) -> int:
        if self._state is None:
            return 0
        return int(self._state["shown"])

    def cancel_stream(self) -> None:
        if self._state is None:
            return
        self._state = None
        self._stop_timer()

    def set_chars_per_tick(self, chars: int) -> None:
        if self._state is not None and chars > 0:
            self._state["chars_per_tick"] = chars

    def set_timer_interval(self, ms: int) -> None:
        if self._timer is not None and ms > 0:
            self._timer.setInterval(ms)
