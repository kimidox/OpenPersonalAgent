from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QScrollBar

from ui.components.message_card import MessageCardWidget, MessageType


class MessageListWidget(QListWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QListWidget.NoFrame)
        self.setSpacing(8)
        self.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: none;
                outline: none;
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
        
        item = QListWidgetItem(self)
        self.addItem(item)
        self.setItemWidget(item, card)
        
        # 设置卡片的宽度
        list_width = max(100, self.viewport().width())
        card.set_available_width(list_width)
        
        # 手动设置 item 尺寸以确保卡片能正确显示
        self._update_item_size(item, card)
        
        self.scroll_to_bottom()
        return card

    def get_last_card(self) -> MessageCardWidget | None:
        count = self.count()
        if count == 0:
            return None
        item = self.item(count - 1)
        return self.itemWidget(item)

    def update_last_message(self, content: str) -> bool:
        card = self.get_last_card()
        if card is None:
            return False
        card.update_content(content)
        self._update_last_item_size()
        self.scroll_to_bottom()
        return True

    def append_to_last_message(self, text: str) -> bool:
        card = self.get_last_card()
        if card is None:
            return False
        card.append_content(text)
        self._update_last_item_size()
        self.scroll_to_bottom()
        return True

    def finalize_last_message(self, token_usage: dict[str, Any] | None = None) -> bool:
        card = self.get_last_card()
        if card is None:
            return False
        card.finalize_content(token_usage)
        self._update_last_item_size()
        return True

    def _update_last_item_size(self) -> None:
        count = self.count()
        if count == 0:
            return
        item = self.item(count - 1)
        card = self.itemWidget(item)
        if card:
            self._update_item_size(item, card)

    def _update_item_size(self, item: QListWidgetItem, card: MessageCardWidget) -> None:
        # 强制计算卡片尺寸
        card.adjustSize()
        # 使用视图宽度计算合适的高度
        list_width = max(100, self.viewport().width())
        # 直接使用卡片的实际高度
        card_height = card.sizeHint().height()
        item.setSizeHint(QSize(list_width, card_height))

    def scroll_to_bottom(self) -> None:
        self.scrollToBottom()

    def clear_all(self) -> None:
        self.clear()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        list_width = max(100, self.viewport().width())
        # 调整窗口大小时，更新所有消息项的尺寸
        for i in range(self.count()):
            item = self.item(i)
            card = self.itemWidget(item)
            if card:
                # 更新卡片宽度
                card.set_available_width(list_width)
                # 更新尺寸
                self._update_item_size(item, card)
