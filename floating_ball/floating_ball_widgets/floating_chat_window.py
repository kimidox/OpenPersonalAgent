"""
悬浮聊天窗口 - 贴着悬浮球显示

从 floating_ball_process.py 内部类提取，逻辑完全等价。

Business purpose:
    在悬浮球旁边显示聊天窗口，支持消息收发和IPC通信。

Modification notes:
    2026-07-29: 从 run_floating_ball_process 内部类提取为独立模块

Related tests:
    tests/test_floating_ball_widgets.py (待补充)
"""
from __future__ import annotations

import time
from multiprocessing import Queue
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QFrame,
)
from floating_ball.floating_ball_ipc import MessageType, make_message
from logger import get_logger

from floating_ball.floating_ball_widgets._constants import (
    CHAT_WIDTH,
    CHAT_HEIGHT,
    CHAT_MIN_WIDTH,
    CHAT_MIN_HEIGHT,
    DEFAULT_BG_COLOR,
    DEFAULT_BORDER_COLOR,
    DEFAULT_TEXT_COLOR,
)
from floating_ball.floating_ball_widgets.message_bubble import MessageBubble


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
        hide_btn = QPushButton("\u2212")
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
        """非阻塞地读取主进程消息（支持批量消息解包）"""
        try:
            while not self._from_main.empty():
                msg = self._from_main.get_nowait()
                # 解包批量消息
                messages = self._unwrap_batch_message(msg)
                for message in messages:
                    self._handle_ipc_message(message)
        except Exception as e:
            self._logger.error(f"悬浮聊天窗口 IPC 轮询异常: {e}")

    def _unwrap_batch_message(self, msg: dict | bytes) -> list[dict]:
        """解包批量消息（兼容新旧格式）"""
        # 处理 bytes 类型（msgpack 序列化）
        if isinstance(msg, bytes):
            try:
                import msgpack
                msg = msgpack.unpackb(msg, raw=False)
            except ImportError:
                # msgpack 未安装，尝试 pickle
                import pickle
                msg = pickle.loads(msg)
            except Exception as e:
                self._logger.error(f"消息反序列化失败: {e}")
                return []

        # 检查是否是批量消息
        if isinstance(msg, dict) and msg.get("type") == "__batch__":
            return msg.get("messages", [])
        else:
            return [msg] if isinstance(msg, dict) else []

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
