from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from skill_agent import SkillAgent
    from ui.views.chat_session_tab import ChatSessionTab


class SkillAgentWorkerThread(QThread):
    """绑定发起请求时的 conversation 与会话页，避免切换标签后日志串页。"""

    log_signal = Signal(str, str, object)
    finished_signal = Signal(str, object)

    def __init__(
        self,
        agent: "SkillAgent",
        query: str,
        *,
        conversation_id: str,
        session_tab: "ChatSessionTab",
        enable_thinking: bool = False,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.query = query
        self.conversation_id = conversation_id
        self.session_tab = session_tab
        self._stop_event = threading.Event()
        self._enable_thinking = enable_thinking

    def request_stop(self) -> None:
        self._stop_event.set()
        self.agent.request_stop()

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> None:
        self._stop_event.clear()
        self.agent.set_conversation_id(self.conversation_id)
        self.agent.set_enable_thinking(self._enable_thinking)
        result = self.agent.run(self.query, self._log_callback, stop_check_callback=self.is_stop_requested)
        self.finished_signal.emit(result, self.session_tab)

    def _log_callback(self, message: str, msg_type: str = "info") -> None:
        self.log_signal.emit(message, msg_type, self.session_tab)
