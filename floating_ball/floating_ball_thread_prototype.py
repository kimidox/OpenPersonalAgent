"""
单进程架构原型 - 悬浮球线程版本

目标：验证 Qt 能否在独立线程中运行，替代双进程架构

核心设计：
1. Qt 线程：运行 QApplication 和悬浮球窗口
2. 主线程：运行主应用逻辑
3. 通信：使用 queue.Queue 替代 multiprocessing.Queue
4. 线程安全：使用 QTimer 在 Qt 线程轮询消息

关键测试：
- Qt 能否在独立线程运行
- 启动时间是否改善
- 内存占用是否降低
- 线程间通信是否稳定
"""
from __future__ import annotations

import sys
import time
import threading
import queue
from pathlib import Path
from typing import Optional, Callable

# 确保项目根目录在 Python 路径中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from logger import get_logger
from floating_ball.floating_ball_ipc import MessageType


class QtThreadManager:
    """
    Qt 线程管理器
    
    在独立线程中运行 QApplication，提供线程安全的消息传递
    """
    
    def __init__(self):
        self._logger = get_logger()
        self._qt_thread: Optional[threading.Thread] = None
        self._qt_app = None
        self._ball_window = None
        self._chat_window = None
        
        # 线程安全的消息队列
        self._to_qt_queue = queue.Queue()
        self._from_qt_queue = queue.Queue()
        
        # Qt 线程状态
        self._qt_ready = threading.Event()
        self._qt_error = None
        
        # 性能监控
        self._start_time = None
        self._perf_log = []
    
    def start(self) -> bool:
        """
        启动 Qt 线程
        
        Returns:
            True 如果启动成功
        """
        self._start_time = time.time()
        self._log_perf("开始启动 Qt 线程")
        
        # 创建 Qt 线程
        self._qt_thread = threading.Thread(
            target=self._run_qt_loop,
            name="qt-floating-ball",
            daemon=False,
        )
        self._qt_thread.start()
        self._log_perf("Qt 线程已创建")
        
        # 等待 Qt 初始化完成（超时 10 秒）
        if not self._qt_ready.wait(timeout=10.0):
            self._logger.error("Qt 线程初始化超时")
            return False
        
        # 检查是否有错误
        if self._qt_error:
            self._logger.error(f"Qt 线程启动失败: {self._qt_error}")
            return False
        
        self._log_perf("Qt 线程启动成功")
        self._print_perf_report()
        
        return True
    
    def stop(self, timeout: float = 5.0) -> None:
        """
        停止 Qt 线程
        
        Args:
            timeout: 等待超时时间（秒）
        """
        self._logger.info("正在停止 Qt 线程...")
        
        # 发送退出消息
        self.send_to_qt({"type": MessageType.EXIT})
        
        # 等待线程结束
        if self._qt_thread and self._qt_thread.is_alive():
            self._qt_thread.join(timeout=timeout)
            if self._qt_thread.is_alive():
                self._logger.warning("Qt 线程未能在超时时间内停止")
        
        self._logger.info("Qt 线程已停止")
    
    def send_to_qt(self, message: dict) -> None:
        """
        发送消息到 Qt 线程
        
        Args:
            message: 消息字典
        """
        try:
            self._to_qt_queue.put(message, block=False)
        except Exception as e:
            self._logger.error(f"发送消息到 Qt 失败: {e}")
    
    def receive_from_qt(self, timeout: float = 0.1) -> Optional[dict]:
        """
        从 Qt 线程接收消息
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            消息字典，如果超时则返回 None
        """
        try:
            return self._from_qt_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def _run_qt_loop(self) -> None:
        """Qt 线程主循环"""
        try:
            # 在 Qt 线程中导入和初始化
            self._init_qt_in_thread()
            
            # 通知主线程初始化完成
            self._qt_ready.set()
            
            # 运行 Qt 事件循环（阻塞）
            if self._qt_app:
                self._logger.info("Qt 事件循环开始运行")
                self._qt_app.exec()
                self._logger.info("Qt 事件循环已退出")
        
        except Exception as e:
            self._qt_error = str(e)
            self._qt_ready.set()
            self._logger.exception(f"Qt 线程异常: {e}")
    
    def _init_qt_in_thread(self) -> None:
        """在 Qt 线程中初始化 Qt 应用"""
        self._log_perf("Qt 线程开始初始化")
        
        # 延迟导入 PySide6（在线程内部）
        from PySide6.QtCore import Qt, QTimer, QPoint
        from PySide6.QtGui import QPainter, QColor, QBrush, QIcon, QAction
        from PySide6.QtWidgets import (
            QApplication, QWidget, QMenu, QStyleFactory,
            QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
            QScrollArea, QFrame,
        )
        
        self._log_perf("PySide6 导入完成")
        
        # 设置高 DPI 感知
        self._set_dpi_awareness()
        self._log_perf("DPI 感知设置完成")
        
        # 创建 QApplication（必须在 Qt 线程）
        import os
        os.environ["QSG_RHI_BACKEND"] = "opengl"
        
        self._qt_app = QApplication(sys.argv)
        fusion = QStyleFactory.create("Fusion")
        if fusion:
            self._qt_app.setStyle(fusion)
        
        # 设置应用图标
        from resource_path import paths
        icon_path = paths.get_bundled_resource("application.ico")
        if icon_path.exists():
            self._qt_app.setWindowIcon(QIcon(str(icon_path)))
        
        self._log_perf("QApplication 初始化完成")
        
        # 创建悬浮球窗口（使用组合模式，而不是继承）
        self._ball_window = FloatingBallWindowThread(
            self._to_qt_queue,
            self._from_qt_queue,
        )
        self._ball_window.show()
        
        self._log_perf("悬浮球窗口创建并显示完成")
    
    def _set_dpi_awareness(self) -> None:
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
    
    def _log_perf(self, stage: str) -> None:
        """记录性能日志"""
        if self._start_time:
            elapsed = time.time() - self._start_time
            self._perf_log.append(f"[{elapsed:.3f}s] {stage}")
    
    def _print_perf_report(self) -> None:
        """打印性能报告"""
        total_time = time.time() - self._start_time
        self._logger.info("=" * 60)
        self._logger.info("单进程架构启动性能报告:")
        for log_entry in self._perf_log:
            self._logger.info(f"  {log_entry}")
        self._logger.info(f"  [{total_time:.3f}s] 总启动时间")
        self._logger.info("=" * 60)
        
        # 判断是否达标
        if total_time < 1.0:
            self._logger.info(f"✓ 启动性能达标（{total_time:.3f}s < 1s）")
        else:
            self._logger.warning(f"✗ 启动性能未达标（{total_time:.3f}s >= 1s）")


