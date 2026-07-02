from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING
from PySide6.QtCore import Qt, QPoint, Signal, QPropertyAnimation, QEasingCurve, QTimer, QEvent, QRectF
from PySide6.QtGui import QIcon, QAction, QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QWidget, QPushButton, QMenu, QApplication, QLabel, QGraphicsOpacityEffect

from resource_path import paths
from ui.styles import StyleManager
from ui.views.floating_chat_window import FloatingChatWindow
from logger import get_logger
from recorder import get_recorder
import config

if TYPE_CHECKING:
    pass


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


class RealtimeRecognitionPopup(QWidget):
    """实时识别结果弹出窗口"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._is_final = False
        self._animation_opacity = 1.0
        self._dot_count = 0
        self._max_dots = 3
        
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self._init_ui()
        self._init_animation()
        
    def _init_ui(self):
        """初始化 UI"""
        # 设置固定宽度和最小高度，高度会根据文本动态调整
        self.setFixedWidth(320)
        self.setMinimumHeight(60)
        
        # 主布局
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label.setWordWrap(True)
        self._label.setGeometry(15, 10, 290, 40)
        
        # 设置字体
        font = QFont()
        font.setPointSize(11)
        self._label.setFont(font)
        
        # 设置样式
        self.setStyleSheet("""
            RealtimeRecognitionPopup {
                background-color: rgba(30, 30, 30, 230);
                border-radius: 10px;
            }
            QLabel {
                color: #FFFFFF;
                background: transparent;
            }
        """)
        
    def _init_animation(self):
        """初始化动画"""
        # 闪烁动画定时器
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._on_blink_timeout)
        
        # 不透明度动画
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        
    def _on_blink_timeout(self):
        """闪烁动画定时器回调"""
        if self._is_final:
            return
            
        self._dot_count = (self._dot_count + 1) % (self._max_dots + 1)
        self.update()
        
    def start_animation(self):
        """开始动画"""
        self._blink_timer.start(500)  # 每 500ms 更新一次
        
    def stop_animation(self):
        """停止动画"""
        self._blink_timer.stop()
        self._dot_count = 0
        self.update()
        
    def set_text(self, text: str, is_final: bool = False):
        """设置识别文本
        
        Args:
            text: 识别文本
            is_final: 是否为最终结果
        """
        self._text = text
        self._is_final = is_final
        
        if is_final:
            self.stop_animation()
            display_text = text if text else "识别完成"
        else:
            # 部分结果，显示识别中状态
            display_text = text if text else "正在识别..."
            
        # 设置文本
        self._label.setText(display_text)
        
        # 根据文本内容动态调整高度
        self._adjust_height()
        
        if is_final:
            # 最终结果时改变背景色
            self.setStyleSheet("""
                RealtimeRecognitionPopup {
                    background-color: rgba(46, 125, 50, 230);
                    border-radius: 10px;
                }
                QLabel {
                    color: #FFFFFF;
                    background: transparent;
                }
            """)
        else:
            # 恢复正常背景色
            self.setStyleSheet("""
                RealtimeRecognitionPopup {
                    background-color: rgba(30, 30, 30, 230);
                    border-radius: 10px;
                }
                QLabel {
                    color: #FFFFFF;
                    background: transparent;
                }
            """)
            
        self.update()
        
    def _adjust_height(self):
        """根据文本内容调整窗口高度"""
        # 计算文本所需的高度
        from PySide6.QtCore import Qt
        
        # 获取文本的字体度量
        font_metrics = self._label.fontMetrics()
        text_width = 290  # 标签宽度
        
        # 计算文本所需的行数和高度
        text_rect = font_metrics.boundingRect(0, 0, text_width, 0, 
                                                Qt.TextFlag.TextWordWrap, 
                                                self._text if self._text else "正在识别...")
        text_height = text_rect.height()
        
        # 计算窗口高度：文本高度 + 上下边距
        window_height = text_height + 30  # 上下各15像素边距
        
        # 限制最小和最大高度
        window_height = max(60, min(window_height, 300))
        
        # 设置窗口高度
        self.setFixedHeight(window_height)
        
        # 更新标签的几何位置
        self._label.setGeometry(15, 10, 290, window_height - 20)
        
    def clear(self):
        """清除内容"""
        self._text = ""
        self._is_final = False
        self._dot_count = 0
        self.stop_animation()
        self._label.setText("")
        # 重置窗口高度到默认值
        self.setFixedHeight(60)
        self._label.setGeometry(15, 10, 290, 40)
        
    def paintEvent(self, event):
        """绘制事件"""
        super().paintEvent(event)
        
        if self._is_final:
            return
            
        # 绘制"识别中"动画点
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制圆角矩形背景
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(30, 30, 30, 230)))
        painter.drawRoundedRect(self.rect(), 10, 10)
        
        # 如果没有文本，绘制动画点
        if not self._text:
            # 绘制三个动画点
            dot_size = 8
            spacing = 12
            start_x = (self.width() - (dot_size * 3 + spacing * 2)) // 2
            y = self.height() // 2
            
            for i in range(3):
                if i < self._dot_count:
                    painter.setBrush(QBrush(QColor(100, 200, 255)))
                else:
                    painter.setBrush(QBrush(QColor(100, 100, 100)))
                    
                x = start_x + i * (dot_size + spacing)
                painter.drawEllipse(x, y - dot_size // 2, dot_size, dot_size)
        
        painter.end()
        
    def show_near_ball(self, ball_geometry: 'QRect'):
        """在悬浮球附近显示
        
        Args:
            ball_geometry: 悬浮球的几何位置
        """
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        
        # 优先在右侧显示
        x = ball_geometry.right() + 10
        y = ball_geometry.top() - (self.height() - ball_geometry.height()) // 2
        
        # 检查是否超出屏幕右边界
        if x + self.width() > screen_geometry.right():
            x = ball_geometry.left() - self.width() - 10
            
        # 检查是否超出屏幕上下边界
        if y < screen_geometry.top():
            y = screen_geometry.top()
        if y + self.height() > screen_geometry.bottom():
            y = screen_geometry.bottom() - self.height()
            
        self.move(x, y)
        self.show()
        self.raise_()


class FloatingBall(QWidget):
    """悬浮球组件，支持拖动、右键菜单和展开会话窗口"""

    show_main_window = Signal()
    quit_application = Signal()
    send_message_requested = Signal(str)
    recording_started = Signal()
    recording_stopped = Signal(Path)
    create_recording_conversation = Signal(Path, str)
    show_model_not_loaded_warning = Signal()
    # 转录相关信号
    transcription_progress = Signal(str)  # 转录进度消息
    transcription_finished = Signal(Path, str)  # 转录完成 (audio_path, text)
    transcription_error = Signal(str)  # 转录错误消息
    # 实时识别信号（跨线程安全传递识别结果）
    realtime_result_signal = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = get_logger()
        self._is_dragging = False
        self._drag_position = QPoint()
        self._chat_window = None
        self._is_expanded = False
        self._animation = None
        # 转录相关属性
        self._current_audio_path: Optional[Path] = None
        
        # 实时识别相关属性
        self._realtime_popup: Optional[RealtimeRecognitionPopup] = None
        self._is_realtime_recording: bool = False
        
        # Live2D 相关
        self._mode = "live2d" if config.LIVE2D_ENABLED else "button"
        self._live2d_widget = None
        self._live2d_model_path: Optional[Path] = None
        
        self._logger.info("FloatingBall: 开始初始化")
        self._init_ui()
        self._init_style()
        self._init_position()
        self._init_chat_window()
        self._init_realtime_popup()
        self._init_live2d()
        self._connect_recorder_signals()
        # 连接实时识别信号到 UI 更新（跨线程安全）
        self.realtime_result_signal.connect(self._update_realtime_popup)
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
        
        # 根据模式设置尺寸
        if self._mode == "live2d":
            self.setFixedSize(config.LIVE2D_BALL_WIDTH, config.LIVE2D_BALL_HEIGHT)
        else:
            self.setFixedSize(30, 30)

        # 创建按钮（仅在 button 模式下显示）
        self.button = FloatingBallButton(self)
        self.button.setFixedSize(30, 30)
        self.button.setObjectName("floatingBallButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setVisible(self._mode == "button")

        # 不设置任何文本或图标，保持纯色

        # 创建右键菜单
        self._init_context_menu()

        # 连接信号（仅 button 模式）
        if self._mode == "button":
            self.button.clicked.connect(self._on_button_clicked)

    def _init_style(self):
        """初始化样式"""
        style = StyleManager.get_style("floating_ball_stylesheet")
        if style and self._mode == "button":
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

    def _init_realtime_popup(self):
        """初始化实时识别弹出窗口"""
        self._realtime_popup = RealtimeRecognitionPopup()
        self._realtime_popup.hide()
        
    def _connect_recorder_signals(self):
        """连接 AudioRecorder 的信号"""
        # 实时识别结果通过 start_recording 的回调传递，无需额外信号连接
        self._logger.info("实时识别将通过回调机制工作")

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

    def _init_live2d(self):
        """初始化 Live2D 相关（启用时自动加载模型）"""
        if self._mode != "live2d":
            return
        
        # 确定模型路径
        self._live2d_model_path = self._resolve_live2d_model_path()
        
        if self._live2d_model_path is None:
            self._logger.warning("未找到可用的 Live2D 模型，回退到按钮模式")
            self._fallback_to_button_mode()
            return
        
        # 创建 Live2D 控件
        try:
            from ui.live2d_widget import Live2DWidget
            self._live2d_widget = Live2DWidget(self)
            self._live2d_widget.setGeometry(0, 0, self.width(), self.height())
            self._live2d_widget.clicked.connect(self._on_live2d_clicked)
            
            # 自动加载模型
            self._live2d_widget.load_model(self._live2d_model_path)
            self._logger.info(f"Live2D 控件已创建，自动加载模型: {self._live2d_model_path}")
        except Exception as e:
            self._logger.error(f"创建 Live2D 控件失败: {e}")
            self._fallback_to_button_mode()

    def _resolve_live2d_model_path(self) -> Optional[Path]:
        """解析 Live2D 模型路径"""
        from ui.live2d_model_manager import scan_models, get_default_model_dir
        
        # 如果配置了具体模型名称，查找对应模型
        if config.LIVE2D_MODEL_NAME:
            models = scan_models()
            for model_info in models:
                if model_info.name == config.LIVE2D_MODEL_NAME or model_info.model_dir.name == config.LIVE2D_MODEL_NAME:
                    self._logger.info(f"找到配置的 Live2D 模型: {model_info.name}")
                    return model_info.model_json
            
            self._logger.warning(f"未找到指定的 Live2D 模型: {config.LIVE2D_MODEL_NAME}")
        
        # 使用默认模型
        default_dir = get_default_model_dir()
        if default_dir:
            from ui.live2d_model_manager import get_model_info
            info = get_model_info(default_dir)
            if info:
                self._logger.info(f"使用默认 Live2D 模型: {info.name}")
                return info.model_json
        
        return None

    def load_live2d_model(self) -> bool:
        """手动加载 Live2D 模型
        
        Returns:
            bool: 加载成功返回 True，失败返回 False
        """
        if self._live2d_widget is None or self._live2d_model_path is None:
            return False
        
        try:
            self._live2d_widget.load_model(self._live2d_model_path)
            return True
        except Exception as e:
            self._logger.error(f"手动加载 Live2D 模型失败: {e}")
            return False

    def switch_to_live2d_mode(self) -> bool:
        """运行时切换到 Live2D 模式
        
        Returns:
            bool: 切换成功返回 True，失败返回 False
        """
        if self._mode == "live2d":
            return True
        
        # 先重新解析配置
        import importlib
        importlib.reload(config)
        
        if not config.LIVE2D_ENABLED:
            self._logger.warning("Live2D 未启用")
            return False
        
        self._mode = "live2d"
        self._live2d_model_path = self._resolve_live2d_model_path()
        
        if self._live2d_model_path is None:
            self._logger.warning("未找到可用的 Live2D 模型，无法切换")
            return False
        
        # 隐藏按钮
        self.button.setVisible(False)
        
        # 设置新尺寸
        self.setFixedSize(config.LIVE2D_BALL_WIDTH, config.LIVE2D_BALL_HEIGHT)
        
        # 创建 Live2D 控件
        try:
            from ui.live2d_widget import Live2DWidget
            self._live2d_widget = Live2DWidget(self)
            self._live2d_widget.setGeometry(0, 0, self.width(), self.height())
            self._live2d_widget.clicked.connect(self._on_live2d_clicked)
            
            # 加载模型
            self._live2d_widget.load_model(self._live2d_model_path)
            
            self._logger.info("成功切换到 Live2D 模式")
            return True
        except Exception as e:
            self._logger.error(f"切换到 Live2D 模式失败: {e}")
            self._fallback_to_button_mode()
            return False

    def switch_to_button_mode(self) -> None:
        """运行时切换到按钮模式"""
        if self._mode == "button":
            return
        
        self._fallback_to_button_mode()
        self._logger.info("成功切换到按钮模式")

    def _fallback_to_button_mode(self):
        """回退到按钮模式"""
        self._mode = "button"
        self.button.setVisible(True)
        self.setFixedSize(30, 30)
        self.button.clicked.connect(self._on_button_clicked)
        
        # 重新定位
        self._init_position()
        
        # 应用样式
        style = StyleManager.get_style("floating_ball_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _on_button_clicked(self):
        """按钮点击事件 - 切换聊天窗口展开/收起"""
        self._toggle_chat_window()
    
    def _on_live2d_clicked(self):
        """Live2D 控件点击事件 - 切换聊天窗口展开/收起"""
        self._toggle_chat_window()
    
    def _toggle_recording(self):
        """切换录音状态"""
        from recorder import is_online_model_loaded
        import config
        recorder = get_recorder()
        
        if recorder.is_recording:
            self._logger.info("停止录音...")
            audio_path = recorder.stop_recording()
            self._recording_action.setText("录音模式")
            self._logger.info(f"录音已停止，audio_path={audio_path}")
            
            # 停止录音后，立即隐藏实时识别窗口
            self._hide_realtime_popup()
            
            # audio_path 为 None 表示实时识别成功，结果已通过回调传递
            # audio_path 不为 None 表示实时识别失败，需要离线转录
            if audio_path:
                self._logger.warning(f"实时识别失败，保存了音频文件: {audio_path}")
                # 离线转录作为降级方案
                self._transcribe_offline(audio_path)
        else:
            # 在开始录音前检查流式模型是否已加载
            if not is_online_model_loaded():
                # 没有流式模型，显示警告
                self.show_model_not_loaded_warning.emit()
                return
            
            success = recorder.start_recording(realtime_callback=self._on_realtime_result)
            if success:
                self._recording_action.setText("停止录音")
                self.recording_started.emit()
                self._show_realtime_popup()
                    
    def _show_realtime_popup(self):
        """显示实时识别弹出窗口"""
        if self._realtime_popup is None:
            self._logger.warning("无法显示实时识别弹出窗口：_realtime_popup 为 None")
            return
            
        self._logger.info("准备显示实时识别弹出窗口")
        self._is_realtime_recording = True
        self._realtime_popup.clear()
        self._realtime_popup.start_animation()
        self._realtime_popup.show_near_ball(self.geometry())
        self._logger.info(f"实时识别弹出窗口已显示，_is_realtime_recording={self._is_realtime_recording}")
        
    def _hide_realtime_popup(self):
        """隐藏实时识别弹出窗口"""
        self._logger.info(f"准备隐藏实时识别弹出窗口，_realtime_popup={self._realtime_popup is not None}, _is_realtime_recording={self._is_realtime_recording}")
        
        if self._realtime_popup is None:
            self._logger.warning("无法隐藏实时识别弹出窗口：_realtime_popup 为 None")
            return
            
        self._is_realtime_recording = False
        self._realtime_popup.stop_animation()
        self._realtime_popup.hide()
        self._logger.info("实时识别弹出窗口已隐藏")
        
    def _on_realtime_result(self, text: str, is_final: bool):
        """处理实时识别结果（从录音回调线程调用）
        
        Args:
            text: 识别文本
            is_final: 是否为最终结果
        """
        # 使用 Qt Signal 跨线程安全传递结果到主线程
        self.realtime_result_signal.emit(text, is_final)
        
    def _update_realtime_popup(self, text: str, is_final: bool):
        """更新实时识别弹出窗口
        
        Args:
            text: 识别文本
            is_final: 是否为最终结果
        """
        self._logger.info(f"_update_realtime_popup 被调用: text='{text}', is_final={is_final}, _realtime_popup={self._realtime_popup is not None}, _is_realtime_recording={self._is_realtime_recording}")
        
        if self._realtime_popup is None or not self._is_realtime_recording:
            self._logger.warning(f"无法更新实时识别弹出窗口: _realtime_popup={self._realtime_popup is not None}, _is_realtime_recording={self._is_realtime_recording}")
            return
            
        self._logger.debug(f"实时识别结果更新: text='{text}', is_final={is_final}")
        
        # 更新弹出窗口内容
        self._realtime_popup.set_text(text, is_final)
        
        # 如果是最终结果，发送转录完成信号并延迟隐藏弹出窗口
        if is_final:
            self._logger.info("最终结果已显示，发送转录完成信号")
            # 发送转录完成信号
            self.transcription_finished.emit(None, text)
            # 发送创建录音会话信号给主窗口
            self.create_recording_conversation.emit(None, text)
            self._logger.info("将在 2 秒后隐藏弹出窗口")
            QTimer.singleShot(2000, self._hide_realtime_popup)
    
    def _on_transcribe_error(self, audio_path: str, error: str):
        """转录错误处理"""
        self._logger.error(f"转录失败: {audio_path}, 错误: {error}")
        
        # 发送转录错误信号
        self.transcription_error.emit(error)
    
    def _transcribe_offline(self, audio_path: Path):
        """使用离线模型转录音频文件作为降级方案"""
        self._logger.info(f"尝试离线转录: {audio_path}")
        from recorder import is_onnx_model_loaded, transcribe_audio_with_onnx
        
        if not is_onnx_model_loaded():
            self._logger.warning("离线模型也未加载，无法转录")
            self._on_transcribe_error(str(audio_path), "离线模型未加载，无法转录音频")
            return
        
        result = transcribe_audio_with_onnx(audio_path)
        if result:
            self._logger.info(f"离线转录成功: {result}")
            self.create_recording_conversation.emit(audio_path, result)
        else:
            self._on_transcribe_error(str(audio_path), "离线转录失败")
        
        # 在聊天窗口显示错误消息
        if self._chat_window:
            self._chat_window.add_message("assistant", f"❌ 转录失败: {error}")

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
            # 如果实时识别弹出窗口已显示，同步移动
            if self._is_realtime_recording and self._realtime_popup:
                self._realtime_popup.show_near_ball(self.geometry())
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
