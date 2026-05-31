from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from ui.styles.style_manager import StyleManager
from ui.utils.file_upload_manager import UploadedFileInfo

if TYPE_CHECKING:
    pass


def get_file_icon(extension: str) -> str:
    icon_map = {
        "pdf": "📄",
        "docx": "📝",
        "doc": "📝",
        "xlsx": "📊",
        "xls": "📊",
        "txt": "📃",
        "md": "📑",
        "json": "⚙",
    }
    return icon_map.get(extension.lower(), "📎")


class FilePreviewCard(QFrame):
    remove_clicked = Signal(str)
    preview_clicked = Signal(str)

    def __init__(
        self,
        file_info: UploadedFileInfo,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_info = file_info
        self.setObjectName("skillAgentFilePreviewCard")
        self._apply_style()
        self._setup_ui()
        self._update_display()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("file_preview_card")
        if style:
            self.setStyleSheet(style)
        else:
            self.setStyleSheet("""
                QFrame#skillAgentFilePreviewCard {
                    background-color: #f9fafb;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    padding: 8px;
                }
                QFrame#skillAgentFilePreviewCard:hover {
                    background-color: #f3f4f6;
                    border-color: #d1d5db;
                }
            """)

    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)
        self.setMinimumHeight(60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(8, 6, 8, 6)
        self._main_layout.setSpacing(8)

        self._icon_label = QLabel(get_file_icon(self._file_info.extension))
        self._icon_label.setStyleSheet("font-size: 20px;")
        self._icon_label.setFixedSize(28, 28)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._main_layout.addWidget(self._icon_label)

        self._info_container = QWidget()
        self._info_layout = QVBoxLayout(self._info_container)
        self._info_layout.setContentsMargins(0, 0, 0, 0)
        self._info_layout.setSpacing(2)

        self._name_label = QLabel(self._file_info.original_name)
        self._name_label.setObjectName("skillAgentFileName")
        self._name_label.setStyleSheet("font-size: 10pt; color: #374151; font-weight: 500;")
        self._name_label.setWordWrap(True)
        self._name_label.setMaximumWidth(180)
        self._info_layout.addWidget(self._name_label)

        self._size_label = QLabel(self._file_info.get_file_size_display())
        self._size_label.setObjectName("skillAgentFileSize")
        self._size_label.setStyleSheet("font-size: 9pt; color: #6b7280;")
        self._info_layout.addWidget(self._size_label)

        self._status_label = QLabel()
        self._status_label.setObjectName("skillAgentFileStatus")
        self._status_label.setStyleSheet("font-size: 8pt; color: #9ca3af;")
        self._info_layout.addWidget(self._status_label)

        self._main_layout.addWidget(self._info_container, stretch=1)

        self._remove_btn = QPushButton("×")
        self._remove_btn.setObjectName("skillAgentFileRemoveButton")
        self._remove_btn.setFixedSize(20, 20)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.clicked.connect(self._on_remove)
        remove_style = StyleManager.get_style("file_preview_remove_button")
        if remove_style:
            self._remove_btn.setStyleSheet(remove_style)
        else:
            self._remove_btn.setStyleSheet("""
                QPushButton#skillAgentFileRemoveButton {
                    background-color: transparent;
                    color: #9ca3af;
                    border: none;
                    border-radius: 10px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton#skillAgentFileRemoveButton:hover {
                    background-color: #fee2e2;
                    color: #ef4444;
                }
            """)
        self._main_layout.addWidget(self._remove_btn)

    def _update_display(self) -> None:
        if self._file_info.is_parsing:
            self._status_label.setText("解析中...")
            self._status_label.setStyleSheet("font-size: 8pt; color: #2563eb;")
        elif self._file_info.is_success:
            self._status_label.setText("已解析")
            self._status_label.setStyleSheet("font-size: 8pt; color: #16a34a;")
        elif self._file_info.parse_error:
            self._status_label.setText("解析失败")
            self._status_label.setStyleSheet("font-size: 8pt; color: #ef4444;")
        else:
            self._status_label.setText("待解析")
            self._status_label.setStyleSheet("font-size: 8pt; color: #9ca3af;")

    def update_file_info(self, file_info: UploadedFileInfo) -> None:
        self._file_info = file_info
        self._update_display()

    def get_file_info(self) -> UploadedFileInfo:
        return self._file_info

    def get_file_id(self) -> str:
        return self._file_info.file_id

    def _on_remove(self) -> None:
        self.remove_clicked.emit(self._file_info.file_id)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._remove_btn.geometry().contains(event.pos()):
                self.preview_clicked.emit(self._file_info.file_id)
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(240, 70)


class FilePreviewList(QWidget):
    file_removed = Signal(str)
    file_preview_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_cards: dict[str, FilePreviewCard] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(8)
        self._main_layout.addStretch()

    def add_file(self, file_info: UploadedFileInfo) -> None:
        if file_info.file_id in self._file_cards:
            return

        card = FilePreviewCard(file_info, self)
        card.remove_clicked.connect(self._on_file_removed)
        card.preview_clicked.connect(self._on_file_preview)
        self._file_cards[file_info.file_id] = card

        self._main_layout.insertWidget(self._main_layout.count() - 1, card)
        self._update_visibility()

    def remove_file(self, file_id: str) -> None:
        if file_id not in self._file_cards:
            return

        card = self._file_cards[file_id]
        self._main_layout.removeWidget(card)
        card.deleteLater()
        del self._file_cards[file_id]
        self._update_visibility()

    def update_file(self, file_info: UploadedFileInfo) -> None:
        if file_info.file_id in self._file_cards:
            self._file_cards[file_info.file_id].update_file_info(file_info)

    def clear_all(self) -> None:
        for file_id in list(self._file_cards.keys()):
            self.remove_file(file_id)

    def get_file_ids(self) -> list[str]:
        return list(self._file_cards.keys())

    def has_files(self) -> bool:
        return len(self._file_cards) > 0

    def file_count(self) -> int:
        return len(self._file_cards)

    def _on_file_removed(self, file_id: str) -> None:
        self.file_removed.emit(file_id)

    def _on_file_preview(self, file_id: str) -> None:
        self.file_preview_requested.emit(file_id)

    def _update_visibility(self) -> None:
        self.setVisible(len(self._file_cards) > 0)