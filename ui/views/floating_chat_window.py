from __future__ import annotations

import json
from typing import Callable, Any, TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QApplication, QSizePolicy
)

from logger import get_logger
from memory import SqliteMemory
from skill_agent import SkillAgent, SKILL_AGENT_AWAITING_USER_REPLY
from resource_path import paths
import config

from ui.components.await_user_card import AwaitUserCard
from ui.components.message_list import MessageListWidget
from ui.state import UIState
from ui.styles.style_manager import StyleManager
from ui.utils import MessageHandler
from ui.utils.simple_stream_renderer import SimpleStreamRenderer
from ui.views.worker_thread import SkillAgentWorkerThread

if TYPE_CHECKING:
    pass


class MultiLineInputEdit(QWidget):
    """多行输入框组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._send_callback = None
        
        from PySide6.QtWidgets import QPlainTextEdit
        self._edit = QPlainTextEdit(self)
        self._edit.setPlaceholderText("输入消息...")
        self._edit.setFont(QFont("Microsoft YaHei", 10))
        self._edit.setMinimumHeight(36)
        self._edit.setMaximumHeight(120)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._edit)
    
    def set_send_callback(self, callback):
        self._send_callback = callback
    
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()
        
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                self._edit.keyPressEvent(event)
            else:
                if self._send_callback:
                    self._send_callback()
                return
        else:
            self._edit.keyPressEvent(event)
    
    def toPlainText(self):
        return self._edit.toPlainText()
    
    def clear(self):
        self._edit.clear()
    
    def setPlaceholderText(self, text):
        self._edit.setPlaceholderText(text)


class FloatingChatWindow(QWidget):
    """半透明浮动聊天窗口"""

    send_message_requested = Signal(str)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_dragging = False
        self._drag_position = QPoint()
        self._is_resizing = False
        self._resize_edge = 0  # 0: none, 1: right, 2: bottom, 3: right+bottom
        self._resize_margin = 8
        self._logger = get_logger()
        self.work_dir = config.WORKER_DIR
        self._memory = SqliteMemory(username=config.DEFAULT_SKILL_AGENT_USER)
        
        # 初始化SkillAgent
        from executor import Executor
        self._executor = Executor(self.work_dir)
        self._skill_agent = SkillAgent(
            self.work_dir, executor=self._executor,
            memory=self._memory, username=config.DEFAULT_SKILL_AGENT_USER,
        )
        
        # 初始化状态和工具
        self._worker_thread: SkillAgentWorkerThread | None = None
        self._stream_renderer = SimpleStreamRenderer(self)
        self._message_handler = MessageHandler(self)
        self._ui_state = UIState(self)
        
        # 当前会话信息
        self._conversation_id: str | None = None
        
        self._init_ui()
        self._init_style()
        self._init_position()
        self._init_conversation()
        self._connect_signals()

    def _init_conversation(self):
        """初始化对话，不自动创建会话，等待用户手动创建或加载最近的会话"""
        # 不再自动创建会话，改为在 showEvent 中加载最近的会话
        pass

    def _load_latest_conversation(self):
        """加载最近的 human_chat_conversation 类型会话"""
        conversations = self._memory.list_user_conversations()
        # 过滤出 human_chat_conversation 类型的会话
        human_chat_convs = [c for c in conversations if c.type == 'human_chat_conversation']
        if human_chat_convs:
            # 获取最近的会话（list_user_conversations 已按 created_at.desc() 排序）
            latest_conv = human_chat_convs[0]
            self._conversation_id = latest_conv.conversation_id
            self._skill_agent.set_conversation_id(latest_conv.conversation_id)
            self._logger.info(f"浮动聊天窗口加载了最近会话: {latest_conv.conversation_id} (类型: human_chat_conversation)")
            return True
        return False

    def _create_new_conversation(self):
        """创建新的 human_chat_conversation 类型会话"""
        # 如果有正在进行的任务，不创建新会话
        if self._worker_thread and self._worker_thread.isRunning():
            self._logger.warning("有正在进行的任务，无法创建新会话")
            return

        cid, title = self._skill_agent.start_new_conversation(conversation_type='human_chat_conversation')
        self._conversation_id = cid
        self._skill_agent.set_conversation_id(cid)
        self._logger.info(f"浮动聊天窗口创建了新会话: {cid} (类型: human_chat_conversation)")

        # 清空消息列表
        self.clear_messages()
        # 清空等待用户UI
        self.clear_await_user_ui()
        # 重置输入框状态
        self._ui_state.set_task_running(False)

    def _init_ui(self):
        """初始化UI"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(400, 500)
        self.resize(500, 600)
        
        # 主容器
        main_container = QWidget(self)
        main_container.setObjectName("floatingChatMainContainer")
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 标题栏
        title_bar = self._create_title_bar()
        main_layout.addWidget(title_bar)
        
        # 聊天内容区
        self.message_list = MessageListWidget(self)
        self.message_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.message_list, stretch=1)
        
        # 等待用户卡片
        self.await_user_card = AwaitUserCard(self)
        self.await_user_card.setVisible(False)
        main_layout.addWidget(self.await_user_card)
        
        # 输入区域
        input_area = self._create_input_area()
        main_layout.addWidget(input_area)
        
        # 设置主容器布局
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.addWidget(main_container)

    def _create_title_bar(self) -> QWidget:
        """创建标题栏"""
        title_bar = QWidget()
        title_bar.setObjectName("floatingChatTitleBar")
        title_bar.setFixedHeight(32)

        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 0, 10, 0)
        title_layout.setSpacing(8)

        # 图标
        icon_path = paths.get_bundled_resource("application.ico")
        icon_btn = QPushButton()
        icon_btn.setFixedSize(20, 20)
        icon_btn.setObjectName("floatingChatIconButton")
        if icon_path.exists():
            icon_btn.setIcon(QIcon(str(icon_path)))
            icon_btn.setIconSize(QSize(16, 16))
        else:
            icon_btn.setText("🤖")
        icon_btn.setCursor(Qt.CursorShape.ArrowCursor)

        # 标题
        from PySide6.QtWidgets import QLabel
        title_label = QLabel("SkillAgent")
        title_label.setObjectName("floatingChatTitleLabel")
        title_label.setFont(QFont("Microsoft YaHei", 9))

        # 新建会话按钮
        new_conv_btn = QPushButton("+")
        new_conv_btn.setFixedSize(24, 24)
        new_conv_btn.setObjectName("floatingChatNewConvButton")
        new_conv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_conv_btn.setToolTip("新建会话")
        new_conv_btn.clicked.connect(self._on_new_conversation_clicked)

        # 关闭按钮
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setObjectName("floatingChatCloseButton")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._on_close_clicked)

        title_layout.addWidget(icon_btn)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(new_conv_btn)
        title_layout.addWidget(close_btn)

        return title_bar

    def _create_input_area(self) -> QWidget:
        """创建输入区域"""
        input_container = QWidget()
        input_container.setObjectName("floatingChatInputContainer")
        
        container_layout = QHBoxLayout(input_container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(8)
        
        self.input_edit = MultiLineInputEdit()
        self.input_edit.setObjectName("floatingChatInputEdit")
        
        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("floatingChatSendButton")
        self.send_btn.setFixedSize(26, 26)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send)
        self.input_edit.set_send_callback(self._on_send)
        
        container_layout.addWidget(self.input_edit, stretch=1)
        container_layout.addWidget(self.send_btn)
        
        return input_container

    def _init_style(self):
        """初始化样式"""
        style = StyleManager.get_style("floating_chat_window_stylesheet")
        if style:
            self.setStyleSheet(style)
        else:
            # 默认样式
            self.setStyleSheet("""
                #floatingChatMainContainer {
                    background-color: rgba(255, 255, 255, 230);
                    border-radius: 12px;
                    border: 1px solid rgba(0, 0, 0, 0.1);
                }
                #floatingChatTitleBar {
                    background-color: rgba(240, 240, 240, 230);
                    border-top-left-radius: 12px;
                    border-top-right-radius: 12px;
                }
                #floatingChatTitleLabel {
                    color: #333;
                }
                #floatingChatNewConvButton {
                    border: none;
                    background-color: transparent;
                    color: #666;
                    font-size: 16px;
                    border-radius: 4px;
                }
                #floatingChatNewConvButton:hover {
                    background-color: rgba(100, 200, 100, 0.3);
                    color: #44aa44;
                }
                #floatingChatCloseButton {
                    border: none;
                    background-color: transparent;
                    color: #666;
                    font-size: 16px;
                    border-radius: 4px;
                }
                #floatingChatCloseButton:hover {
                    background-color: rgba(255, 100, 100, 0.3);
                    color: #ff4444;
                }
                #floatingChatInputContainer {
                    background-color: rgba(245, 245, 245, 230);
                    border-top: 1px solid rgba(0, 0, 0, 0.05);
                }
                #floatingChatSendButton {
                    border: none;
                    background-color: #007aff;
                    color: white;
                    border-radius: 13px;
                    font-size: 14px;
                }
                #floatingChatSendButton:hover {
                    background-color: #0056b3;
                }
                #floatingChatSendButton:pressed {
                    background-color: #004080;
                }
            """)

    def _init_position(self):
        """初始化位置 - 默认屏幕右下角"""
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = screen_geometry.width() - self.width() - 100
        y = screen_geometry.height() - self.height() - 100
        self.move(x, y)

    def _connect_signals(self):
        """连接信号"""
        self._ui_state.send_button_changed.connect(self.send_btn.setEnabled)
        self._ui_state.stop_button_changed.connect(self._on_stop_button_changed)
        self._ui_state.input_placeholder_changed.connect(self.input_edit.setPlaceholderText)
        
        # 连接消息处理器信号
        self._message_handler.assistant_message.connect(self._on_assistant_message)
        self._message_handler.think_message.connect(self._on_think_message)
        self._message_handler.tool_message.connect(self._on_tool_message)
        self._message_handler.await_user_message.connect(self._on_await_user_message)
        self._message_handler.skill_content_message.connect(self._on_skill_content_message)
        self._message_handler.tool_call_message.connect(self._on_tool_call_message)
        self._message_handler.token_usage_message.connect(self._on_token_usage_message)

    def _load_conversation_history(self):
        """加载会话历史"""
        if self._conversation_id is None:
            return
            
        records = self._skill_agent.message_records_for_conversation(self._conversation_id)
        self._replay_messages(records)
        
        # 检查是否需要恢复等待用户提示
        if SkillAgent.conversation_awaits_user_clarification(self._memory, self._conversation_id):
            self._restore_await_user_panel(records)

    def _replay_messages(self, records: list):
        """重放消息记录"""
        show_tool = config.SKILL_AGENT_UI_SHOW_TOOL_CALLS
        from llm.llm_config_manager import get_current_config
        current_config = get_current_config()
        show_thinking = current_config.enable_thinking
        
        for m in records:
            role, content, meta = str(m.get("role") or ""), str(m.get("content") or ""), m.get("metadata") or {}
            if role == "user":
                msg_type = "user"
            elif role == "assistant":
                msg_type = meta.get("type")
                if msg_type == "think":
                    if not show_thinking:
                        continue
                    msg_type = "think"
                elif msg_type == "tool_call":
                    msg_type = "tool_call"
                else:
                    msg_type = "assistant"
            elif role == "tool" and show_tool:
                msg_type = "tool"
            else:
                continue
            
            token_usage = meta.get("token_usage") if msg_type == "assistant" else None
            files = []
            file_dicts = meta.get("files", [])
            if file_dicts and isinstance(file_dicts, list):
                from ui.utils.file_upload_manager import UploadedFileInfo
                files = [UploadedFileInfo.from_dict(d) for d in file_dicts]
            self.add_message(msg_type, content, token_usage=token_usage, files=files)
        
        # 调整布局
        QTimer.singleShot(50, self._finalize_replay)

    def _finalize_replay(self):
        """完成消息重放后的最终处理"""
        self.message_list.update_all_cards_width()
        for card in self.message_list._message_cards:
            if not card.is_finalized():
                card.finalize_content()
        self.scroll_to_bottom()

    def _restore_await_user_panel(self, records: list):
        """恢复等待用户提示面板"""
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
        self.show_await_user_prompt(spec, on_confirm_send=lambda t: self._send_user_message(t))

    def _on_send(self):
        """发送按钮点击"""
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self._send_user_message(text)

    def _send_user_message(self, text: str):
        """发送用户消息"""
        text = (text or "").strip()
        if not text or (self._worker_thread and self._worker_thread.isRunning()):
            return

        # 确保会话已初始化
        if self._conversation_id is None:
            # 先尝试加载最近的会话
            if not self._load_latest_conversation():
                # 如果没有最近会话，创建新会话
                self._create_new_conversation()

        self.add_message("user", text)
        self.clear_await_user_ui()
        self.input_edit.clear()
        self._ui_state.set_task_running(True)
        enable_thinking = self._ui_state.get_enable_thinking()

        self._worker_thread = SkillAgentWorkerThread(
            self._skill_agent, text, conversation_id=self._conversation_id,
            session_tab=self, enable_thinking=enable_thinking
        )
        self._worker_thread.log_signal.connect(self._on_log)
        self._worker_thread.finished_signal.connect(self._on_worker_finished)
        self._worker_thread.start()

    def _on_log(self, message: str, msg_type: str, session_tab):
        """处理日志回调"""
        self._message_handler.handle_message(message, msg_type, session_tab)

    def _on_assistant_message(self, message: str, session_tab):
        """处理助手消息"""
        # 如果有正在进行的 think 流，先强制完成
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            stream_type = self._stream_renderer.get_stream_type()
            if conv_id == self._conversation_id and stream_type == "think":
                self._stream_renderer.complete()
        self._stream_renderer.start(
            self.message_list,
            message,
            "assistant",
            self._conversation_id
        )

    def _on_think_message(self, message: str, session_tab):
        """处理思考消息"""
        # 如果有正在进行的 assistant 流，先强制完成
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            stream_type = self._stream_renderer.get_stream_type()
            if conv_id == self._conversation_id and stream_type == "assistant":
                self._stream_renderer.complete()
        self._stream_renderer.start(
            self.message_list,
            message,
            "think",
            self._conversation_id
        )

    def _on_tool_message(self, message: str, session_tab):
        """处理工具消息"""
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            if conv_id == self._conversation_id:
                self._stream_renderer.complete()
        self.add_message("tool", message)

    def _on_tool_call_message(self, message: str, session_tab):
        """处理工具调用消息"""
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            if conv_id == self._conversation_id:
                self._stream_renderer.complete()
        self.add_message("tool_call", message)

    def _on_skill_content_message(self, message: str, session_tab):
        """处理技能内容消息"""
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            if conv_id == self._conversation_id:
                self._stream_renderer.complete()
        self.add_message("user", message)

    def _on_token_usage_message(self, token_usage: dict, session_tab):
        """处理token使用量消息"""
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            if conv_id == self._conversation_id:
                self._stream_renderer.complete(token_usage)

    def _on_await_user_message(self, spec: dict, session_tab):
        """处理等待用户消息"""
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            if conv_id == self._conversation_id:
                self._stream_renderer.complete()
        self.show_await_user_prompt(spec, on_confirm_send=lambda t: self._send_user_message(t))

    def _on_worker_finished(self, result: str, session_tab):
        """工作线程完成回调"""
        self._ui_state.set_task_running(False)
        # 先完成可能活跃的流
        if self._stream_renderer.is_active():
            conv_id = self._stream_renderer.get_conversation_id()
            if conv_id == self._conversation_id:
                self._stream_renderer.complete()
                
        if result != SKILL_AGENT_AWAITING_USER_REPLY:
            self.clear_await_user_ui()
            # 检查是否需要添加最终结果：只有当流渲染未为该会话创建过卡片时才添加
            if result and result.strip():
                if not self._stream_renderer.had_started_for(self._conversation_id):
                    self.add_message("assistant", result)
        
        # 更新输入框提示
        self._sync_input_placeholder()

    def _sync_input_placeholder(self):
        """同步输入框提示"""
        if self._conversation_id:
            self._ui_state.set_awaiting_user_mode(SkillAgent.conversation_awaits_user_clarification(self._memory, self._conversation_id))

    def _on_stop_button_changed(self, show_stop: bool):
        """停止按钮状态改变回调"""
        if show_stop:
            try:
                self.send_btn.clicked.disconnect(self._on_send)
            except RuntimeError:
                pass
            self.send_btn.setObjectName("floatingChatStopButton")
            self.send_btn.setText("")
            self.send_btn.clicked.connect(self._on_stop)
            self.send_btn.setEnabled(True)
            self.send_btn.setFixedSize(18, 18)
            self.send_btn.style().unpolish(self.send_btn)
            self.send_btn.style().polish(self.send_btn)
            self.send_btn.update()
        else:
            try:
                self.send_btn.clicked.disconnect(self._on_stop)
            except RuntimeError:
                pass
            self.send_btn.setObjectName("floatingChatSendButton")
            self.send_btn.setText("↑")
            self.send_btn.clicked.connect(self._on_send)
            self.send_btn.setFixedSize(26, 26)
            self.send_btn.style().unpolish(self.send_btn)
            self.send_btn.style().polish(self.send_btn)
            self.send_btn.update()

    def _on_stop(self):
        """停止按钮点击"""
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.request_stop()
        if self._stream_renderer.is_active():
            self._stream_renderer.complete()
        self.send_btn.setEnabled(False)
        self.send_btn.setText("")

    def _on_close_clicked(self):
        """关闭按钮点击"""
        self.close_requested.emit()
        self.hide()

    def add_message(self, msg_type: str, content: str, token_usage: dict = None, files: list = None):
        """添加消息"""
        from ui.components.message_card import MessageType
        valid_type: MessageType = msg_type if msg_type in ("user", "assistant", "tool", "think", "tool_call") else "assistant"
        self.message_list.add_message(valid_type, content, token_usage, files=files)

    def update_last_message(self, content: str) -> bool:
        """更新最后一条消息"""
        return self.message_list.update_last_message(content)

    def append_to_last_message(self, text: str) -> bool:
        """追加到最后一条消息"""
        return self.message_list.append_to_last_message(text)

    def finalize_last_message(self, token_usage: dict = None) -> bool:
        """完成最后一条消息"""
        return self.message_list.finalize_last_message(token_usage)

    def scroll_to_bottom(self):
        """滚动到底部"""
        self.message_list.scroll_to_bottom()

    def clear_messages(self):
        """清除所有消息"""
        self.message_list.clear_all()

    def show_await_user_prompt(self, spec: dict[str, Any], on_confirm_send: Callable[[str], None] | None = None):
        """显示等待用户提示"""
        self.await_user_card.show_prompt(spec, on_confirm_send=on_confirm_send)

    def clear_await_user_ui(self):
        """清除等待用户UI"""
        self.await_user_card.clear_prompt()

    def has_active_await_user_prompt(self) -> bool:
        """检查是否有活跃的等待用户提示"""
        return self.await_user_card.has_active_prompt()

    def showEvent(self, event):
        """窗口显示事件 - 加载历史消息"""
        super().showEvent(event)
        # 加载最近的 human_chat_conversation 类型会话
        if self._conversation_id is None:
            self._load_latest_conversation()
        self._load_conversation_history()
        QTimer.singleShot(100, lambda: (self.message_list.update_all_cards_width(), self.scroll_to_bottom()))

    def _on_new_conversation_clicked(self):
        """新建会话按钮点击"""
        self._create_new_conversation()

    def mousePressEvent(self, event):
        """鼠标按下事件 - 开始拖动或调整大小"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            self._check_resize_edge(pos)
            
            if self._resize_edge != 0:
                self._is_resizing = True
            else:
                self._is_dragging = True
                self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 拖动或调整大小"""
        if self._is_resizing and event.buttons() & Qt.MouseButton.LeftButton:
            new_size = self.size()
            global_pos = event.globalPosition().toPoint()
            top_left = self.frameGeometry().topLeft()
            
            if self._resize_edge & 1:  # right edge
                new_width = global_pos.x() - top_left.x()
                new_size.setWidth(max(self.minimumWidth(), new_width))
            if self._resize_edge & 2:  # bottom edge
                new_height = global_pos.y() - top_left.y()
                new_size.setHeight(max(self.minimumHeight(), new_height))
            
            self.resize(new_size)
            event.accept()
        elif self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
        else:
            # 更新鼠标光标
            self._check_resize_edge(event.pos())
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件 - 结束拖动或调整大小"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._is_resizing = False
            self._resize_edge = 0
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _check_resize_edge(self, pos: QPoint):
        """检查是否在调整大小边缘"""
        edge = 0
        if pos.x() >= self.width() - self._resize_margin:
            edge |= 1
        if pos.y() >= self.height() - self._resize_margin:
            edge |= 2
        
        self._resize_edge = edge
        
        if edge == 0:
            self.unsetCursor()
        elif edge == 1:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == 2:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge == 3:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
