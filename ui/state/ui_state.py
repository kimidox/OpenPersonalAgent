from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, Signal


class InputState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    AWAITING_USER = "awaiting_user"


@dataclass
class ButtonStates:
    send_enabled: bool = True
    stop_enabled: bool = False
    new_conversation_enabled: bool = True
    settings_enabled: bool = True


class UIState(QObject):
    send_button_changed = Signal(bool)
    stop_button_changed = Signal(bool)
    new_conversation_button_changed = Signal(bool)
    settings_button_changed = Signal(bool)
    input_state_changed = Signal(str)
    input_placeholder_changed = Signal(str)
    ui_reset = Signal()

    PLACEHOLDER_DEFAULT = "输入业务问题后发送…"
    PLACEHOLDER_AWAITING_USER = "Agent 正在等待你的补充回复…"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._button_states: ButtonStates = ButtonStates()
        self._input_state: InputState = InputState.ENABLED
        self._input_placeholder: str = self.PLACEHOLDER_DEFAULT

    def get_send_button_enabled(self) -> bool:
        return self._button_states.send_enabled

    def set_send_button_enabled(self, enabled: bool) -> None:
        if self._button_states.send_enabled == enabled:
            return
        self._button_states.send_enabled = enabled
        self.send_button_changed.emit(enabled)

    def get_stop_button_enabled(self) -> bool:
        return self._button_states.stop_enabled

    def set_stop_button_enabled(self, enabled: bool) -> None:
        if self._button_states.stop_enabled == enabled:
            return
        self._button_states.stop_enabled = enabled
        self.stop_button_changed.emit(enabled)

    def get_new_conversation_button_enabled(self) -> bool:
        return self._button_states.new_conversation_enabled

    def set_new_conversation_button_enabled(self, enabled: bool) -> None:
        if self._button_states.new_conversation_enabled == enabled:
            return
        self._button_states.new_conversation_enabled = enabled
        self.new_conversation_button_changed.emit(enabled)

    def get_settings_button_enabled(self) -> bool:
        return self._button_states.settings_enabled

    def set_settings_button_enabled(self, enabled: bool) -> None:
        if self._button_states.settings_enabled == enabled:
            return
        self._button_states.settings_enabled = enabled
        self.settings_button_changed.emit(enabled)

    def get_input_state(self) -> InputState:
        return self._input_state

    def set_input_state(self, state: InputState) -> None:
        if self._input_state == state:
            return
        self._input_state = state
        self.input_state_changed.emit(state.value)

    def is_input_enabled(self) -> bool:
        return self._input_state == InputState.ENABLED

    def get_input_placeholder(self) -> str:
        return self._input_placeholder

    def set_input_placeholder(self, placeholder: str) -> None:
        if self._input_placeholder == placeholder:
            return
        self._input_placeholder = placeholder
        self.input_placeholder_changed.emit(placeholder)

    def set_awaiting_user_mode(self, awaiting: bool) -> None:
        if awaiting:
            self.set_input_state(InputState.AWAITING_USER)
            self.set_input_placeholder(self.PLACEHOLDER_AWAITING_USER)
        else:
            self.set_input_state(InputState.ENABLED)
            self.set_input_placeholder(self.PLACEHOLDER_DEFAULT)

    def set_task_running(self, running: bool) -> None:
        if running:
            self.set_send_button_enabled(False)
            self.set_input_state(InputState.DISABLED)
            self.set_stop_button_enabled(True)
        else:
            self.set_send_button_enabled(True)
            self.set_input_state(InputState.ENABLED)
            self.set_stop_button_enabled(False)

    def get_button_states(self) -> ButtonStates:
        return self._button_states

    def reset(self) -> None:
        self._button_states = ButtonStates()
        self._input_state = InputState.ENABLED
        self._input_placeholder = self.PLACEHOLDER_DEFAULT
        self.ui_reset.emit()

    def is_task_running(self) -> bool:
        return self._button_states.stop_enabled and not self._button_states.send_enabled