class FloatingBallWindowThread:
    """
    悬浮球窗口（线程版本）
    
    使用组合模式而不是继承，避免模块导入时的类定义问题。
    在运行时动态创建 QWidget 实例并连接事件处理。
    """
    
    BALL_SIZE = 50
    BALL_MARGIN = 20
    
    def __init__(
        self,
        from_main_queue: queue.Queue,
        to_main_queue: queue.Queue,
    ):
        # 延迟导入 PySide6（在实例创建时）
        from PySide6.QtCore import Qt, QTimer, QPoint
        from PySide6.QtGui import QPainter, QColor, QBrush, QAction
        from PySide6.QtWidgets import QWidget, QMenu
        
        # 创建实际的 QWidget 实例
        self._widget = QWidget()
        self._logger = get_logger()
        self._from_main = from_main_queue
        self._to_main = to_main_queue
        
        # 拖拽状态
        self._is_dragging = False
        self._drag_start_global = QPoint()
        self._drag_start_pos = QPoint()
        
        # 颜色配置
        self._primary_color = QColor("#3B82F6")
        self._hover_color = QColor("#2563EB")
        self._is_hovered = False
        
        # 初始化窗口
        self._init_window()
        self._init_menu()
        self._init_position()
        self._init_message_poll()
        
        # 代理 QWidget 的方法
        self.show = self._widget.show
        self.hide = self._widget.hide
        self.close = self._widget.close
    
    def _init_window(self) -> None:
        """初始化窗口"""
        from PySide6.QtCore import Qt
        
        self._widget.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self._widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._widget.setFixedSize(self.BALL_SIZE, self.BALL_SIZE)
        self._widget.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 连接绘制事件
        self._widget.paintEvent = self._paint_event
        self._widget.mousePressEvent = self._mouse_press_event
        self._widget.mouseMoveEvent = self._mouse_move_event
        self._widget.mouseReleaseEvent = self._mouse_release_event
        self._widget.enterEvent = self._enter_event
        self._widget.leaveEvent = self._leave_event
        self._widget.contextMenuEvent = self._context_menu_event
    
    def _init_menu(self) -> None:
        """初始化右键菜单"""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        
        self._menu = QMenu(self._widget)
        self._menu.setStyleSheet(
            "QMenu { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 6px; }"
            "QMenu::item { padding: 6px 24px; border-radius: 4px; }"
            "QMenu::item:selected { background-color: #eff6ff; color: #1d4ed8; }"
            "QMenu::separator { height: 1px; background-color: #e5e7eb; margin: 4px 0px; }"
        )
        
        # 测试按钮
        self._test_action = QAction("测试消息", self._widget)
        self._test_action.triggered.connect(self._on_test_message)
        self._menu.addAction(self._test_action)
        
        self._menu.addSeparator()
        
        # 退出按钮
        self._quit_action = QAction("退出", self._widget)
        self._quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self._quit_action)
    
    def _init_position(self) -> None:
        """默认放到屏幕右下角"""
        from PySide6.QtWidgets import QApplication
        
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        x = geometry.width() - self.BALL_SIZE - self.BALL_MARGIN
        y = geometry.height() - self.BALL_SIZE - self.BALL_MARGIN
        self._widget.move(x, y)
    
    def _init_message_poll(self) -> None:
        """启动消息轮询定时器"""
        from PySide6.QtCore import QTimer
        
        self._poll_timer = QTimer(self._widget)
        self._poll_timer.timeout.connect(self._poll_messages)
        self._poll_timer.start(100)  # 100ms 轮询一次
    
    # ----------------- 事件处理 -----------------
    
    def _paint_event(self, event) -> None:
        from PySide6.QtGui import QPainter, QBrush, QColor
        from PySide6.QtCore import Qt, QPoint
        
        painter = QPainter(self._widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 背景圆
        color = self._hover_color if self._is_hovered else self._primary_color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(0, 0, self.BALL_SIZE, self.BALL_SIZE)
        
        # 绘制聊天泡泡图标
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.setPen(Qt.PenStyle.NoPen)
        
        # 气泡主体
        bubble_rect = self._widget.rect().adjusted(14, 13, -14, -17)
        painter.drawRoundedRect(bubble_rect, 8, 8)
        
        # 气泡尖角
        tail_points = [
            QPoint(28, 33),
            QPoint(34, 39),
            QPoint(34, 33),
        ]
        painter.drawPolygon(tail_points)
        
        painter.end()
    
    def _mouse_press_event(self, event) -> None:
        from PySide6.QtCore import Qt
        
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_global = event.globalPosition().toPoint()
            self._drag_start_pos = self._widget.pos()
    
    def _mouse_move_event(self, event) -> None:
        from PySide6.QtCore import Qt
        
        if event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            delta = current - self._drag_start_global
            if not self._is_dragging and delta.manhattanLength() > 5:
                self._is_dragging = True
            if self._is_dragging:
                self._widget.move(self._drag_start_pos + delta)
    
    def _mouse_release_event(self, event) -> None:
        from PySide6.QtCore import Qt
        
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._is_dragging:
                # 点击事件：发送消息到主线程
                self._send_message(MessageType.SHOW_MAIN_WINDOW)
            self._is_dragging = False
    
    def _enter_event(self, event) -> None:
        self._is_hovered = True
        self._widget.update()
    
    def _leave_event(self, event) -> None:
        self._is_hovered = False
        self._widget.update()
    
    def _context_menu_event(self, event) -> None:
        self._menu.exec(event.globalPos())
    
    # ----------------- 菜单回调 -----------------
    
    def _on_test_message(self) -> None:
        """测试消息发送"""
        self._send_message(MessageType.TOGGLE_CHAT, content="测试消息")
        self._logger.info("已发送测试消息到主线程")
    
    def _on_quit(self) -> None:
        """退出"""
        self._send_message(MessageType.EXIT)
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
    
    # ----------------- 消息处理 -----------------
    
    def _send_message(self, msg_type: MessageType, **payload) -> None:
        """发送消息到主线程"""
        message = {"type": msg_type, **payload}
        try:
            self._to_main.put(message, block=False)
        except Exception as e:
            self._logger.error(f"发送消息失败: {e}")
    
    def _poll_messages(self) -> None:
        """轮询来自主线程的消息"""
        try:
            # 非阻塞获取所有消息
            while True:
                try:
                    msg = self._from_main.get_nowait()
                    self._handle_message(msg)
                except queue.Empty:
                    break
        except Exception as e:
            self._logger.error(f"消息轮询异常: {e}")
    
    def _handle_message(self, msg: dict) -> None:
        """处理来自主线程的消息"""
        from PySide6.QtGui import QColor
        
        msg_type = msg.get("type")
        self._logger.info(f"收到主线程消息: {msg_type}")
        
        if msg_type == MessageType.EXIT:
            self._logger.info("收到退出消息")
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        elif msg_type == MessageType.SHOW_WINDOW:
            self._widget.show()
            self._logger.info("窗口已显示")
        elif msg_type == MessageType.HIDE_WINDOW:
            self._widget.hide()
            self._logger.info("窗口已隐藏")
        elif msg_type == MessageType.SET_THEME:
            color = msg.get("color", "#3B82F6")
            self._primary_color = QColor(color)
            self._hover_color = QColor(color).darker(115)
            self._widget.update()


# 测试入口
def test_qt_thread():
    """测试 Qt 线程运行"""
    import time
    
    print("=" * 60)
    print("单进程架构原型测试")
    print("=" * 60)
    
    # 创建 Qt 线程管理器
    manager = QtThreadManager()
    
    # 启动 Qt 线程
    print("\n启动 Qt 线程...")
    if not manager.start():
        print("✗ Qt 线程启动失败")
        return
    
    print("✓ Qt 线程启动成功")
    
    # 测试消息接收（主线程轮询）
    print("\n开始监听消息（按 Ctrl+C 停止）...")
    try:
        while True:
            msg = manager.receive_from_qt(timeout=0.1)
            if msg:
                print(f"收到消息: {msg}")
            
            time.sleep(0.05)  # 避免 CPU 占用过高
    
    except KeyboardInterrupt:
        print("\n用户中断，正在停止...")
    
    # 停止 Qt 线程
    print("\n停止 Qt 线程...")
    manager.stop(timeout=3.0)
    print("✓ Qt 线程已停止")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_qt_thread()