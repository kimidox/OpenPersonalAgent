"""
桌面悬浮球窗口

从 floating_ball_process.py 内部类提取，逻辑完全等价。

Business purpose:
    在桌面显示可拖拽的悬浮球，支持右键菜单、Live2D渲染、聊天窗口切换和IPC通信。

Modification notes:
    2026-07-29: 从 run_floating_ball_process 内部类提取为独立模块

Related tests:
    tests/test_floating_ball_widgets.py (待补充)
"""
from __future__ import annotations

import os
import subprocess
import time
import traceback
from multiprocessing import Queue
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QPainter, QColor, QBrush, QIcon, QAction
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QStyleFactory
from floating_ball.floating_ball_ipc import MessageType, make_message
from logger import get_logger
from resource_path import paths

from floating_ball.floating_ball_widgets import _constants as _const
from floating_ball.floating_ball_widgets.live2d_widget import Live2DWidget
from floating_ball.floating_ball_widgets.floating_chat_window import FloatingChatWindow

# 数值常量可直接使用（不依赖延迟初始化）
BALL_SIZE = _const.BALL_SIZE
BALL_MARGIN = _const.BALL_MARGIN


class FloatingBallWindow(QWidget):
    """桌面悬浮球窗口"""

    def __init__(
        self,
        to_main_queue: Queue,
        from_main_queue: Queue,
        main_pid: int,
        live2d_enabled: bool = False,
        live2d_model_path: str | None = None,
        live2d_width: int = 200,
        live2d_height: int = 200,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._logger = get_logger()
        self._to_main = to_main_queue
        self._from_main = from_main_queue
        self._main_pid = main_pid  # 主进程 PID，用于退出时终止主进程

        # Live2D 配置
        self._live2d_enabled = live2d_enabled
        self._live2d_model_path = live2d_model_path
        self._live2d_width = live2d_width
        self._live2d_height = live2d_height

        self._is_dragging = False
        self._drag_start_global = QPoint()
        self._drag_start_pos = QPoint()
        self._is_recording = False

        self._primary_color = _const.DEFAULT_PRIMARY_COLOR
        self._hover_color = _const.DEFAULT_HOVER_COLOR
        self._is_hovered = False

        # 聊天窗口（共享同一进程）
        self._chat_window: FloatingChatWindow | None = None

        # Live2D 组件（如果启用）
        self._live2d_widget: Live2DWidget | None = None

        self._init_window()
        self._init_menu()
        self._init_position()

        # 如果启用 Live2D，初始化 Live2D 组件
        if live2d_enabled and live2d_model_path:
            self._init_live2d()

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
        self.setStyleSheet("background:transparent")

        # 根据是否启用 Live2D 调整窗口大小
        if self._live2d_enabled and self._live2d_model_path:
            window_width = self._live2d_width
            window_height = self._live2d_height
            self._logger.info(f"Live2D 悬浮球窗口大小: {window_width}x{window_height}")
        else:
            window_width = BALL_SIZE
            window_height = BALL_SIZE

        self.setFixedSize(window_width, window_height)
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

        # 根据窗口大小计算位置
        window_width = self.width()
        window_height = self.height()
        x = geometry.width() - window_width - BALL_MARGIN
        y = geometry.height() - window_height - BALL_MARGIN
        self.move(x, y)

    def _init_live2d(self) -> None:
        """初始化 Live2D 组件"""
        try:
            # 检查模型路径是否有效
            if not self._live2d_model_path:
                self._logger.warning("Live2D 模型路径为空，使用默认悬浮球")
                self._live2d_widget = None
                return

            model_path_obj = Path(self._live2d_model_path)
            if not model_path_obj.exists():
                self._logger.warning(
                    f"Live2D 模型文件不存在: {self._live2d_model_path}, 使用默认悬浮球"
                )
                self._live2d_widget = None
                return

            self._logger.info(f"正在初始化 Live2D 组件: {self._live2d_model_path}")

            # 创建 Live2D 组件实例
            self._live2d_widget = Live2DWidget(
                model_path=self._live2d_model_path,
                parent=self
            )

            # 设置组件大小和位置（填充整个窗口）
            self._live2d_widget.setGeometry(0, 0, self._live2d_width, self._live2d_height)
            self._live2d_widget.show()

            self._logger.info(
                f"Live2D 组件已初始化: {self._live2d_model_path}, "
                f"大小: {self._live2d_width}x{self._live2d_height}, "
                f"可见性: {self._live2d_widget.isVisible()}, "
                f"几何: {self._live2d_widget.geometry()}"
            )
            # 强制重绘以触发 initializeGL/paintGL
            self._live2d_widget.update()

        except Exception as e:
            self._logger.error(
                f"初始化 Live2D 组件失败: {e}, 使用默认悬浮球",
                exc_info=True
            )
            # 确保失败时清理组件引用
            if self._live2d_widget:
                try:
                    self._live2d_widget.close()
                except Exception:
                    pass
            self._live2d_widget = None

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
        # 如果 Live2D 组件存在，不绘制默认圆形
        if self._live2d_widget is not None:
            # Live2D 组件会自己渲染，这里不绘制背景
            return

        # 绘制默认圆形悬浮球
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
                # 如果有 Live2D 组件，进行碰撞检测并播放动画
                if self._live2d_widget is not None:
                    # 获取点击位置（相对于窗口）
                    local_pos = event.position().toPoint()
                    hit_area = self._live2d_widget.get_hit_area(local_pos.x(), local_pos.y())

                    if hit_area:
                        # 点击在模型上，播放对应动作
                        self._live2d_widget.play_click_animation(hit_area)
                        self._logger.info(f"Live2D 点击区域: {hit_area}")
                    else:
                        # 点击在模型外，切换聊天窗口
                        self._toggle_chat_window()
                        self._logger.debug("点击在 Live2D 模型外，切换聊天窗口")
                else:
                    # 没有 Live2D，切换聊天窗口
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

    def closeEvent(self, event) -> None:
        """窗口关闭事件 - 确保资源清理"""
        self._logger.info("悬浮球窗口 closeEvent: 开始清理资源")

        # 清理 Live2D 组件
        if self._live2d_widget:
            try:
                self._live2d_widget.cleanup()
                self._live2d_widget.close()
                self._live2d_widget = None
                self._logger.info("Live2D 组件已清理")
            except Exception as e:
                self._logger.error(f"清理 Live2D 组件失败: {e}")
                self._live2d_widget = None

        # 清理聊天窗口
        if self._chat_window:
            try:
                self._chat_window.close()
                self._chat_window = None
                self._logger.info("聊天窗口已清理")
            except Exception as e:
                self._logger.error(f"清理聊天窗口失败: {e}")
                self._chat_window = None

        super().closeEvent(event)
        self._logger.info("悬浮球窗口 closeEvent 完成")

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
        self._logger.info(f"主进程 PID: {self._main_pid}")

        # 先清理 Live2D 组件
        if self._live2d_widget:
            try:
                self._live2d_widget.cleanup()
                self._live2d_widget.close()
                self._live2d_widget = None  # 释放引用
                self._logger.info("Live2D 组件已清理并释放引用")
            except Exception as e:
                self._logger.error(f"清理 Live2D 组件失败: {e}")
                self._live2d_widget = None  # 即使失败也置空引用

        # 先关闭聊天窗口和悬浮球窗口
        if self._chat_window:
            self._chat_window.close()
        self.close()

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
        """非阻塞地读取主进程消息（支持批量消息解包）"""
        try:
            while not self._from_main.empty():
                msg = self._from_main.get_nowait()
                # 解包批量消息
                messages = self._unwrap_batch_message(msg)
                for message in messages:
                    self._handle_ipc_message(message)
        except Exception as e:
            self._logger.error(f"悬浮球 IPC 轮询异常: {e}")

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
            self._logger.info("悬浮球收到退出消息，关闭窗口")
            # 清理 Live2D 资源
            if self._live2d_widget:
                try:
                    self._live2d_widget.cleanup()
                    self._live2d_widget.close()
                    self._live2d_widget = None
                    self._logger.info("Live2D 组件已清理")
                except Exception as e:
                    self._logger.error(f"清理 Live2D 组件失败: {e}")
            if self._chat_window:
                self._chat_window.close()
            self.close()
            QApplication.quit()
        elif msg_type == MessageType.SHOW_WINDOW:
            # 显示悬浮球窗口（预启动模式）
            self.show()
            self._logger.info("悬浮球窗口已显示（预启动模式）")
        elif msg_type == MessageType.HIDE_WINDOW:
            # 隐藏悬浮球窗口（预启动模式）
            if self._chat_window:
                self._chat_window.hide()
            self.hide()
            self._logger.info("悬浮球窗口已隐藏（预启动模式）")
        elif msg_type == MessageType.SET_THEME:
            color = msg.get("color", "#3B82F6")
            self._primary_color = QColor(color)
            self._hover_color = QColor(color).darker(115)
            self.update()
        elif msg_type == MessageType.CHAT_RECEIVE_MESSAGE:
            # 转发给聊天窗口
            if self._chat_window:
                self._chat_window._handle_ipc_message(msg)

