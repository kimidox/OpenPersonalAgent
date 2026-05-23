from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QTabBar, QTabWidget, QToolButton

from ui.styles.color_scheme import TAB_CLOSE_X


_TAB_CLOSE_BTN_OBJECT_NAME = "skillAgentTabCloseButton"
_TAB_CLOSE_ICON: QIcon | None = None


def create_close_pixmap(size: int, color: QColor) -> QPixmap:
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


def create_close_icon() -> QIcon:
    global _TAB_CLOSE_ICON
    if _TAB_CLOSE_ICON is None:
        base = QColor(TAB_CLOSE_X)
        ico = QIcon()
        for d in (16, 20, 24):
            ico.addPixmap(create_close_pixmap(d, base))
        _TAB_CLOSE_ICON = ico
    return _TAB_CLOSE_ICON


class TabCloseButton(QToolButton):
    clicked_signal = Signal()

    def __init__(self, parent: QTabBar | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(_TAB_CLOSE_BTN_OBJECT_NAME)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(create_close_icon())
        self.setIconSize(QSize(14, 14))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setFixedSize(20, 20)
        self.setToolTip("关闭")
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self) -> None:
        self.clicked_signal.emit()

    def refresh_icon(self) -> None:
        self.setIcon(create_close_icon())
        self.setIconSize(QSize(14, 14))


def setup_tab_close_button(tab_bar: QTabBar, index: int) -> TabCloseButton | None:
    if not tab_bar.tabsClosable():
        return None
    existing = tab_bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
    if isinstance(existing, TabCloseButton):
        existing.refresh_icon()
        return existing
    btn = TabCloseButton(tab_bar)
    tab_bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)
    btn.clicked_signal.connect(lambda idx=index: tab_bar.tabCloseRequested.emit(idx))
    return btn


def refresh_all_tab_close_buttons(tab_widget: QTabWidget) -> None:
    bar = tab_widget.tabBar()
    if not bar.tabsClosable():
        return
    for i in range(bar.count()):
        setup_tab_close_button(bar, i)
