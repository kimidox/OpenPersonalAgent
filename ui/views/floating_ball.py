from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QPoint, Signal, QPropertyAnimation, QEasingCurve, QTimer, QEvent
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QWidget, QPushButton, QMenu, QApplication

from resource_path import paths
from ui.styles import StyleManager
from ui.views.floating_chat_window import FloatingChatWindow
from logger import get_logger
from recorder import get_recorder


class FloatingBallButton(QPushButton):
    """自定义悬浮球按钮，不拦截拖动事件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_floating_ball = parent
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_click_timeout)
        self._is_possible_click = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_possible_click = True
            self._click_timer.start(150)
        self._parent_floating_ball.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._is_possible_click = False
        self._parent_floating_ball.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_possible_click and self._click_timer.isActive():
                self._click_timer.stop()
                self.clicked.emit()
            self._is_possible_click = False
        self._parent_floating_ball.mouseReleaseEvent(event)

    def _on_click_timeout(self):
        self._is_possible_click = False

    def contextMenuEvent(self, event):
        self._parent_floating_ball.contextMenuEvent(event)


class FloatingBall(QWidget):
    """悬浮球组件，支持拖动、右键菜单和展开会话窗口"""

    show_main_window = Signal()
    quit_application = Signal()
    send_message_requested = Signal(str)
    recording_started = Signal()
    recording_stopped = Signal(Path)
    create_recording_conversation = Signal(Path, str)
    show_model_not_loaded_warning = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = get_logger()
        self._is_dragging = False
        self._drag_position = QPoint()
        self._chat_window = None
        self._is_expanded = False
        self._animation = None
        
        self._logger.info("FloatingBall: 开始初始化")
        self._init_ui()
        self._init_style()
        self._init_position()
        self._init_chat_window()
        # 所有初始化完成后最后隐藏，确保不会被任何操作触发显示
        self._logger.info("FloatingBall: 初始化完成，调用 hide()")
        self.hide()
        self._logger.info(f"FloatingBall: hide() 调用后，isVisible() = {self.isVisible()}")

    def _init_ui(self):
        """初始化UI"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(30, 30)

        # 创建按钮
        self.button = FloatingBallButton(self)
        self.button.setFixedSize(30, 30)
        self.button.setObjectName("floatingBallButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)

        # 不设置任何文本或图标，保持纯色

        # 创建右键菜单
        self._init_context_menu()

        # 连接信号
        self.button.clicked.connect(self._on_button_clicked)

    def _init_style(self):
        """初始化样式"""
        style = StyleManager.get_style("floating_ball_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _init_position(self):
        """初始化位置 - 默认屏幕右下角"""
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        x = screen_geometry.width() - self.width() - 20
        y = screen_geometry.height() - self.height() - 20
        self.move(x, y)

    def _init_chat_window(self):
        """初始化聊天窗口"""
        self._chat_window = FloatingChatWindow()
        self._chat_window.hide()
        # 浮动聊天窗口现在独立处理消息，不需要转发
        self._chat_window.close_requested.connect(self._collapse_chat_window)

    def _init_context_menu(self):
        """初始化右键菜单"""
        self.menu = QMenu(self)
        
        toggle_action = QAction("展开聊天窗口", self)
        toggle_action.triggered.connect(self._toggle_chat_window)
        self.menu.addAction(toggle_action)
        
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show_main_window.emit)
        self.menu.addAction(show_action)
        
        self.menu.addSeparator()
        
        self._recording_action = QAction("录音模式", self)
        self._recording_action.triggered.connect(self._toggle_recording)
        self.menu.addAction(self._recording_action)
        
        self.menu.addSeparator()
        
        quit_action = QAction("退出应用", self)
        quit_action.triggered.connect(self.quit_application.emit)
        self.menu.addAction(quit_action)

    def _on_button_clicked(self):
        """按钮点击事件 - 切换聊天窗口展开/收起"""
        self._toggle_chat_window()
    
    def _toggle_recording(self):
        """切换录音状态"""
        from recorder import is_model_loaded
        recorder = get_recorder()
        
        if recorder.is_recording:
            audio_path = recorder.stop_recording()
            self._recording_action.setText("录音模式")
            
            if audio_path:
                self.recording_stopped.emit(audio_path)
                # 只发送音频路径，让主窗口统一处理转文本和创建会话
                self.create_recording_conversation.emit(audio_path, "")
        else:
            # 在开始录音前先检查模型是否已加载
            if not is_model_loaded():
                # 我们通过信号让主窗口来显示提示，避免在悬浮球中直接显示对话框导致的问题
                self.show_model_not_loaded_warning.emit()
                return
            success = recorder.start_recording()
            if success:
                self._recording_action.setText("停止录音")
                self.recording_started.emit()

    def _toggle_chat_window(self):
        """切换聊天窗口的展开/收起状态"""
        if self._is_expanded:
            self._collapse_chat_window()
        else:
            self._expand_chat_window()

    def _expand_chat_window(self):
        """展开聊天窗口"""
        if not self._chat_window:
            return
            
        # 计算聊天窗口位置
        self._position_chat_window()
        
        # 显示聊天窗口
        self._chat_window.show()
        self._chat_window.raise_()
        
        # 添加淡入动画
        self._chat_window.setWindowOpacity(0.0)
        self._animation = QPropertyAnimation(self._chat_window, b"windowOpacity")
        self._animation.setDuration(200)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation.start()
        
        self._is_expanded = True

    def _collapse_chat_window(self):
        """收起聊天窗口"""
        if not self._chat_window or not self._is_expanded:
            return
            
        # 添加淡出动画
        self._animation = QPropertyAnimation(self._chat_window, b"windowOpacity")
        self._animation.setDuration(200)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation.finished.connect(lambda: self._chat_window.hide())
        self._animation.start()
        
        self._is_expanded = False

    def _position_chat_window(self):
        """根据悬浮球位置定位聊天窗口"""
        if not self._chat_window:
            return
            
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        ball_rect = self.geometry()
        chat_width = self._chat_window.width()
        chat_height = self._chat_window.height()
        
        # 判断应该放在左边还是右边
        if ball_rect.right() + chat_width <= screen_geometry.right():
            # 右边有足够空间
            x = ball_rect.right() + 10
        else:
            # 右边空间不足，放在左边
            x = ball_rect.left() - chat_width - 10
            
        # 判断应该放在上方还是下方
        if ball_rect.top() - chat_height >= screen_geometry.top():
            # 上方有足够空间
            y = ball_rect.top() - chat_height
        else:
            # 上方空间不足，放在下方
            y = ball_rect.bottom() + 10
            
        # 确保窗口不会超出屏幕边界
        if x < screen_geometry.left():
            x = screen_geometry.left()
        if y < screen_geometry.top():
            y = screen_geometry.top()
        if x + chat_width > screen_geometry.right():
            x = screen_geometry.right() - chat_width
        if y + chat_height > screen_geometry.bottom():
            y = screen_geometry.bottom() - chat_height
            
        self._chat_window.move(x, y)

    def mousePressEvent(self, event):
        """鼠标按下事件 - 开始拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            # 右键显示菜单
            self.menu.exec_(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 拖动"""
        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            # 如果聊天窗口已展开，同步移动
            if self._is_expanded and self._chat_window:
                self._position_chat_window()
            event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件 - 结束拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            event.accept()

    def contextMenuEvent(self, event):
        """右键菜单事件"""
        self.menu.exec_(event.globalPosition().toPoint())
    
    def add_message(self, msg_type: str, content: str, token_usage: dict = None, files: list = None):
        """向聊天窗口添加消息"""
        if self._chat_window:
            self._chat_window.add_message(msg_type, content, token_usage, files)
    
    def update_last_message(self, content: str) -> bool:
        """更新聊天窗口最后一条消息"""
        if self._chat_window:
            return self._chat_window.update_last_message(content)
        return False
    
    def append_to_last_message(self, text: str) -> bool:
        """追加到聊天窗口最后一条消息"""
        if self._chat_window:
            return self._chat_window.append_to_last_message(text)
        return False
    
    def finalize_last_message(self, token_usage: dict = None) -> bool:
        """完成聊天窗口最后一条消息"""
        if self._chat_window:
            return self._chat_window.finalize_last_message(token_usage)
        return False
    
    def scroll_to_bottom(self):
        """滚动到聊天窗口底部"""
        if self._chat_window:
            self._chat_window.scroll_to_bottom()
    
    def clear_messages(self):
        """清除聊天窗口所有消息"""
        if self._chat_window:
            self._chat_window.clear_messages()
    
    def show_await_user_prompt(self, spec: dict, on_confirm_send=None):
        """显示等待用户提示"""
        if self._chat_window:
            self._chat_window.show_await_user_prompt(spec, on_confirm_send)
    
    def clear_await_user_ui(self):
        """清除等待用户UI"""
        if self._chat_window:
            self._chat_window.clear_await_user_ui()
    
    def has_active_await_user_prompt(self) -> bool:
        """检查是否有活跃的等待用户提示"""
        if self._chat_window:
            return self._chat_window.has_active_await_user_prompt()
        return False
    
    def show(self):
        """显示悬浮球"""
        self._logger.info(f"FloatingBall.show() 调用，当前 isVisible() = {self.isVisible()}")
        super().show()
        self._logger.info(f"FloatingBall.show() 完成，现在 isVisible() = {self.isVisible()}")
    
    def hide(self):
        """隐藏悬浮球"""
        self._logger.info(f"FloatingBall.hide() 调用，当前 isVisible() = {self.isVisible()}")
        super().hide()
        self._logger.info(f"FloatingBall.hide() 完成，现在 isVisible() = {self.isVisible()}")
