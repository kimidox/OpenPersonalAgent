from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect
from PySide6.QtGui import QFont


def show_system_notification(tray_icon, title: str, message: str, duration_ms: int = 5000) -> None:
    if tray_icon is None:
        return
    tray_icon.showMessage(title, message, msecs=duration_ms)


class ToastWindow(QWidget):
    def __init__(self, title: str, message: str, duration_seconds: int = 30):
        super().__init__()
        self._duration_seconds = duration_seconds
        self._title = title
        self._message = message
        self._init_ui()
        self._setup_timer()

    def _init_ui(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(320)
        self.setMinimumHeight(80)

        container = QWidget(self)
        container.setObjectName("toastContainer")
        container.setStyleSheet("""
            #toastContainer {
                background-color: rgba(45, 45, 45, 230);
                border-radius: 8px;
                border: 1px solid rgba(80, 80, 80, 180);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(container)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 12, 16, 12)
        container_layout.setSpacing(6)

        title_label = QLabel(self._title)
        title_label.setObjectName("toastTitle")
        title_label.setStyleSheet("""
            #toastTitle {
                color: #FFFFFF;
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }
        """)
        title_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        title_label.setWordWrap(True)
        container_layout.addWidget(title_label)

        message_label = QLabel(self._message)
        message_label.setObjectName("toastMessage")
        message_label.setStyleSheet("""
            #toastMessage {
                color: #CCCCCC;
                font-size: 12px;
                background: transparent;
            }
        """)
        message_label.setFont(QFont("Microsoft YaHei", 9))
        message_label.setWordWrap(True)
        container_layout.addWidget(message_label)

        self._adjust_size()

    def _adjust_size(self) -> None:
        self.adjustSize()
        self._position_window()

    def _position_window(self) -> None:
        screen = self.screen()
        if screen is None:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        screen_geometry = screen.availableGeometry()
        margin = 20
        x = screen_geometry.right() - self.width() - margin
        y = screen_geometry.bottom() - self.height() - margin
        self.move(x, y)

    def _setup_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._timer.start(self._duration_seconds * 1000)

    def _fade_out(self) -> None:
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_step = 0
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._do_fade)
        self._fade_timer.start(30)

    def _do_fade(self) -> None:
        self._fade_step += 1
        opacity = 1.0 - (self._fade_step * 0.1)
        if opacity <= 0:
            self._fade_timer.stop()
            self.close()
            self.deleteLater()
        else:
            self._opacity_effect.setOpacity(opacity)

    def show_toast(self) -> None:
        self.show()
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)
        self._fade_in_step = 0
        self._fade_in_timer = QTimer(self)
        self._fade_in_timer.timeout.connect(self._do_fade_in)
        self._fade_in_timer.start(30)

    def _do_fade_in(self) -> None:
        self._fade_in_step += 1
        opacity = self._fade_in_step * 0.1
        if opacity >= 1.0:
            self._opacity_effect.setOpacity(1.0)
            self._fade_in_timer.stop()
        else:
            self._opacity_effect.setOpacity(opacity)

    def mousePressEvent(self, event) -> None:
        self.close()
        self.deleteLater()


def show_toast_notification(title: str, message: str, duration_seconds: int = 30) -> ToastWindow:
    toast = ToastWindow(title, message, duration_seconds)
    toast.show_toast()
    return toast


def send_notification(notification_type: str, title: str, message: str, tray_icon=None) -> ToastWindow | None:
    if notification_type == 'system':
        show_system_notification(tray_icon, title, message)
        return None
    elif notification_type == 'toast':
        return show_toast_notification(title, message)
    else:
        raise ValueError(f"Unknown notification type: {notification_type}. Supported types: 'system', 'toast'")