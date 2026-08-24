"""
消息气泡组件

从 floating_ball_process.py 内部类提取，逻辑完全等价。

Business purpose:
    在聊天窗口中显示单条消息的气泡样式组件。

Modification notes:
    2026-07-29: 从 run_floating_ball_process 内部类提取为独立模块

Related tests:
    tests/test_floating_ball_widgets.py (待补充)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from floating_ball.floating_ball_widgets._constants import (
    DEFAULT_BG_COLOR,
    DEFAULT_BORDER_COLOR,
    DEFAULT_TEXT_COLOR,
)


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
