from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from ui.styles.style_manager import StyleManager


_AWAIT_USER_SCROLL_MAX_RATIO = 0.32
_AWAIT_USER_SCROLL_MIN_PX = 200
_AWAIT_USER_SCROLL_MAX_PX = 420


class _ClickableChoiceLabel(QLabel):
    def __init__(self, text: str, radio: QRadioButton) -> None:
        super().__init__(text)
        self._radio = radio
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("color: #374151; background: transparent;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._radio.setChecked(True)
        super().mousePressEvent(event)


class AwaitUserCard(QFrame):
    confirm_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("skillAgentAwaitUserCard")
        self.setVisible(False)
        self._apply_style()
        self._setup_ui()
        self._selected_text: str | None = None
        self._on_confirm_send: Callable[[str], None] | None = None

    def _apply_style(self) -> None:
        style = StyleManager.get_style("await_user_card_frame")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 10, 12, 10)
        self._main_layout.setSpacing(8)

    def show_prompt(self, spec: dict[str, Any], *, on_confirm_send: Callable[[str], None] | None = None) -> None:
        self.clear_prompt()
        self._on_confirm_send = on_confirm_send
        question = str(spec.get("question") or "").strip()
        context = str(spec.get("context") or "").strip()
        choices_raw = spec.get("choices")
        choices: list[str] = []
        if isinstance(choices_raw, list):
            for c in choices_raw:
                if c is None:
                    continue
                s = str(c).strip()
                if s:
                    choices.append(s)

        q_lab = QLabel(question or "（模型未提供具体问题）")
        q_lab.setObjectName("skillAgentAwaitUserQuestion")
        q_lab.setWordWrap(True)

        if choices:
            scroll = QScrollArea()
            scroll.setObjectName("skillAgentAwaitUserScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scr = QApplication.primaryScreen()
            scr_h = scr.availableGeometry().height() if scr is not None else 900
            scroll.setMaximumHeight(
                max(
                    _AWAIT_USER_SCROLL_MIN_PX,
                    min(_AWAIT_USER_SCROLL_MAX_PX, int(scr_h * _AWAIT_USER_SCROLL_MAX_RATIO)),
                )
            )
            scroll.setMinimumHeight(100)
            scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

            scroll_inner = QWidget()
            s_layout = QVBoxLayout(scroll_inner)
            s_layout.setContentsMargins(0, 0, 6, 0)
            s_layout.setSpacing(8)
            s_layout.addWidget(q_lab)
            if context:
                ctx_lab = QLabel(context)
                ctx_lab.setObjectName("skillAgentAwaitUserHint")
                ctx_lab.setWordWrap(True)
                s_layout.addWidget(ctx_lab)
            hint = QLabel("请选择一个建议回答，点击下方「确定」将立即发送（无需再点发送）：")
            hint.setObjectName("skillAgentAwaitUserHint")
            hint.setWordWrap(True)
            s_layout.addWidget(hint)

            group = QButtonGroup(self)
            group.setExclusive(True)
            for label in choices:
                row = QWidget()
                row_l = QHBoxLayout(row)
                row_l.setContentsMargins(0, 0, 0, 0)
                row_l.setSpacing(8)
                rb = QRadioButton()
                rb.setProperty("choice_answer", label)
                lab = _ClickableChoiceLabel(label, rb)
                lab.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                row_l.addWidget(rb, alignment=Qt.AlignmentFlag.AlignTop)
                row_l.addWidget(lab, stretch=1)
                group.addButton(rb)
                s_layout.addWidget(row)

            scroll.setWidget(scroll_inner)
            self._main_layout.addWidget(scroll)

            self._confirm_btn = QPushButton("确定")
            self._confirm_btn.setObjectName("skillAgentAwaitUserConfirmButton")
            self._confirm_btn.setEnabled(False)
            self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            def _on_choice(btn: QAbstractButton) -> None:
                ans = btn.property("choice_answer")
                text = str(ans) if ans is not None and str(ans) else btn.text()
                self._selected_text = text.strip() or None
                self._confirm_btn.setEnabled(bool(self._selected_text))

            group.buttonClicked.connect(_on_choice)
            self._confirm_btn.clicked.connect(self._on_confirm)
            self._main_layout.addWidget(self._confirm_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            self._main_layout.addWidget(q_lab)
            if context:
                ctx_lab = QLabel(context)
                ctx_lab.setObjectName("skillAgentAwaitUserHint")
                ctx_lab.setWordWrap(True)
                self._main_layout.addWidget(ctx_lab)
            free = QLabel("未提供固定选项：请在下方输入框自由输入后发送。")
            free.setObjectName("skillAgentAwaitUserHint")
            free.setWordWrap(True)
            self._main_layout.addWidget(free)

        self.setVisible(True)

    def clear_prompt(self) -> None:
        self.setVisible(False)
        self._selected_text = None
        while self._main_layout.count():
            item = self._main_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def has_active_prompt(self) -> bool:
        return self.isVisible()

    def _on_confirm(self) -> None:
        if self._selected_text:
            self.confirm_clicked.emit(self._selected_text)
            if self._on_confirm_send:
                self._on_confirm_send(self._selected_text)
