"""
桌面悬浮球子进程

在独立进程中运行一个 PySide6 无边框置顶窗口，可在全桌面范围内拖拽。
通过 multiprocessing.Queue 与主 Flet 进程通信。
聊天窗口与悬浮球共享同一进程，点击悬浮球立即显示聊天窗口。
"""
from __future__ import annotations

import sys
import threading
from multiprocessing import Queue
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QIcon,
    QAction,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMenu,
    QStyleFactory,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QFrame,
)

# 兼容开发环境和 PyInstaller 打包环境
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from logger import get_logger
from resource_path import paths
from ui_flet.floating_ball_ipc import MessageType, make_message


BALL_SIZE = 50
BALL_MARGIN = 20
DEFAULT_PRIMARY_COLOR = QColor("#3B82F6")
DEFAULT_HOVER_COLOR = QColor("#2563EB")

# 聊天窗口配置
CHAT_WIDTH = 400
CHAT_HEIGHT = 500
CHAT_MIN_WIDTH = 300
CHAT_MIN_HEIGHT = 400

# 颜色配置
DEFAULT_BG_COLOR = "#ffffff"
DEFAULT_TEXT_COLOR = "#1f2937"
DEFAULT_BORDER_COLOR = "#e5e7eb"


class MessageBubble(QFrame):
    """消息气泡组件"""

    def __init__(self, text: str, is_user: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._text = text
        self._is_user = is_user
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        # 角色标签
        role_label = QLabel("用户" if self._is_user else "助手")
        role_label.setStyleSheet(f"color: {DEFAULT_TEXT_COLOR}; font-size: 12px; font-weight: bold;")
        layout.addWidget(role_label)

        # 消息文本
        text_label = QLabel(self._text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(f"color: {DEFAULT_TEXT_COLOR}; font-size: 14px;")
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(text_label)

        # 设置背景色
        if self._is_user:
            self.setStyleSheet(f"""
                MessageBubble {{
                    background-color: #eff6ff;
                    border-radius: 8px;
                    border: 1px solid {DEFAULT_BORDER_COLOR};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                MessageBubble {{
                    background-color: {DEFAULT_BG_COLOR};
                    border-radius: 8px;
                    border: 1px solid {DEFAULT_BORDER_COLOR};
                }}
            """)


class FloatingChatWindow(QWidget):
    """悬浮聊天窗口 - 贴着悬浮球显示"""

    def __init__(
        self,
        to_main_queue: Queue,
        from_main_queue: Queue,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._logger = get_logger()
        self._to_main = to_main_queue
        self._from_main = from_main_queue

        # 消息列表
        self._messages: list[tuple[bool, str]] = []  # (is_user, text)

        # 悬浮球位置（用于定位聊天窗口）
        self._ball_pos: QPoint | None = None

        self._init_window()
        self._init_ui()
        self._init_ipc_poll()

    # ----------------- UI 初始化 -----------------

    def _init_window(self) -> None:
        """初始化窗口"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(CHAT_MIN_WIDTH, CHAT_MIN_HEIGHT)
        self.resize(CHAT_WIDTH, CHAT_HEIGHT)

        # 设置窗口样式
        self.setStyleSheet(f"""
            FloatingChatWindow {{
                background-color: {DEFAULT_BG_COLOR};
                border: 1px solid {DEFAULT_BORDER_COLOR};
                border-radius: 10px;
            }}
        """)

    def _init_ui(self) -> None:
        """初始化 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题栏
        title_bar = self._create_title_bar()
        main_layout.addWidget(title_bar)

        # 消息区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DEFAULT_BG_COLOR};
            }}
            QScrollBar:vertical {{
                width: 8px;
                background-color: {DEFAULT_BG_COLOR};
            }}
            QScrollBar::handle:vertical {{
                background-color: {DEFAULT_BORDER_COLOR};
                border-radius: 4px;
            }}
        """)

        self._message_container = QWidget()
        self._message_layout = QVBoxLayout(self._message_container)
        self._message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._message_layout.setSpacing(10)
        self._message_layout.setContentsMargins(10, 10, 10, 10)

        self._scroll_area.setWidget(self._message_container)
        main_layout.addWidget(self._scroll_area, stretch=1)

        # 输入区域
        input_area = self._create_input_area()
        main_layout.addWidget(input_area)

    def _create_title_bar(self) -> QWidget:
        """创建标题栏"""
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {DEFAULT_BG_COLOR};
                border-bottom: 1px solid {DEFAULT_BORDER_COLOR};
            }}
        """)

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(10, 0, 10, 0)

        # 标题
        title_label = QLabel("快速对话")
        title_label.setStyleSheet(f"color: {DEFAULT_TEXT_COLOR}; font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)

        layout.addStretch()

        # 隐藏按钮
        hide_btn = QPushButton("−")
        hide_btn.setFixedSize(30, 30)
        hide_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {DEFAULT_TEXT_COLOR};
                border: none;
                font-size: 18px;
                border-radius: 15px;
            }}
            QPushButton:hover {{
                background-color: {DEFAULT_BORDER_COLOR};
            }}
        """)
        hide_btn.clicked.connect(self.hide)
        layout.addWidget(hide_btn)

        # 支持拖拽
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release

        self._dragging = False
        self._drag_start_pos = None
        self._drag_start_global = None

        return title_bar

    def _create_input_area(self) -> QWidget:
        """创建输入区域"""
        input_area = QWidget()
        input_area.setFixedHeight(60)
        input_area.setStyleSheet(f"""
            QWidget {{
                background-color: {DEFAULT_BG_COLOR};
                border-top: 1px solid {DEFAULT_BORDER_COLOR};
            }}
        """)

        layout = QHBoxLayout(input_area)
        layout.setContentsMargins(10, 10, 10, 10)

        # 输入框
        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("输入消息... (Enter 发送)")
        self._input_field.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DEFAULT_BG_COLOR};
                color: {DEFAULT_TEXT_COLOR};
                border: 1px solid {DEFAULT_BORDER_COLOR};
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: #3B82F6;
            }}
        """)
        self._input_field.returnPressed.connect(self._send_message)
        layout.addWidget(self._input_field, stretch=1)

        # 发送按钮
        send_btn = QPushButton("发送")
        send_btn.setFixedSize(60, 35)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: #2563EB;
            }}
            QPushButton:pressed {{
                background-color: #1d4ed8;
            }}
        """)
        send_btn.clicked.connect(self._send_message)
        layout.addWidget(send_btn)

        return input_area

    def _init_ipc_poll(self) -> None:
        """启动定时器，轮询主进程发来的消息"""
        self._ipc_timer = QTimer(self)
        self._ipc_timer.timeout.connect(self._poll_ipc)
        self._ipc_timer.start(100)  # 100ms 轮询一次

    # ----------------- 拖拽事件 -----------------

    def _title_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_global = event.globalPosition().toPoint()
            self._drag_start_pos = self.pos()

    def _title_mouse_move(self, event):
        if self._dragging and self._drag_start_global:
            current = event.globalPosition().toPoint()
            delta = current - self._drag_start_global
            self.move(self._drag_start_pos + delta)

    def _title_mouse_release(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    # ----------------- 位置计算 -----------------

    def update_position(self, ball_pos: QPoint) -> None:
        """根据悬浮球位置更新聊天窗口位置（贴着悬浮球左上角）"""
        self._ball_pos = ball_pos

        # 计算聊天窗口位置：悬浮球左上角
        # ball_pos 是悬浮球左上角的位置
        chat_x = ball_pos.x() - CHAT_WIDTH
        chat_y = ball_pos.y() - CHAT_HEIGHT

        # 确保不超出屏幕
        screen = QApplication.primaryScreen()
        if screen:
            geometry = screen.availableGeometry()
            chat_x = max(0, min(chat_x, geometry.width() - CHAT_WIDTH))
            chat_y = max(0, min(chat_y, geometry.height() - CHAT_HEIGHT))

        self.move(chat_x, chat_y)
        self._logger.info(f"聊天窗口位置更新: ({chat_x}, {chat_y})")

    # ----------------- 消息处理 -----------------

    def _send_message(self) -> None:
        """发送消息"""
        text = self._input_field.text().strip()
        if not text:
            return

        self._logger.info(f"悬浮聊天窗口发送消息: {text[:50]}...")

        # 添加用户消息到界面
        self._add_message(True, text)

        # 清空输入框
        self._input_field.clear()

        # 发送到主进程
        self._send(MessageType.CHAT_SEND_MESSAGE, content=text)

    def _add_message(self, is_user: bool, text: str) -> None:
        """添加消息到界面"""
        bubble = MessageBubble(text, is_user)
        self._message_layout.addWidget(bubble)
        self._messages.append((is_user, text))

        # 滚动到底部
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        """滚动到底部"""
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ----------------- IPC 通信 -----------------

    def _send(self, msg_type: MessageType, **payload) -> None:
        try:
            self._to_main.put(make_message(msg_type, **payload))
        except Exception as e:
            self._logger.error(f"悬浮聊天窗口 IPC 发送失败: {e}")

    def _poll_ipc(self) -> None:
        """非阻塞地读取主进程消息"""
        try:
            while not self._from_main.empty():
                msg = self._from_main.get_nowait()
                self._handle_ipc_message(msg)
        except Exception as e:
            self._logger.error(f"悬浮聊天窗口 IPC 轮询异常: {e}")

    def _handle_ipc_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == MessageType.EXIT:
            self._logger.info("悬浮聊天窗口收到退出消息，关闭窗口")
            self.close()
        elif msg_type == MessageType.CHAT_RECEIVE_MESSAGE:
            # 接收到助手回复
            content = msg.get("content", "")
            self._add_message(False, content)
            self._logger.info(f"悬浮聊天窗口收到助手回复: {content[:50]}...")
        elif msg_type == MessageType.SET_THEME:
            # 更新主题（暂不实现）
            pass


class FloatingBallWindow(QWidget):
    """桌面悬浮球窗口"""

    def __init__(
        self,
        to_main_queue: Queue,
        from_main_queue: Queue,
        main_pid: int,
        flet_pid: int | None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._logger = get_logger()
        self._to_main = to_main_queue
        self._from_main = from_main_queue
        self._main_pid = main_pid  # 主进程 PID，用于退出时终止主进程
        self._flet_pid = flet_pid  # Flet 原生进程 PID

        self._is_dragging = False
        self._drag_start_global = QPoint()
        self._drag_start_pos = QPoint()
        self._is_recording = False

        self._primary_color = DEFAULT_PRIMARY_COLOR
        self._hover_color = DEFAULT_HOVER_COLOR
        self._is_hovered = False

        # 聊天窗口（共享同一进程）
        self._chat_window: FloatingChatWindow | None = None

        self._init_window()
        self._init_menu()
        self._init_position()
        self._init_ipc_poll()

    # ----------------- UI 初始化 -----------------

    def _init_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(BALL_SIZE, BALL_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _init_menu(self) -> None:
        self._menu = QMenu(self)
        self._menu.setStyleSheet(
            "QMenu { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px; }"
            "QMenu::item { padding: 6px 24px; border-radius: 4px; }"
            "QMenu::item:selected { background-color: #eff6ff; color: #1d4ed8; }"
            "QMenu::separator { height: 1px; background-color: #e5e7eb; margin: 4px 0px; }"
        )

        self._toggle_chat_action = QAction("展开聊天窗口", self)
        self._toggle_chat_action.triggered.connect(self._on_toggle_chat)
        self._menu.addAction(self._toggle_chat_action)

        self._show_main_action = QAction("显示主窗口", self)
        self._show_main_action.triggered.connect(self._on_show_main_window)
        self._menu.addAction(self._show_main_action)

        self._menu.addSeparator()

        self._recording_action = QAction("开始录音", self)
        self._recording_action.triggered.connect(self._on_toggle_recording)
        self._menu.addAction(self._recording_action)

        self._menu.addSeparator()

        self._quit_action = QAction("退出应用", self)
        self._quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self._quit_action)

    def _init_position(self) -> None:
        """默认放到屏幕右下角"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.width() - BALL_SIZE - BALL_MARGIN
        y = geometry.height() - BALL_SIZE - BALL_MARGIN
        self.move(x, y)

    def _init_ipc_poll(self) -> None:
        """启动定时器，轮询主进程发来的消息"""
        self._ipc_timer = QTimer(self)
        self._ipc_timer.timeout.connect(self._poll_ipc)
        self._ipc_timer.start(100)  # 100ms 轮询一次

    # ----------------- 聊天窗口管理 -----------------

    def _create_chat_window(self) -> None:
        """创建聊天窗口（只创建一次）"""
        if self._chat_window is not None:
            return

        self._chat_window = FloatingChatWindow(
            self._to_main,
            self._from_main,
        )
        self._logger.info("聊天窗口已创建")

    def _toggle_chat_window(self) -> None:
        """切换聊天窗口显示/隐藏"""
        if self._chat_window is None:
            self._create_chat_window()

        if self._chat_window is None:
            return

        if self._chat_window.isVisible():
            self._chat_window.hide()
            self._toggle_chat_action.setText("展开聊天窗口")
            self._logger.info("聊天窗口已隐藏")
        else:
            # 更新聊天窗口位置（贴着悬浮球左上角）
            self._chat_window.update_position(self.pos())
            self._chat_window.show()
            self._toggle_chat_action.setText("收起聊天窗口")
            self._logger.info(f"聊天窗口已显示，悬浮球位置: {self.pos()}")

    # ----------------- 绘制 -----------------

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景圆
        color = self._hover_color if self._is_hovered else self._primary_color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(0, 0, BALL_SIZE, BALL_SIZE)

        # 绘制聊天泡泡图标（避免依赖字体图标）
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(Qt.PenStyle.NoPen)

        # 气泡主体
        bubble_rect = self.rect().adjusted(14, 13, -14, -17)
        painter.drawRoundedRect(bubble_rect, 8, 8)

        # 气泡尖角
        tail_points = [
            QPoint(28, 33),
            QPoint(34, 39),
            QPoint(34, 33),
        ]
        painter.drawPolygon(tail_points)

        painter.end()

    # ----------------- 鼠标事件 -----------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_global = event.globalPosition().toPoint()
            self._drag_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            delta = current - self._drag_start_global
            if not self._is_dragging and delta.manhattanLength() > 5:
                self._is_dragging = True
            if self._is_dragging:
                self.move(self._drag_start_pos + delta)
                # 同时更新聊天窗口位置
                if self._chat_window and self._chat_window.isVisible():
                    self._chat_window.update_position(self.pos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._is_dragging:
                self._toggle_chat_window()
            self._is_dragging = False
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: ARG002
        self._is_hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ARG002
        self._is_hovered = False
        self.update()

    def contextMenuEvent(self, event) -> None:
        self._menu.exec(event.globalPos())

    # ----------------- 菜单/交互回调 -----------------

    def _on_toggle_chat(self) -> None:
        self._toggle_chat_window()

    def _on_show_main_window(self) -> None:
        self._send(MessageType.SHOW_MAIN_WINDOW)

    def _on_toggle_recording(self) -> None:
        if self._is_recording:
            self._is_recording = False
            self._recording_action.setText("开始录音")
            self._send(MessageType.STOP_RECORDING)
        else:
            self._is_recording = True
            self._recording_action.setText("停止录音")
            self._send(MessageType.START_RECORDING)

    def _on_quit(self) -> None:
        """退出应用：终止所有相关进程"""
        import os
        import subprocess

        self._logger.info("悬浮球请求退出应用...")
        self._logger.info(f"主进程 PID: {self._main_pid}, Flet 进程 PID: {self._flet_pid}")

        # 先关闭聊天窗口和悬浮球窗口
        if self._chat_window:
            self._chat_window.close()
        self.close()

        # 先终止 Flet 原生进程（精确使用 PID）
        if self._flet_pid:
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/PID", str(self._flet_pid)],
                    check=False,
                    capture_output=True,
                    text=True
                )
                self._logger.info(f"终止 Flet 进程 {self._flet_pid}: {result.stdout} {result.stderr}")
            except Exception as e:
                self._logger.error(f"终止 Flet 进程失败: {e}")

        # 再终止主进程及其子进程（使用 /T 终止进程树）
        try:
            if self._main_pid and self._main_pid != os.getpid():
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._main_pid)],
                    check=False,
                    capture_output=True,
                    text=True
                )
                self._logger.info(f"终止主进程树 {self._main_pid}: {result.stdout} {result.stderr}")
        except Exception as e:
            self._logger.error(f"终止主进程失败: {e}")

        # 悬浮球进程退出
        self._logger.info("悬浮球进程退出")
        QApplication.quit()

    def _send(self, msg_type: MessageType, **payload) -> None:
        try:
            self._to_main.put(make_message(msg_type, **payload))
        except Exception as e:
            self._logger.error(f"悬浮球 IPC 发送失败: {e}")

    # ----------------- IPC 接收 -----------------

    def _poll_ipc(self) -> None:
        """非阻塞地读取主进程消息"""
        try:
            while not self._from_main.empty():
                msg = self._from_main.get_nowait()
                self._handle_ipc_message(msg)
        except Exception as e:
            self._logger.error(f"悬浮球 IPC 轮询异常: {e}")

    def _handle_ipc_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == MessageType.EXIT:
            self._logger.info("悬浮球收到退出消息，关闭窗口")
            if self._chat_window:
                self._chat_window.close()
            self.close()
            QApplication.quit()
        elif msg_type == MessageType.SET_THEME:
            color = msg.get("color", "#3B82F6")
            self._primary_color = QColor(color)
            self._hover_color = QColor(color).darker(115)
            self.update()
        elif msg_type == MessageType.CHAT_RECEIVE_MESSAGE:
            # 转发给聊天窗口
            if self._chat_window:
                self._chat_window._handle_ipc_message(msg)


def _set_dpi_awareness() -> None:
    """Windows 高 DPI 感知"""
    try:
        from ctypes import windll

        windll.user32.SetProcessDpiAwarenessContext(2)
    except Exception:
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run_floating_ball_process(
    to_main_queue: Queue,
    from_main_queue: Queue,
    main_pid: int,
    flet_pid: int | None,
) -> None:
    """悬浮球子进程入口"""
    _set_dpi_awareness()

    app = QApplication(sys.argv)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)

    icon_path = paths.get_bundled_resource("application.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    ball = FloatingBallWindow(to_main_queue, from_main_queue, main_pid, flet_pid)
    ball.show()

    # 保持 QApplication 事件循环运行
    sys.exit(app.exec())


def main() -> None:
    """命令行独立调试用入口"""
    import os

    # 创建一对本地队列即可独立运行，事件会打印到日志
    q1: Queue = Queue()
    q2: Queue = Queue()

    def printer():
        while True:
            try:
                print("IPC:", q1.get(timeout=0.5))
            except Exception:
                continue

    t = threading.Thread(target=printer, daemon=True)
    t.start()

    # 独立运行时，main_pid 为当前进程 PID，flet_pid 为 None
    run_floating_ball_process(q1, q2, os.getpid(), None)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()