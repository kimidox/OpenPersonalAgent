from __future__ import annotations

import gc
import json
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QCoreApplication
from PySide6.QtGui import QFont, QKeyEvent, QIcon, QAction
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QMainWindow, QMessageBox,
    QPushButton, QVBoxLayout, QWidget, QMenu, QSystemTrayIcon, QSplitter,
    QProgressDialog, QLabel,
)

import config
from logger import get_logger
from executor import Executor
from memory import SqliteMemory
from skill_agent import SkillAgent, SKILL_AGENT_AWAITING_USER_REPLY
from resource_path import paths
from scheduler import TaskScheduler
from scheduled_tasks import ScheduledTask
from recorder import get_recorder

from ui.components import ChatSessionTab, SettingsDialog, ConversationSidebar, FileUploadArea
from ui.state import SessionState, StreamState, UIState
from ui.styles import StyleManager
from ui.utils import MessageHandler
from ui.utils.simple_stream_renderer import SimpleStreamRenderer
from ui.utils.file_upload_controller import FileUploadController
from ui.views.worker_thread import SkillAgentWorkerThread

if TYPE_CHECKING:
    pass

logger = get_logger()


class MultiLineInputEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._send_callback = None

    def set_send_callback(self, callback):
        self._send_callback = callback

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                if self._send_callback:
                    self._send_callback()
                return
        else:
            super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        super().insertFromMimeData(source)


