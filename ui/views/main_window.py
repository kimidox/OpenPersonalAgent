from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

import config
from executor import Executor
from memory import SqliteMemory
from skill_agent import SkillAgent, SKILL_AGENT_AWAITING_USER_REPLY

from ui.components import ChatSessionTab, SettingsDialog
from ui.state import SessionState, StreamState, UIState
from ui.styles import StyleManager
from ui.utils import MessageHandler
from ui.utils.simple_stream_renderer import SimpleStreamRenderer
from ui.views.worker_thread import SkillAgentWorkerThread

if TYPE_CHECKING:
    pass


class SkillAgentMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.work_dir = config.WORKER_DIR
        self.executor = Executor(self.work_dir)
        self._memory = SqliteMemory(username=config.DEFAULT_SKILL_AGENT_USER)
        self.skill_agent = SkillAgent(
            self.work_dir, executor=self.executor,
            memory=self._memory, username=config.DEFAULT_SKILL_AGENT_USER,
        )
        self.worker_thread: SkillAgentWorkerThread | None = None
        self.stream_renderer = SimpleStreamRenderer(self)
        self.message_handler = MessageHandler(self)
        self.session_state = SessionState(self)
        self.stream_state = StreamState(self)
        self.ui_state = UIState(self)
        self._init_ui()
        self._connect_signals()
        self._populate_initial_tabs()

    def _init_ui(self) -> None:
        self.setWindowTitle("SkillAgent")
        self.setGeometry(120, 120, 780, 620)
        central = QWidget()
        central.setObjectName("skillAgentCentral")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self._setup_header(layout)
        self._setup_chat_tabs(layout)
        self._setup_input_area(layout)
        style = StyleManager.get_style("main_window_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_header(self, layout: QVBoxLayout) -> None:
        header = QHBoxLayout()
        header.addStretch(1)
        self.new_conversation_btn = self._create_toolbar_button("新增会话", self._on_new_conversation)
        self.settings_btn = self._create_toolbar_button("设置", self._open_settings)
        header.addWidget(self.new_conversation_btn, alignment=Qt.AlignmentFlag.AlignRight)
        header.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

    def _create_toolbar_button(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("skillAgentToolbarButton")
        btn.setFont(QFont("Microsoft YaHei", 9))
        btn.setFixedHeight(28)
        btn.clicked.connect(callback)
        return btn

    def _setup_chat_tabs(self, layout: QVBoxLayout) -> None:
        self.chat_tabs = QTabWidget()
        self.chat_tabs.setDocumentMode(True)
        self.chat_tabs.setTabsClosable(True)
        self.chat_tabs.setMovable(True)
        self.chat_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.chat_tabs.currentChanged.connect(self._on_current_tab_changed)
        self.chat_tabs.tabBar().tabBarClicked.connect(self._on_tab_bar_clicked)
        self.chat_tabs.setMinimumHeight(280)
        self.chat_tabs.tabBar().setDrawBase(False)
        layout.addWidget(self.chat_tabs, stretch=1)

    def _setup_input_area(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(UIState.PLACEHOLDER_DEFAULT)
        self.input_edit.setFont(QFont("Microsoft YaHei", 10))
        self.input_edit.setMinimumHeight(36)
        self.input_edit.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("skillAgentSendButton")
        self.send_btn.setFont(QFont("Microsoft YaHei", 10))
        self.send_btn.setMinimumHeight(36)
        self.send_btn.setMinimumWidth(88)
        self.send_btn.clicked.connect(self._on_send)
        row.addWidget(self.input_edit, stretch=1)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

    def _connect_signals(self) -> None:
        self.ui_state.send_button_changed.connect(self.send_btn.setEnabled)
        self.ui_state.input_placeholder_changed.connect(self.input_edit.setPlaceholderText)
        self.message_handler.assistant_message.connect(self._on_assistant_message)
        self.message_handler.think_message.connect(self._on_think_message)
        self.message_handler.tool_message.connect(self._on_tool_message)
        self.message_handler.await_user_message.connect(self._on_await_user_message)
        self.message_handler.skill_content_message.connect(self._on_skill_content_message)
        self.message_handler.tool_call_message.connect(self._on_tool_call_message)

    def _populate_initial_tabs(self) -> None:
        sessions = [c for c in self.skill_agent.list_saved_conversations() if (c.conversation_id or "").strip()]
        if not sessions:
            self._create_new_conversation_tab()
            return
        for conv in sessions:
            self._add_conversation_tab((conv.conversation_id or "").strip(), conv.title, pending_db_history=True)
        self.chat_tabs.setCurrentIndex(0)
        first_cid = (sessions[0].conversation_id or "").strip()
        self.skill_agent.set_conversation_id(first_cid)
        self.session_state.set_current_conversation(first_cid)
        first_tab = self.chat_tabs.widget(0)
        if isinstance(first_tab, ChatSessionTab):
            self._ensure_tab_history_loaded(first_tab)
        self._sync_input_placeholder()

    def _add_conversation_tab(self, conversation_id: str, title: str | None = None, pending_db_history: bool = False) -> int:
        tab = ChatSessionTab(conversation_id, pending_db_history=pending_db_history)
        display_title = title or f"新会话 · {conversation_id[:5] if len(conversation_id) >= 5 else conversation_id or '?'}"
        idx = self.chat_tabs.addTab(tab, display_title)
        self.chat_tabs.setTabToolTip(idx, conversation_id)
        self.session_state.add_conversation(conversation_id, title=display_title, pending_db_history=pending_db_history)
        return idx

    def _create_new_conversation_tab(self) -> str:
        cid, title = self.skill_agent.start_new_conversation()
        self._add_conversation_tab(cid, title, pending_db_history=False)
        self.skill_agent.set_conversation_id(cid)
        return cid

    def _active_session_tab(self) -> ChatSessionTab | None:
        w = self.chat_tabs.currentWidget()
        return w if isinstance(w, ChatSessionTab) else None

    def _ensure_tab_history_loaded(self, tab: ChatSessionTab) -> None:
        if not tab.pending_db_history:
            return
        tab.pending_db_history = False
        records = self.skill_agent.message_records_for_conversation(tab.conversation_id)
        self._replay_messages(tab, records)
        if SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id):
            self._restore_await_user_panel(tab, records)
        if self.chat_tabs.currentWidget() is tab:
            self._sync_input_placeholder()

    def _replay_messages(self, tab: ChatSessionTab, records: list) -> None:
        show_tool = config.SKILL_AGENT_UI_SHOW_TOOL_CALLS
        for m in records:
            role, content, meta = str(m.get("role") or ""), str(m.get("content") or ""), m.get("metadata") or {}
            if role == "user":
                msg_type = "user"
            elif role == "assistant":
                msg_type = meta.get("type")
                if msg_type == "think":
                    msg_type = "think"
                elif msg_type == "tool_call":
                    msg_type = "tool_call"
                else:
                    msg_type = "assistant"
            elif role == "tool" and show_tool:
                msg_type = "tool"
            else:
                continue
                
            # 先添加消息
            card = tab.message_list.add_message(msg_type, content)
            
        # 批量加载完成后，先更新所有卡片的宽度，再逐个 finalize
        from PySide6.QtCore import QTimer
        
        def finalize_all_cards():
            tab.message_list.update_all_cards_width()
            for card in tab.message_list._message_cards:
                if not card.is_finalized():
                    card.finalize_content()
            tab.scroll_to_bottom()
            
        QTimer.singleShot(50, finalize_all_cards)

    def _restore_await_user_panel(self, tab: ChatSessionTab, records: list) -> None:
        if not records or str(records[-1].get("role")) != "tool":
            return
        meta = records[-1].get("metadata") or {}
        if meta.get("name") != "ask_user":
            return
        content = str(records[-1].get("content", "") or "")
        if content.startswith("错误"):
            return
        args = meta.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        spec = {"question": str(args.get("question") or "").strip(), "context": str(args.get("context") or "").strip(), "choices": args.get("choices") or []}
        tab.show_await_user_prompt(spec, on_confirm_send=lambda t, st=tab: self._send_user_message(t, session_tab=st))

    def _on_current_tab_changed(self, _index: int) -> None:
        tab = self._active_session_tab()
        if tab is not None:
            self.skill_agent.set_conversation_id(tab.conversation_id)
            self.session_state.set_current_conversation(tab.conversation_id)
            if not tab.pending_db_history and SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id) and not tab.has_active_await_user_prompt():
                self._restore_await_user_panel(tab, self.skill_agent.message_records_for_conversation(tab.conversation_id))
        self._sync_input_placeholder()

    def _sync_input_placeholder(self) -> None:
        tab = self._active_session_tab()
        if tab is None:
            self.ui_state.set_input_placeholder(UIState.PLACEHOLDER_DEFAULT)
        else:
            self.ui_state.set_awaiting_user_mode(SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id))

    def _on_tab_bar_clicked(self, index: int) -> None:
        w = self.chat_tabs.widget(index)
        if isinstance(w, ChatSessionTab):
            self._ensure_tab_history_loaded(w)

    def _on_tab_close_requested(self, index: int) -> None:
        if self.chat_tabs.count() <= 1:
            QMessageBox.information(self, "提示", "至少保留一个会话标签页。")
            return
        page = self.chat_tabs.widget(index)
        if not isinstance(page, ChatSessionTab):
            return
        if self.worker_thread and self.worker_thread.isRunning() and page.conversation_id == self.worker_thread.conversation_id:
            QMessageBox.warning(self, "提示", "该会话正在执行中，请结束后再关闭标签。")
            return
        self._memory.clear_conversation(page.conversation_id)
        self.session_state.remove_conversation(page.conversation_id)
        self.chat_tabs.removeTab(index)
        page.deleteLater()

    def _on_new_conversation(self) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "提示", "当前仍有对话在执行，请结束后再新建会话。")
            return
        self._create_new_conversation_tab()
        self.chat_tabs.setCurrentIndex(self.chat_tabs.count() - 1)
        self._sync_input_placeholder()

    def _open_settings(self) -> None:
        SettingsDialog(self, self.skill_agent).exec()

    def _on_send(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入内容")
            return
        self._send_user_message(text)

    def _send_user_message(self, text: str, *, session_tab: ChatSessionTab | None = None) -> None:
        text = (text or "").strip()
        if not text or (self.worker_thread and self.worker_thread.isRunning()):
            return
        tab = session_tab or self._active_session_tab()
        if tab is None:
            return
        self.skill_agent.set_conversation_id(tab.conversation_id)
        tab.add_message("user", text)
        tab.clear_await_user_ui()
        self.input_edit.clear()
        self.ui_state.set_task_running(True)
        self.worker_thread = SkillAgentWorkerThread(self.skill_agent, text, conversation_id=tab.conversation_id, session_tab=tab)
        self.worker_thread.log_signal.connect(self._on_log)
        self.worker_thread.finished_signal.connect(self._on_worker_finished)
        self.worker_thread.start()

    def _on_log(self, message: str, msg_type: str, session_tab) -> None:
        if isinstance(session_tab, ChatSessionTab):
            self.message_handler.handle_message(message, msg_type, session_tab)

    def _on_assistant_message(self, message: str, session_tab: ChatSessionTab) -> None:
        # 如果有正在进行的 think 流，先强制完成
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            stream_type = self.stream_renderer.get_stream_type()
            if conv_id == session_tab.conversation_id and stream_type == "think":
                self.stream_renderer.complete()
        self.stream_renderer.start(
            session_tab.message_list, 
            message, 
            "assistant", 
            session_tab.conversation_id
        )

    def _on_think_message(self, message: str, session_tab: ChatSessionTab) -> None:
        # 如果有正在进行的 assistant 流，先强制完成
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            stream_type = self.stream_renderer.get_stream_type()
            if conv_id == session_tab.conversation_id and stream_type == "assistant":
                self.stream_renderer.complete()
        self.stream_renderer.start(
            session_tab.message_list, 
            message, 
            "think", 
            session_tab.conversation_id
        )

    def _on_tool_message(self, message: str, session_tab: ChatSessionTab) -> None:
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.add_message("tool", message)

    def _on_tool_call_message(self, message: str, session_tab: ChatSessionTab) -> None:
        """处理工具调用消息"""
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.add_message("tool_call", message)

    def _on_skill_content_message(self, message: str, session_tab: ChatSessionTab) -> None:
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.add_message("user", message)

    def _on_await_user_message(self, spec: dict, session_tab: ChatSessionTab) -> None:
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.show_await_user_prompt(spec, on_confirm_send=lambda t, st=session_tab: self._send_user_message(t, session_tab=st))

    def _on_worker_finished(self, result: str, session_tab) -> None:
        self.ui_state.set_task_running(False)
        if isinstance(session_tab, ChatSessionTab):
            stream_text = ""
            if self.stream_renderer.is_active():
                conv_id = self.stream_renderer.get_conversation_id()
                if conv_id == session_tab.conversation_id:
                    stream_text = self.stream_renderer.complete() or ""
            
            print(f"[DEBUG-finish] main_window: result={result!r}, stream_text={stream_text!r}")
            
            if result != SKILL_AGENT_AWAITING_USER_REPLY:
                session_tab.clear_await_user_ui()
                # 检查是否需要添加最终结果
                if result and result.strip():
                    # 如果流式渲染没有内容或者内容只有"(完成)"这类提示
                    has_stream_content = stream_text.strip() and "(完成)" not in stream_text
                    if not has_stream_content:
                        session_tab.add_message("assistant", result)
        self._sync_input_placeholder()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        tab = self._active_session_tab()
        if tab:
            tab.message_list.update_all_cards_width()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 窗口首次显示后，确保当前标签页滚动到底部
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._ensure_first_tab_layout_correct)

    def _ensure_first_tab_layout_correct(self) -> None:
        tab = self._active_session_tab()
        if tab:
            tab.message_list.update_all_cards_width()
            tab.scroll_to_bottom()

    def closeEvent(self, event) -> None:
        if self.stream_renderer.is_active():
            self.stream_renderer.complete()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait(2000)
        super().closeEvent(event)
