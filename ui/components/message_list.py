from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QScrollBar, QSizePolicy
)

from ui.components.message_card import MessageCardWidget, MessageType


class MessageListWidget(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._message_cards = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 设置滚动区域属性
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setStyleSheet("""
            QScrollArea {
                background-color: #ffffff;
                border: none;
            }
            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: #c1c1c1;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a8a8a8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # 创建内部容器
        self._container = QWidget()
        self._container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._container.setStyleSheet("background-color: #ffffff;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 8, 0, 8)
        self._layout.setSpacing(8)
        
        self.setWidget(self._container)

    def add_message(
        self,
        msg_type: MessageType,
        content: str = "",
        token_usage: dict[str, Any] | None = None,
    ) -> MessageCardWidget | None:
        # 避免添加空消息
        content = content or ""
        if not content.strip() and not token_usage:
            return None
            
        card = MessageCardWidget(msg_type, content)
        if token_usage and msg_type in ("assistant", "think"):
            card.finalize_content(token_usage)
        
        # 设置卡片宽度
        list_width = max(100, self.viewport().width())
        card.set_available_width(list_width)
        
        # 添加到布局
        self._layout.addWidget(card)
        self._message_cards.append(card)
        
        # 滚动到底部
        QTimer.singleShot(50, self.scroll_to_bottom)
        return card

    def get_last_card(self) -> MessageCardWidget | None:
        if self._message_cards:
            return self._message_cards[-1]
        return None

    def update_last_message(self, content: str) -> bool:
        card = self.get_last_card()
        if card is None:
            return False
        card.update_content(content)
        # 更新宽度
        list_width = max(100, self.viewport().width())
        card.set_available_width(list_width)
        card.adjustSize()
        QTimer.singleShot(50, self.scroll_to_bottom)
        return True

    def append_to_last_message(self, text: str) -> bool:
        card = self.get_last_card()
        if card is None:
            return False
        card.append_content(text)
        list_width = max(100, self.viewport().width())
        card.set_available_width(list_width)
        card.adjustSize()
        QTimer.singleShot(50, self.scroll_to_bottom)
        return True

    def finalize_last_message(self, token_usage: dict[str, Any] | None = None) -> bool:
        card = self.get_last_card()
        if card is None:
            return False
        card.finalize_content(token_usage)
        list_width = max(100, self.viewport().width())
        card.set_available_width(list_width)
        card.adjustSize()
        return True

    def scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_all(self) -> None:
        # 清空所有卡片
        for card in self._message_cards:
            card.setParent(None)
        self._message_cards.clear()
        
        # 清空布局
        while self._layout.count() > 0:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def update_all_cards_width(self) -> None:
        """更新所有卡片的宽度"""
        list_width = max(100, self.viewport().width())
        for card in self._message_cards:
            card.set_available_width(list_width)
            card.adjustSize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_all_cards_width()
