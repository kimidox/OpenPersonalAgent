"""
桌面悬浮球子进程

在独立进程中运行一个 PySide6 无边框置顶窗口，可在全桌面范围内拖拽。
通过 multiprocessing.Queue 与主 Flet 进程通信。
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


class FloatingBallWindow(QWidget):
    """桌面悬浮球窗口"""

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

        self._is_dragging = False
        self._drag_start_global = QPoint()
        self._drag_start_pos = QPoint()
        self._is_recording = False

        self._primary_color = DEFAULT_PRIMARY_COLOR
        self._hover_color = DEFAULT_HOVER_COLOR
        self._is_hovered = False

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
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._is_dragging:
                self._on_toggle_chat()
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
        self._send(MessageType.TOGGLE_CHAT)

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
        self._send(MessageType.QUIT_APPLICATION)

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
            self.close()
            QApplication.quit()
        elif msg_type == MessageType.SET_THEME:
            color = msg.get("color", "#3B82F6")
            self._primary_color = QColor(color)
            self._hover_color = QColor(color).darker(115)
            self.update()


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

    ball = FloatingBallWindow(to_main_queue, from_main_queue)
    ball.show()

    # 保持 QApplication 事件循环运行
    sys.exit(app.exec())


def main() -> None:
    """命令行独立调试用入口"""
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

    run_floating_ball_process(q1, q2)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
