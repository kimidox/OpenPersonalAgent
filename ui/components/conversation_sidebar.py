from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea, QSizePolicy
)

from ui.components.conversation_list_item import ConversationListItem
from memory.conversation import Conversation
from ui.styles.style_manager import StyleManager


class ConversationSidebar(QWidget):
    """会话侧边栏组件"""
    
    new_conversation_requested = Signal()
    conversation_selected = Signal(str)
    conversation_deleted = Signal(str)
    settings_requested = Signal()
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conversation_items: dict[str, ConversationListItem] = {}
        self._selected_conversation_id: str | None = None
        self._setup_ui()
        
    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(168)
        self.setMaximumWidth(224)
        sidebar_style = StyleManager.get_style("conversation_sidebar")
        if sidebar_style:
            self.setStyleSheet(sidebar_style)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 12, 12, 12)
        self._main_layout.setSpacing(12)

        # 顶部按钮区域（新增会话 + 设置）
        top_button_layout = QHBoxLayout()
        top_button_layout.setSpacing(8)

        self._new_conversation_button = QPushButton("新增会话")
        self._new_conversation_button.setMinimumHeight(20)
        self._new_conversation_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_conversation_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._new_conversation_button.setObjectName("skillAgentNewConversationButton")
        new_btn_style = StyleManager.get_style("conversation_sidebar_new_button")
        if new_btn_style:
            self._new_conversation_button.setStyleSheet(new_btn_style)
        self._new_conversation_button.clicked.connect(self._on_new_conversation_clicked)
        top_button_layout.addWidget(self._new_conversation_button)

        self._settings_button = QPushButton("设置")
        self._settings_button.setMinimumHeight(20)
        self._settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_button.setObjectName("skillAgentSettingsButton")
        settings_btn_style = StyleManager.get_style("conversation_sidebar_settings_button")
        if settings_btn_style:
            self._settings_button.setStyleSheet(settings_btn_style)
        self._settings_button.clicked.connect(self._on_settings_clicked)
        top_button_layout.addWidget(self._settings_button)

        self._main_layout.addLayout(top_button_layout)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_area.setFrameShape(QScrollArea.NoFrame)
        self._scroll_area.setObjectName("skillAgentSidebarScrollArea")
        scroll_area_style = StyleManager.get_style("conversation_sidebar_scrollarea")
        if scroll_area_style:
            self._scroll_area.setStyleSheet(scroll_area_style)

        self._scroll_container = QWidget()
        self._scroll_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._scroll_container.setObjectName("skillAgentSidebarScrollContainer")
        scroll_container_style = StyleManager.get_style("conversation_sidebar_scroll_container")
        if scroll_container_style:
            self._scroll_container.setStyleSheet(scroll_container_style)
        self._list_layout = QVBoxLayout(self._scroll_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        self._scroll_area.setWidget(self._scroll_container)
        self._main_layout.addWidget(self._scroll_area)
        
    def _on_new_conversation_clicked(self) -> None:
        """新增会话按钮点击事件"""
        self.new_conversation_requested.emit()
    
    def _on_settings_clicked(self) -> None:
        """设置按钮点击事件"""
        self.settings_requested.emit()
        
    def add_conversation(self, conversation: Conversation) -> ConversationListItem:
        """添加会话"""
        conversation_id = conversation.conversation_id
        title = conversation.title or "新会话"
        
        item = ConversationListItem(conversation_id, title)
        item.selected.connect(self._on_conversation_selected)
        item.delete_requested.connect(self._on_conversation_deleted)
        
        self._list_layout.insertWidget(self._list_layout.count() - 1, item)
        self._conversation_items[conversation_id] = item
        
        return item
        
    def remove_conversation(self, conversation_id: str) -> None:
        """删除会话"""
        if conversation_id in self._conversation_items:
            item = self._conversation_items[conversation_id]
            item.setParent(None)
            del self._conversation_items[conversation_id]
            
            if self._selected_conversation_id == conversation_id:
                self._selected_conversation_id = None
                
    def set_selected_conversation(self, conversation_id: str) -> None:
        """设置当前选中会话"""
        for cid, item in self._conversation_items.items():
            item.set_selected(cid == conversation_id)
        self._selected_conversation_id = conversation_id
        
    def load_conversations(self, conversations: list[Conversation]) -> None:
        """从会话列表中加载会话"""
        self.clear_conversations()
        
        for conversation in conversations:
            self.add_conversation(conversation)
            
    def clear_conversations(self) -> None:
        """清空所有会话"""
        for item in self._conversation_items.values():
            item.setParent(None)
        self._conversation_items.clear()
        self._selected_conversation_id = None
        
    def _on_conversation_selected(self, conversation_id: str) -> None:
        """会话被选中事件"""
        self.set_selected_conversation(conversation_id)
        self.conversation_selected.emit(conversation_id)
        
    def _on_conversation_deleted(self, conversation_id: str) -> None:
        """会话删除请求事件"""
        self.conversation_deleted.emit(conversation_id)
