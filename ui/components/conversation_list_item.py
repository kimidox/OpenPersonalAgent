from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QRect
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QToolButton, QSizePolicy
)
from ui.styles.style_manager import StyleManager


class ElideLabel(QLabel):
    """支持文本省略的标签"""
    
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self._elide_mode = Qt.TextElideMode.ElideRight
        
    def setText(self, text: str) -> None:
        self._full_text = text
        self._update_elided_text()
        
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_text()
        
    def _update_elided_text(self) -> None:
        """根据可用宽度更新显示的文本"""
        fm = QFontMetrics(self.font())
        available_width = self.width()
        elided = fm.elidedText(self._full_text, self._elide_mode, available_width)
        super().setText(elided)


_DELETE_ICON: QIcon | None = None


def create_delete_pixmap(size: int, color: QColor) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color)
    pen.setWidthF(max(1.35, size * 0.105))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    m = size * 0.3
    from PySide6.QtCore import QPointF
    painter.drawLine(QPointF(m, m), QPointF(size - m, size - m))
    painter.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    painter.end()
    return pm


def create_delete_icon() -> QIcon:
    global _DELETE_ICON
    if _DELETE_ICON is None:
        base = QColor("#64748b")  # 与 tab 关闭按钮一致的颜色
        ico = QIcon()
        for d in (16, 20, 24):
            ico.addPixmap(create_delete_pixmap(d, base))
        _DELETE_ICON = ico
    return _DELETE_ICON


class ConversationListItem(QWidget):
    """会话列表项组件"""
    
    # 信号定义
    selected = Signal(str)  # 会话被选中，参数为conversation_id
    delete_requested = Signal(str)  # 请求删除会话，参数为conversation_id
    
    def __init__(
        self,
        conversation_id: str,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._conversation_id = conversation_id
        self._title = title
        self._is_selected = False
        self._setup_ui()
        
    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(8, 6, 8, 6)
        self._main_layout.setSpacing(8)

        # 标题标签 - 使用支持文本省略的自定义标签
        self._title_label = ElideLabel(self._title)
        self._title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._main_layout.addWidget(self._title_label)

        # 删除按钮 - 与 tab 关闭按钮保持一致风格
        self._delete_button = QToolButton()
        self._delete_button.setObjectName("skillAgentTabCloseButton")  # 使用相同的 objectName 以便样式表生效
        self._delete_button.setIcon(create_delete_icon())
        self._delete_button.setIconSize(QSize(14, 14))
        self._delete_button.setAutoRaise(True)
        self._delete_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._delete_button.setToolTip("删除会话")
        self._delete_button.setFixedSize(20, 20)  # 与 tab 关闭按钮尺寸一致
        # 注意：删除按钮使用主窗口样式表中的相同 objectName，不需要单独设置样式
        self._delete_button.clicked.connect(self._on_delete_clicked)
        self._main_layout.addWidget(self._delete_button)

        self._update_style()
        
    def set_title(self, title: str) -> None:
        """设置会话标题"""
        self._title = title
        self._title_label.setText(title)
        
    def get_title(self) -> str:
        """获取会话标题"""
        return self._title
        
    def get_conversation_id(self) -> str:
        """获取会话ID"""
        return self._conversation_id
        
    def set_selected(self, selected: bool) -> None:
        """设置选中状态"""
        if self._is_selected != selected:
            self._is_selected = selected
            self._update_style()
            
    def is_selected(self) -> bool:
        """获取选中状态"""
        return self._is_selected
        
    def _update_style(self) -> None:
        """更新样式"""
        if self._is_selected:
            selected_style = StyleManager.get_style("conversation_list_item_selected")
            if selected_style:
                self.setStyleSheet(selected_style)
        else:
            normal_style = StyleManager.get_style("conversation_list_item_normal")
            if normal_style:
                self.setStyleSheet(normal_style)
            
    def mousePressEvent(self, event) -> None:
        """点击事件：选中会话"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_selected(True)
            self.selected.emit(self._conversation_id)
        super().mousePressEvent(event)
        
    def _on_delete_clicked(self) -> None:
        """删除按钮点击事件"""
        self.delete_requested.emit(self._conversation_id)
