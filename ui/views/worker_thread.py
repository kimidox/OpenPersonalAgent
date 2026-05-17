from __future__ import annotations

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
    ) -> None:
        super().__init__()
        self.agent = agent
        self.query = query
        self.conversation_id = conversation_id
        self.session_tab = session_tab

    def run(self) -> None:
        self.agent.set_conversation_id(self.conversation_id)
        result = self.agent.run(self.query, self._log_callback)
        self.finished_signal.emit(result, self.session_tab)

    def _log_callback(self, message: str, msg_type: str = "info") -> None:
        self.log_signal.emit(message, msg_type, self.session_tab)