class SkillAgentMainWindow(QMainWindow):
    def __init__(self, background: bool = False) -> None:
        super().__init__()
        self._background = background
        self._is_background_mode: bool = False
        self._memory_optimization_timer: QTimer | None = None
        self._logger = get_logger()
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
        self.file_upload_controller = FileUploadController(self)
        self.skill_agent.set_file_upload_controller(self.file_upload_controller)
        self._conversation_tabs: dict[str, ChatSessionTab] = {}
        self._current_conversation_tab: ChatSessionTab | None = None
        self._floating_ball = None
        # 添加处理录音文件的记录，防止重复处理
        self._last_processed_recording: str | None = None
        # 异步转录工作线程
        self._transcribe_worker = None
        # 转录进度对话框
        self._transcribe_progress_dialog = None
        self._init_ui()
        self._init_tray_icon()
        self._init_task_scheduler()
        self._connect_signals()
        self._populate_initial_conversations()
    
    def set_floating_ball(self, floating_ball):
        """设置悬浮球引用"""
        self._floating_ball = floating_ball
        self._logger.info(f"MainWindow.set_floating_ball() 调用，当前 isVisible() = {self.isVisible()}")
        # 不在这里设置显示/隐藏，让 showEvent/hideEvent 来处理
        # 连接悬浮球的模型未加载警告信号
        self._floating_ball.show_model_not_loaded_warning.connect(self._on_show_model_not_loaded_warning)
    
    def _on_show_model_not_loaded_warning(self):
        """显示模型未加载的警告"""
        QMessageBox.warning(
            self, 
            "提示", 
            "语音模型未加载，请先在设置页面点击「加载模型」按钮加载模型，然后再使用录音功能。"
        )
    
    def _on_asr_model_not_loaded(self, filename: str):
        """处理 ASR 模型未加载的信号，显示提示对话框"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("提示")
        msg_box.setText(f"语音识别模型未加载，无法处理音频文件 '{filename}'。\n请先在设置页面点击「加载模型」按钮加载模型后再上传音频文件。")
        msg_box.setIcon(QMessageBox.Icon.Warning)
        
        # 添加"打开设置"按钮
        open_settings_btn = msg_box.addButton("打开设置", QMessageBox.ButtonRole.AcceptRole)
        msg_box.addButton(QMessageBox.StandardButton.Close)
        
        msg_box.exec()
        
        # 如果用户点击了"打开设置"按钮，打开设置页面
        if msg_box.clickedButton() == open_settings_btn:
            self._open_settings()
    
    def _on_floating_ball_send_message(self, text: str):
        """处理来自悬浮球的消息发送请求"""
        if self._floating_ball:
            self._floating_ball.add_message("user", text)
        self._send_user_message(text)

    def _init_ui(self) -> None:
        self.setWindowTitle("SkillAgent")
        self.setGeometry(120, 120, config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
        self._set_window_icon()
        central = QWidget()
        central.setObjectName("skillAgentCentral")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 侧边栏状态
        self._sidebar_collapsed = False
        self._sidebar_default_width = 182
        
        # 创建左侧容器（侧边栏 + 切换按钮）
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        
        # 左侧边栏
        self.sidebar = ConversationSidebar()
        left_layout.addWidget(self.sidebar)
        
        # 切换按钮
        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setObjectName("skillAgentToggleButton")
        self._toggle_btn.setFixedWidth(24)
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        left_layout.addWidget(self._toggle_btn)
        
        # 右侧聊天区域
        chat_container = QWidget()
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(10, 10, 10, 10)
        chat_layout.setSpacing(8)
        
        self._setup_header(chat_layout)
        self._setup_chat_area(chat_layout)
        self._setup_input_area(chat_layout)
        
        layout.addWidget(left_container)
        layout.addWidget(chat_container, stretch=1)
        
        # 设置初始侧边栏宽度
        self.sidebar.setFixedWidth(self._sidebar_default_width)
        
        style = StyleManager.get_style("main_window_stylesheet")
        if style:
            self.setStyleSheet(style)
    
    def _set_window_icon(self) -> None:
        icon_path = paths.get_bundled_resource("application.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _init_tray_icon(self) -> None:
        icon_path = paths.get_bundled_resource("application.ico")
        if not icon_path.exists():
            self.tray_icon = None
            return

        icon = QIcon(str(icon_path))
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("SkillAgent")

        tray_menu = QMenu(self)
        
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)
        
        self._tray_recording_action = QAction("录音模式", self)
        self._tray_recording_action.triggered.connect(self._toggle_tray_recording)
        tray_menu.addAction(self._tray_recording_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_application)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_icon_activated)
        self.tray_icon.show()

    def _init_task_scheduler(self) -> None:
        self.task_scheduler = TaskScheduler(tray_icon=self.tray_icon, main_window=self)
        self.task_scheduler.start()

    def _tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()
    
    def _toggle_tray_recording(self) -> None:
        """切换托盘录音状态"""
        from recorder import is_onnx_model_loaded
        recorder = get_recorder()
        
        if recorder.is_recording:
            audio_path = recorder.stop_recording()
            self._tray_recording_action.setText("录音模式")
            
            if audio_path:
                self._process_recording_for_conversation(audio_path)
        else:
            # 在开始录音前先检查模型是否已加载
            if not is_onnx_model_loaded():
                QMessageBox.warning(
                    self, 
                    "提示", 
                    "语音模型未加载，请先在设置页面点击「加载模型」按钮加载模型，然后再使用录音功能。"
                )
                return
            success = recorder.start_recording()
            if success:
                self._tray_recording_action.setText("停止录音")

    def _process_recording_for_conversation(self, audio_path: Path, text: str = "") -> None:
        """处理录音文件：转文本、创建会话并发送消息
        
        使用异步转录方式，避免阻塞 UI 线程
        """
        self._logger.info(f"_process_recording_for_conversation 被调用: audio_path={audio_path}, text={text}")
        
        # 如果已有转录任务在进行，提示用户
        if self._transcribe_worker is not None and self._transcribe_worker.isRunning():
            QMessageBox.warning(self, "提示", "已有转录任务在进行中，请等待完成或取消后再试。")
            return
        
        # 防止重复处理同一个录音文件
        audio_path_str = str(audio_path)
        if self._last_processed_recording == audio_path_str:
            self._logger.warning(f"检测到重复处理录音文件: {audio_path_str}，跳过")
            return
        self._last_processed_recording = audio_path_str
        
        from recorder import is_onnx_model_loaded
        recorder = get_recorder()
        
        # 如果已有文本，直接处理
        if text:
            self._logger.info(f"text 已提供: {text}")
            self._create_conversation_and_send(text)
            return
        
        # 检查模型是否已加载
        if not is_onnx_model_loaded():
            QMessageBox.warning(
                self, 
                "提示", 
                "语音模型未加载，请先在设置页面点击「加载模型」按钮加载模型，然后再使用录音功能。"
            )
            return
        
        # 检查音频时长是否超过限制
        duration = recorder.get_audio_duration(audio_path)
        max_duration = getattr(config, 'ASR_MAX_AUDIO_DURATION', 3600)
        show_warning = getattr(config, 'ASR_SHOW_DURATION_WARNING', True)
        
        if duration is not None and duration > max_duration:
            error_msg = f"音频时长 ({duration:.1f}秒) 超过限制 ({max_duration}秒)"
            self._logger.warning(error_msg)
            QMessageBox.warning(self, "音频时长超限", error_msg)
            return
        
        # 如果时长较长，显示警告提示
        if duration is not None and duration > 60 and show_warning:
            warning_result = QMessageBox.question(
                self,
                "音频时长提示",
                f"音频时长为 {duration:.1f} 秒，转录可能需要较长时间。\n\n是否继续转录？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if warning_result != QMessageBox.StandardButton.Yes:
                self._logger.info("用户取消长音频转录")
                return
        
        # 创建进度对话框
        self._transcribe_progress_dialog = QProgressDialog("正在转录音频...", "取消", 0, 100, self)
        self._transcribe_progress_dialog.setWindowTitle("语音转录")
        self._transcribe_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._transcribe_progress_dialog.setMinimumDuration(0)
        self._transcribe_progress_dialog.setValue(0)
        self._transcribe_progress_dialog.canceled.connect(self._on_transcribe_cancelled)
        
        # 定义转录完成回调
        def on_transcribe_finished(path: str, transcribed_text: str):
            self._logger.info(f"转录完成: path={path}, text={transcribed_text}")
            self._cleanup_transcribe_dialog()
            
            if not transcribed_text or not transcribed_text.strip():
                QMessageBox.warning(self, "转录失败", "转录结果为空，请重试。")
                return
            
            self._create_conversation_and_send(transcribed_text.strip())
        
        # 定义转录失败回调
        def on_transcribe_error(path: str, error: str):
            self._logger.error(f"转录失败: path={path}, error={error}")
            self._cleanup_transcribe_dialog()
            QMessageBox.warning(self, "转录失败", f"语音转录失败：{error}")
        
        # 定义转录进度回调
        def on_transcribe_progress(progress: int, status: str):
            if self._transcribe_progress_dialog:
                self._transcribe_progress_dialog.setValue(progress)
                self._transcribe_progress_dialog.setLabelText(status)
        
        # 启动异步转录
        self._transcribe_worker = recorder.transcribe_audio_async(
            audio_path,
            callback=lambda path, text, error: (
                on_transcribe_finished(path, text) if error is None else on_transcribe_error(path, error)
            ),
            progress_callback=on_transcribe_progress
        )
        
        if self._transcribe_worker is None:
            self._cleanup_transcribe_dialog()
            QMessageBox.warning(self, "转录失败", "无法启动转录任务，请重试。")
    
    def _cleanup_transcribe_dialog(self):
        """清理转录进度对话框"""
        if self._transcribe_progress_dialog:
            self._transcribe_progress_dialog.close()
            self._transcribe_progress_dialog.deleteLater()
            self._transcribe_progress_dialog = None
    
    def _on_transcribe_cancelled(self):
        """处理转录取消"""
        self._logger.info("用户取消转录")
        if self._transcribe_worker and self._transcribe_worker.isRunning():
            self._transcribe_worker.requestInterruption()
            self._transcribe_worker.wait(2000)
        self._transcribe_worker = None
        self._cleanup_transcribe_dialog()
    
    def _create_conversation_and_send(self, text: str) -> None:
        """创建新会话并发送消息"""
        if not text or not text.strip():
            self._logger.warning("文本为空，返回")
            return
        
        text = text.strip()
        
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "提示", "当前仍有对话在执行，请结束后再发送录音消息。")
            return
        
        cid, _ = self.skill_agent.start_new_conversation(
            conversation_type='record_conversation'
        )
        self.skill_agent.set_conversation_id(cid)
        
        self._logger.info(f"创建新会话: {cid}")
        
        tab = self._add_conversation(cid, f"录音会话-{cid[:5]}", pending_db_history=False)
        
        # 获取对话信息并添加到侧边栏
        conv = self._memory.get_conversation(cid)
        if conv:
            self.sidebar.add_conversation(conv)
        
        self._switch_to_conversation(cid)
        
        self._logger.info(f"调用 _send_user_message，text: {text}")
        self._send_user_message(text, session_tab=tab)

    def _enter_background_mode(self) -> None:
        self._is_background_mode = True
        delay_ms = config.MEMORY_OPTIMIZATION_DELAY_SECONDS * 1000
        self._memory_optimization_timer = QTimer()
        self._memory_optimization_timer.setSingleShot(True)
        self._memory_optimization_timer.timeout.connect(self._optimize_memory_for_background)
        self._memory_optimization_timer.start(delay_ms)
        self._logger.info(f"进入后台模式，将在 {config.MEMORY_OPTIMIZATION_DELAY_SECONDS} 秒后执行内存优化")

    def _exit_background_mode(self) -> None:
        self._is_background_mode = False
        if self._memory_optimization_timer is not None:
            self._memory_optimization_timer.stop()
            self._memory_optimization_timer.deleteLater()
            self._memory_optimization_timer = None
        tab = self._active_session_tab()
        if tab is not None:
            tab.restore_ui_cache(self.skill_agent)
        self._logger.info("退出后台模式，已恢复 UI 缓存")

    def _optimize_memory_for_background(self) -> None:
        if not config.MEMORY_OPTIMIZATION_ENABLED:
            return
        if not self._is_background_mode:
            return
        if self.worker_thread is not None and self.worker_thread.isRunning():
            return
        released_count = 0
        active_tab = self._active_session_tab()
        for cid, tab in self._conversation_tabs.items():
            if tab is not active_tab:
                tab.release_ui_cache()
                released_count += 1
        if active_tab is not None:
            active_tab.release_ui_cache()
        self.skill_agent.clear_runtime_cache()
        gc.collect()
        self._logger.info(f"后台模式内存优化完成，释放了 {released_count} 个会话标签页缓存")

    def _show_window(self) -> None:
        self._logger.info(f"显示窗口 - 后台模式: {self._background}")
        self.show()
        self.raise_()
        self.activateWindow()
        self._exit_background_mode()

    def _quit_application(self) -> None:
        if self.stream_renderer.is_active():
            self.stream_renderer.complete()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait(2000)
        # 清理转录任务
        if self._transcribe_worker and self._transcribe_worker.isRunning():
            self._transcribe_worker.requestInterruption()
            self._transcribe_worker.wait(2000)
        self._cleanup_transcribe_dialog()
        if hasattr(self, 'task_scheduler'):
            self.task_scheduler.stop()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _setup_header(self, layout: QVBoxLayout) -> None:
        # 头部区域暂时为空，后续可添加其他元素
        pass
    
    def _setup_chat_area(self, layout: QVBoxLayout) -> None:
        # 创建一个容器来容纳当前显示的会话
        self.chat_area_container = QWidget()
        self.chat_area_layout = QVBoxLayout(self.chat_area_container)
        self.chat_area_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_area_layout.setSpacing(0)
        layout.addWidget(self.chat_area_container, stretch=1)

    def _create_toolbar_button(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("skillAgentToolbarButton")
        btn.setFont(QFont("Microsoft YaHei", 9))
        btn.setFixedHeight(28)
        btn.clicked.connect(callback)
        return btn

    def _setup_input_area(self, layout: QVBoxLayout) -> None:
        self._file_upload_area = FileUploadArea(self.file_upload_controller, self)
        layout.addWidget(self._file_upload_area)
        
        input_container = QWidget()
        input_container.setObjectName("skillAgentInputContainer")
        container_layout = QHBoxLayout(input_container)
        container_layout.setContentsMargins(8, 8, 8, 8)
        container_layout.setSpacing(8)
        
        self.input_edit = MultiLineInputEdit()
        self.input_edit.setPlaceholderText(UIState.PLACEHOLDER_DEFAULT)
        self.input_edit.setFont(QFont("Microsoft YaHei", 10))
        self.input_edit.setMinimumHeight(36)
        self.input_edit.setMaximumHeight(120)
        self.input_edit.set_send_callback(self._on_send)
        
        self._file_upload_btn = self._file_upload_area.create_upload_button()
        
        self.vortex_btn = QPushButton("🌀")
        self.vortex_btn.setObjectName("skillAgentVortexButton")
        self.vortex_btn.setFixedSize(26, 26)
        self.vortex_btn.setProperty("thinking", "false")
        self.vortex_btn.clicked.connect(self._on_vortex_clicked)
        
        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("skillAgentSendButton")
        self.send_btn.setFixedSize(26, 26)
        self.send_btn.clicked.connect(self._on_send)
        
        container_layout.addWidget(self.input_edit, stretch=1)
        container_layout.addWidget(self._file_upload_btn)
        container_layout.addWidget(self.vortex_btn)
        container_layout.addWidget(self.send_btn)
        layout.addWidget(input_container)

    def _connect_signals(self) -> None:
        self.ui_state.send_button_changed.connect(self.send_btn.setEnabled)
        self.ui_state.stop_button_changed.connect(self._on_stop_button_changed)
        self.ui_state.input_placeholder_changed.connect(self.input_edit.setPlaceholderText)
        self.message_handler.assistant_message.connect(self._on_assistant_message)
        self.message_handler.think_message.connect(self._on_think_message)
        self.message_handler.tool_message.connect(self._on_tool_message)
        self.message_handler.await_user_message.connect(self._on_await_user_message)
        self.message_handler.skill_content_message.connect(self._on_skill_content_message)
        self.message_handler.tool_call_message.connect(self._on_tool_call_message)
        self.message_handler.token_usage_message.connect(self._on_token_usage_message)
        # 连接侧边栏信号
        self.sidebar.new_conversation_requested.connect(self._on_new_conversation)
        self.sidebar.conversation_selected.connect(self._on_conversation_selected)
        self.sidebar.conversation_deleted.connect(self._on_conversation_deleted)
        self.sidebar.settings_requested.connect(self._open_settings)
        # 连接文件上传控制器信号
        self.file_upload_controller.asr_model_not_loaded.connect(self._on_asr_model_not_loaded)

    def _populate_initial_conversations(self) -> None:
        all_sessions = [c for c in self.skill_agent.list_saved_conversations() if (c.conversation_id or "").strip()]
        sessions_with_messages = []
        for conv in all_sessions:
            cid = (conv.conversation_id or "").strip()
            if cid and self._memory.get_message_records(cid):
                sessions_with_messages.append(conv)
        if not sessions_with_messages:
            self._create_new_conversation()
            return
        for conv in sessions_with_messages:
            self._add_conversation((conv.conversation_id or "").strip(), conv.title, pending_db_history=True)
        self.sidebar.load_conversations(sessions_with_messages)
        first_cid = (sessions_with_messages[0].conversation_id or "").strip()
        self._switch_to_conversation(first_cid)

    def _add_conversation(self, conversation_id: str, title: str | None = None, pending_db_history: bool = False) -> ChatSessionTab:
        tab = ChatSessionTab(conversation_id, pending_db_history=pending_db_history)
        display_title = title or f"新会话 · {conversation_id[:5] if len(conversation_id) >= 5 else conversation_id or '?'}"
        self._conversation_tabs[conversation_id] = tab
        self.session_state.add_conversation(conversation_id, title=display_title, pending_db_history=pending_db_history)
        return tab

    def _create_new_conversation(self) -> str:
        cid, title = self.skill_agent.start_new_conversation(conversation_type='agent_conversation')
        self._add_conversation(cid, title, pending_db_history=False)
        from memory.conversation import Conversation
        conv = self._memory.get_conversation(cid)
        if conv:
            self.sidebar.add_conversation(conv)
        else:
            conv = Conversation(cid, self.skill_agent.username, title)
            self.sidebar.add_conversation(conv)
        self._switch_to_conversation(cid)
        return cid

    def create_conversation_for_scheduled_task(self, task: ScheduledTask) -> str | None:
        """
        为定时任务创建新会话并自动执行。
        
        Args:
            task: 定时任务对象，包含 title、skill_ids、execution_chain 等信息
            
        Returns:
            新会话的 conversation_id，如果创建失败则返回 None
        """
        if self.worker_thread and self.worker_thread.isRunning():
            return None
        
        # 仅在配置为 true 时才自动弹出窗口
        if (self.isHidden() or not self.isVisible()) and config.SCHEDULED_TASK_SHOW_WINDOW:
            self._show_window()
        
        cid, _ = self.skill_agent.start_new_conversation()
        self.skill_agent.set_conversation_id(cid)
        
        self._memory.ensure_conversation(cid, title=task.title)
        
        if task.skill_ids:
            self._memory.set_active_skills(cid, task.skill_ids)
        
        tab = self._add_conversation(cid, task.title, pending_db_history=False)
        
        from memory.conversation import Conversation
        conv = self._memory.get_conversation(cid)
        if conv:
            self.sidebar.add_conversation(conv)
        else:
            conv = Conversation(cid, self.skill_agent.username, task.title)
            self.sidebar.add_conversation(conv)
        
        self._switch_to_conversation(cid)
        
        user_message = self._build_execution_chain_message(task)
        
        self._send_user_message(user_message, session_tab=tab)
        
        return cid

    def _build_execution_chain_message(self, task: ScheduledTask) -> str:
        """
        从定时任务的 execution_chain 构建用户消息。
        
        Args:
            task: 定时任务对象
            
        Returns:
            格式化后的用户消息文本
        """
        if not task.execution_chain:
            return f"请执行以下任务：{task.title}"
        
        try:
            chain_data = json.loads(task.execution_chain)
        except json.JSONDecodeError:
            return f"请执行以下任务：{task.title}\n\n{task.content}"
        
        goal = chain_data.get("goal", task.title)
        skills = chain_data.get("skills", [])
        steps = chain_data.get("steps", [])
        
        message_parts = [f"请执行以下任务："]
        message_parts.append(f"目标：{goal}")
        
        if skills:
            skills_str = "、".join(skills)
            message_parts.append(f"相关技能：{skills_str}")
        
        if steps:
            message_parts.append("执行步骤：")
            for i, step in enumerate(steps, 1):
                message_parts.append(f"{i}. {step}")
        
        # if task.content and task.content.strip():
        #     message_parts.append(f"\n补充说明：{task.content}")
        
        return "\n".join(message_parts)

    def _active_session_tab(self) -> ChatSessionTab | None:
        return self._current_conversation_tab

    def _switch_to_conversation(self, conversation_id: str) -> None:
        """切换到指定会话"""
        if self._current_conversation_tab:
            self._current_conversation_tab.setParent(None)
        
        if conversation_id not in self._conversation_tabs:
            return
        
        new_tab = self._conversation_tabs[conversation_id]
        
        self.chat_area_layout.addWidget(new_tab)
        self._current_conversation_tab = new_tab
        
        self.skill_agent.set_conversation_id(conversation_id)
        self.session_state.set_current_conversation(conversation_id)
        self.sidebar.set_selected_conversation(conversation_id)
        
        self.file_upload_controller.clear_all_files()
        
        self._ensure_tab_history_loaded(new_tab)
        
        # 更新输入框提示
        self._sync_input_placeholder()

    def _ensure_tab_history_loaded(self, tab: ChatSessionTab) -> None:
        if not tab.pending_db_history:
            return
        tab.pending_db_history = False
        records = self.skill_agent.message_records_for_conversation(tab.conversation_id)
        self._replay_messages(tab, records)
        if SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id):
            self._restore_await_user_panel(tab, records)
        if self._current_conversation_tab is tab:
            self._sync_input_placeholder()

    def _replay_messages(self, tab: ChatSessionTab, records: list) -> None:
        show_tool = config.SKILL_AGENT_UI_SHOW_TOOL_CALLS
        from llm.llm_config_manager import get_current_config
        current_config = get_current_config()
        show_thinking = current_config.enable_thinking
        from ui.utils.file_upload_manager import UploadedFileInfo
        
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
                files = [UploadedFileInfo.from_dict(d) for d in file_dicts]
            card = tab.message_list.add_message(msg_type, content, token_usage=token_usage, files=files)
            
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

    def _on_conversation_selected(self, conversation_id: str) -> None:
        """侧边栏会话被选中"""
        self._switch_to_conversation(conversation_id)

    def _on_conversation_deleted(self, conversation_id: str) -> None:
        """侧边栏会话删除请求"""
        if self.worker_thread and self.worker_thread.isRunning() and conversation_id == self.worker_thread.conversation_id:
            QMessageBox.warning(self, "提示", "该会话正在执行中，请结束后再删除。")
            return
        
        # 检查是否只剩一个会话
        if len(self._conversation_tabs) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个会话。")
            return
        
        # 如果删除的是当前会话，切换到另一个会话
        if self._current_conversation_tab and self._current_conversation_tab.conversation_id == conversation_id:
            # 找到另一个会话
            for cid in self._conversation_tabs.keys():
                if cid != conversation_id:
                    self._switch_to_conversation(cid)
                    break
        
        # 更新UI - 先删除侧边栏中的会话项
        self.sidebar.remove_conversation(conversation_id)
        
        # 删除会话
        self._memory.clear_conversation(conversation_id)
        self.session_state.remove_conversation(conversation_id)
        
        # 移除会话标签
        if conversation_id in self._conversation_tabs:
            tab = self._conversation_tabs[conversation_id]
            tab.deleteLater()
            del self._conversation_tabs[conversation_id]

    def _sync_input_placeholder(self) -> None:
        tab = self._active_session_tab()
        if tab is None:
            self.ui_state.set_input_placeholder(UIState.PLACEHOLDER_DEFAULT)
        else:
            self.ui_state.set_awaiting_user_mode(SkillAgent.conversation_awaits_user_clarification(self._memory, tab.conversation_id))

    def _on_new_conversation(self) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "提示", "当前仍有对话在执行，请结束后再新建会话。")
            return
        self._create_new_conversation()

    def _open_settings(self) -> None:
        SettingsDialog(self, self.skill_agent).exec()

    def _on_send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入内容")
            return
        self._send_user_message(text)

    def _on_vortex_clicked(self) -> None:
        enabled = self.ui_state.toggle_enable_thinking()
        self.vortex_btn.setProperty("thinking", "true" if enabled else "false")
        self.vortex_btn.style().unpolish(self.vortex_btn)
        self.vortex_btn.style().polish(self.vortex_btn)
        self.vortex_btn.update()

    def _on_stop_button_changed(self, show_stop: bool) -> None:
        if show_stop:
            try:
                self.send_btn.clicked.disconnect(self._on_send)
            except RuntimeError:
                pass
            self.send_btn.setObjectName("skillAgentStopButton")
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
            self.send_btn.setObjectName("skillAgentSendButton")
            self.send_btn.setText("↑")
            self.send_btn.clicked.connect(self._on_send)
            self.send_btn.setFixedSize(26, 26)
            self.send_btn.style().unpolish(self.send_btn)
            self.send_btn.style().polish(self.send_btn)
            self.send_btn.update()

    def _on_stop(self) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.request_stop()
        if self.stream_renderer.is_active():
            self.stream_renderer.complete()
        self.send_btn.setEnabled(False)
        self.send_btn.setText("")

    def _send_user_message(self, text: str, *, session_tab: ChatSessionTab | None = None) -> None:
        text = (text or "").strip()
        if not text or (self.worker_thread and self.worker_thread.isRunning()):
            return
        tab = session_tab or self._active_session_tab()
        if tab is None:
            return
        
        uploaded_files_content = ""
        uploaded_files = []
        if self.file_upload_controller.has_files():
            uploaded_files_content = self.file_upload_controller.generate_combined_full_content()
            uploaded_files = self.file_upload_controller.get_all_files()
            self.file_upload_controller.clear_all_files()
        
        self.skill_agent.set_uploaded_files_content(uploaded_files_content)
        self.skill_agent.set_conversation_id(tab.conversation_id)
        tab.add_message("user", text, files=uploaded_files)
        tab.clear_await_user_ui()
        self.input_edit.clear()
        self.ui_state.set_task_running(True)
        enable_thinking = self.ui_state.get_enable_thinking()
        # Save file info to memory
        if uploaded_files:
            from ui.utils.file_upload_manager import UploadedFileInfo
            file_dicts = [f.to_dict() for f in uploaded_files]
            # Save to skill agent to store in message metadata
            self.skill_agent._last_uploaded_files = file_dicts
        else:
            self.skill_agent._last_uploaded_files = None
        self.worker_thread = SkillAgentWorkerThread(
            self.skill_agent, text, conversation_id=tab.conversation_id, 
            session_tab=tab, enable_thinking=enable_thinking
        )
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
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.add_message("assistant", message)
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
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.add_message("think", message)
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
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.add_message("tool", message)

    def _on_tool_call_message(self, message: str, session_tab: ChatSessionTab) -> None:
        """处理工具调用消息"""
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.add_message("tool_call", message)
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.add_message("tool_call", message)

    def _on_skill_content_message(self, message: str, session_tab: ChatSessionTab) -> None:
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.add_message("user", message)
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.add_message("user", message)

    def _on_token_usage_message(self, token_usage: dict, session_tab: ChatSessionTab) -> None:
        """处理token_usage消息，将token用量信息传递给stream_renderer"""
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete(token_usage)
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.finalize_last_message(token_usage)

    def _on_await_user_message(self, spec: dict, session_tab: ChatSessionTab) -> None:
        if self.stream_renderer.is_active():
            conv_id = self.stream_renderer.get_conversation_id()
            if conv_id == session_tab.conversation_id:
                self.stream_renderer.complete()
        session_tab.show_await_user_prompt(spec, on_confirm_send=lambda t, st=session_tab: self._send_user_message(t, session_tab=st))
        # 同步到悬浮球
        if self._floating_ball:
            self._floating_ball.show_await_user_prompt(spec, on_confirm_send=lambda t: self._on_floating_ball_send_message(t))

    def _on_worker_finished(self, result: str, session_tab) -> None:
        self.ui_state.set_task_running(False)
        if isinstance(session_tab, ChatSessionTab):
            stream_text = ""
            if self.stream_renderer.is_active():
                conv_id = self.stream_renderer.get_conversation_id()
                if conv_id == session_tab.conversation_id:
                    stream_text = self.stream_renderer.complete() or ""
            
            logger.debug(f"finish: result={result!r}, stream_text={stream_text!r}")
            
            if result != SKILL_AGENT_AWAITING_USER_REPLY:
                session_tab.clear_await_user_ui()
                # 同步到悬浮球
                if self._floating_ball:
                    self._floating_ball.clear_await_user_ui()
                # 检查是否需要添加最终结果
                if result and result.strip():
                    # 如果流式渲染没有内容或者内容只有"(完成)"这类提示，或者已经通过token_usage完成了渲染
                    has_stream_content = (stream_text.strip() and "(完成)" not in stream_text) or self.stream_renderer.has_completed_with_token_usage()
                    if not has_stream_content:
                        session_tab.add_message("assistant", result)
                        # 同步到悬浮球
                        if self._floating_ball:
                            self._floating_ball.add_message("assistant", result)
        self._sync_input_placeholder()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        tab = self._active_session_tab()
        if tab:
            tab.message_list.update_all_cards_width()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._logger.info(f"MainWindow.showEvent() 触发，isVisible() = {self.isVisible()}")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._ensure_first_tab_layout_correct)
        # 主窗口显示时隐藏悬浮球
        if self._floating_ball:
            self._logger.info(f"MainWindow.showEvent(): 悬浮球存在，调用 hide()")
            self._floating_ball.hide()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._logger.info(f"MainWindow.hideEvent() 触发，isVisible() = {self.isVisible()}")
        # 主窗口隐藏时显示悬浮球
        if self._floating_ball:
            self._logger.info(f"MainWindow.hideEvent(): 悬浮球存在，调用 show()")
            self._floating_ball.show()

    def _ensure_first_tab_layout_correct(self) -> None:
        tab = self._active_session_tab()
        if tab:
            tab.message_list.update_all_cards_width()
            tab.scroll_to_bottom()

    def closeEvent(self, event) -> None:
        event.ignore()
        
        from PySide6.QtWidgets import QDialog, QLabel, QHBoxLayout, QVBoxLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle("关闭确认")
        dialog.setFixedSize(500, 150)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        label = QLabel("请选择关闭方式：")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        minimize_btn = QPushButton("最小化到托盘")
        minimize_btn.setObjectName("skillAgentCloseDialogMinimizeButton")
        minimize_style = StyleManager.get_style("close_dialog_minimize_button")
        if minimize_style:
            minimize_btn.setStyleSheet(minimize_style)

        floating_btn = QPushButton("悬浮球模式")
        floating_btn.setObjectName("skillAgentCloseDialogFloatingButton")
        floating_style = StyleManager.get_style("close_dialog_floating_button")
        if floating_style:
            floating_btn.setStyleSheet(floating_style)

        close_btn = QPushButton("直接关闭")
        close_btn.setObjectName("skillAgentCloseDialogCloseButton")
        close_style = StyleManager.get_style("close_dialog_close_button")
        if close_style:
            close_btn.setStyleSheet(close_style)
        
        btn_layout.addWidget(minimize_btn)
        btn_layout.addWidget(floating_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        minimize_btn.clicked.connect(lambda: (
            self._logger.info(f"最小化到托盘 - 后台模式: {self._background}"),
            self.hide(),
            self._enter_background_mode(),
            dialog.done(1)
        ))
        
        def switch_to_floating():
            self._logger.info(f"切换到悬浮球模式")
            self.hide()
            self._enter_background_mode()
            dialog.done(3)
        
        floating_btn.clicked.connect(switch_to_floating)
        
        close_btn.clicked.connect(lambda: (
            self._cleanup_and_close(),
            dialog.done(2)
        ))
        
        dialog.exec()

    def _toggle_sidebar(self) -> None:
        """切换侧边栏的折叠/展开状态"""
        self._sidebar_collapsed = not self._sidebar_collapsed
        
        if self._sidebar_collapsed:
            # 折叠侧边栏
            self.sidebar.setFixedWidth(0)
            self.sidebar.hide()
            self._toggle_btn.setText("▶")
        else:
            # 展开侧边栏
            self.sidebar.setFixedWidth(self._sidebar_default_width)
            self.sidebar.show()
            self._toggle_btn.setText("◀")
    
    def _cleanup_and_close(self) -> None:
        if self.stream_renderer.is_active():
            self.stream_renderer.complete()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait(2000)
        # 清理转录任务
        if self._transcribe_worker and self._transcribe_worker.isRunning():
            self._transcribe_worker.requestInterruption()
            self._transcribe_worker.wait(2000)
        self._cleanup_transcribe_dialog()
        if hasattr(self, 'task_scheduler'):
            self.task_scheduler.stop()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
