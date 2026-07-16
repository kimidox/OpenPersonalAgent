from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTextEdit


class StreamType(Enum):
    NONE = "none"
    CONTENT = "content"
    THINK = "think"


@dataclass
class StreamBuffer:
    full_text: str = ""
    shown_chars: int = 0
    marker_start: str = ""
    marker_end: str = ""
    chars_per_tick: int = 2
    token_usage: dict[str, Any] | None = None

    def reset(self) -> None:
        self.full_text = ""
        self.shown_chars = 0
        self.marker_start = ""
        self.marker_end = ""
        self.token_usage = None

    def append_text(self, text: str) -> None:
        self.full_text += text

    def is_complete(self) -> bool:
        return self.shown_chars >= len(self.full_text)

    def remaining_chars(self) -> int:
        return max(0, len(self.full_text) - self.shown_chars)


class StreamState(QObject):
    stream_started = Signal(str)
    stream_tick = Signal(str, int)
    stream_completed = Signal(str, object)
    stream_type_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_type: StreamType = StreamType.NONE
        self._current_session_id: str | None = None
        self._buffer: StreamBuffer = StreamBuffer()
        self._chat_view: QTextEdit | None = None

    def get_current_type(self) -> StreamType:
        return self._current_type

    def set_current_type(self, stream_type: StreamType) -> None:
        if self._current_type == stream_type:
            return
        self._current_type = stream_type
        self.stream_type_changed.emit(stream_type.value)

    def get_current_session_id(self) -> str | None:
        return self._current_session_id

    def set_current_session_id(self, session_id: str | None) -> None:
        self._current_session_id = session_id

    def get_buffer(self) -> StreamBuffer:
        return self._buffer

    def reset_buffer(self) -> None:
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
        self._current_session_id = session_id
        self._current_type = stream_type
        self._buffer = StreamBuffer(
            full_text=initial_text,
            shown_chars=0,
            marker_start=marker_start,
            marker_end=marker_end,
            chars_per_tick=chars_per_tick,
        )
        self.stream_started.emit(session_id)

    def append_to_stream(self, text: str) -> None:
        self._buffer.append_text(text)

    def advance_stream(self, chars: int | None = None) -> int:
        if chars is None:
            chars = self._buffer.chars_per_tick
        next_shown = min(
            len(self._buffer.full_text),
            self._buffer.shown_chars + max(1, chars),
        )
        self._buffer.shown_chars = next_shown
        self.stream_tick.emit(self._current_session_id or "", next_shown)
        return next_shown

    def complete_stream(self, token_usage: dict[str, Any] | None = None) -> None:
        self._buffer.token_usage = token_usage
        self.stream_completed.emit(self._current_session_id or "", token_usage)

    def is_streaming(self) -> bool:
        return self._current_type != StreamType.NONE and self._current_session_id is not None

    def is_active_for_session(self, session_id: str) -> bool:
        return (
            self.is_streaming()
            and self._current_session_id == session_id
        )

    def clear(self) -> None:
        self._current_type = StreamType.NONE
        self._current_session_id = None
        self._buffer.reset()
        self._chat_view = None

    def set_chat_view(self, chat_view: QTextEdit | None) -> None:
        self._chat_view = chat_view

    def get_chat_view(self) -> QTextEdit | None:
        return self._chat_view

    def get_full_text(self) -> str:
        return self._buffer.full_text

    def get_shown_chars(self) -> int:
        return self._buffer.shown_chars

    def set_token_usage(self, token_usage: dict[str, Any] | None) -> None:
        self._buffer.token_usage = token_usage

    def get_token_usage(self) -> dict[str, Any] | None:
        return self._buffer.token_usage
