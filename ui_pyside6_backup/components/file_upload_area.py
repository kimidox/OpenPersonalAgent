from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.styles.style_manager import StyleManager
from ui.utils.file_upload_controller import FileUploadController
from ui.utils.file_upload_manager import UploadedFileInfo
from ui.components.file_preview_card import FilePreviewList

if TYPE_CHECKING:
    pass


class FileUploadArea(QWidget):
    files_uploaded = Signal()
    files_cleared = Signal()
    upload_error_occurred = Signal(str)

    def __init__(
        self,
        upload_controller: FileUploadController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = upload_controller
        self.setObjectName("skillAgentFileUploadArea")
        self._setup_ui()
        self._connect_signals()
        self._apply_style()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("file_upload_area")
        if style:
            self.setStyleSheet(style)
        else:
            self.setStyleSheet("""
                QWidget#skillAgentFileUploadArea {
                    background-color: transparent;
                }
                QToolButton#skillAgentFileUploadButton {
                    background-color: transparent;
                    color: #6b7280;
                    border: none;
                    border-radius: 13px;
                    font-size: 16px;
                    padding: 0;
                }
                QToolButton#skillAgentFileUploadButton:hover {
                    background-color: #f3f4f6;
                    color: #2563eb;
                }
                QToolButton#skillAgentFileUploadButton:pressed {
                    background-color: #e5e7eb;
                }
            """)

    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(4)

        self._progress_container = QWidget()
        self._progress_container.setVisible(False)
        self._progress_layout = QHBoxLayout(self._progress_container)
        self._progress_layout.setContentsMargins(8, 4, 8, 4)
        self._progress_layout.setSpacing(8)

        self._progress_label = QLabel("正在解析文件...")
        self._progress_label.setStyleSheet("font-size: 9pt; color: #6b7280;")
        self._progress_layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("skillAgentFileParseProgress")
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        progress_style = StyleManager.get_style("file_parse_progress_bar")
        if progress_style:
            self._progress_bar.setStyleSheet(progress_style)
        else:
            self._progress_bar.setStyleSheet("""
                QProgressBar#skillAgentFileParseProgress {
                    background-color: #e5e7eb;
                    border: none;
                    border-radius: 2px;
                }
                QProgressBar#skillAgentFileParseProgress::chunk {
                    background-color: #2563eb;
                    border-radius: 2px;
                }
            """)
        self._progress_layout.addWidget(self._progress_bar, stretch=1)

        self._main_layout.addWidget(self._progress_container)

        self._file_list = FilePreviewList(self)
        self._file_list.file_removed.connect(self._on_file_removed)
        self._file_list.file_preview_requested.connect(self._on_file_preview)
        self._file_list.setVisible(False)
        self._main_layout.addWidget(self._file_list)

    def _connect_signals(self) -> None:
        self._controller.file_added.connect(self._on_file_added)
        self._controller.file_removed.connect(self._on_file_removed_from_controller)
        self._controller.file_parse_started.connect(self._on_parse_started)
        self._controller.file_parse_finished.connect(self._on_parse_finished)
        self._controller.file_parse_error.connect(self._on_parse_error)
        self._controller.upload_error.connect(self._show_upload_error)

    def create_upload_button(self) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("skillAgentFileUploadButton")
        btn.setText("📎")
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_upload_clicked)
        
        style = StyleManager.get_style("file_upload_button")
        if style:
            btn.setStyleSheet(style)
        else:
            btn.setStyleSheet("""
                QToolButton#skillAgentFileUploadButton {
                    background-color: transparent;
                    color: #6b7280;
                    border: none;
                    border-radius: 13px;
                    font-size: 16px;
                    padding: 0;
                }
                QToolButton#skillAgentFileUploadButton:hover {
                    background-color: #f3f4f6;
                    color: #2563eb;
                }
            """)
        
        return btn

    def _on_upload_clicked(self) -> None:
        if not self._controller.can_add_file():
            max_files = self._controller._max_files
            QMessageBox.information(
                self,
                "提示",
                f"最多只能上传 {max_files} 个文件",
            )
            return

        filter_str = self._controller.get_file_filter()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要上传的文件",
            "",
            filter_str,
        )

        if not file_paths:
            return

        remaining_slots = self._controller._max_files - self._controller.file_count()
        files_to_add = file_paths[:remaining_slots]

        if len(file_paths) > remaining_slots:
            QMessageBox.information(
                self,
                "提示",
                f"已选择 {len(file_paths)} 个文件，但只能再上传 {remaining_slots} 个",
            )

        for path_str in files_to_add:
            path = Path(path_str)
            self._controller.add_file(path)

    def _on_file_added(self, file_info: UploadedFileInfo) -> None:
        self._file_list.add_file(file_info)
        self._file_list.setVisible(True)
        self.files_uploaded.emit()

    def _on_file_removed_from_controller(self, file_id: str) -> None:
        self._file_list.remove_file(file_id)
        if not self._controller.has_files():
            self._file_list.setVisible(False)
            self.files_cleared.emit()

    def _on_file_removed(self, file_id: str) -> None:
        self._controller.remove_file(file_id)

    def _on_file_preview(self, file_id: str) -> None:
        file_info = self._controller.get_file(file_id)
        if not file_info:
            return

        if file_info.is_success and file_info.parse_result:
            content = file_info.parse_result.content or ""
            preview_len = 500
            preview = content[:preview_len] + "..." if len(content) > preview_len else content
            
            QMessageBox.information(
                self,
                f"文件预览: {file_info.original_name}",
                preview,
            )
        elif file_info.parse_error:
            QMessageBox.warning(
                self,
                f"解析错误: {file_info.original_name}",
                file_info.parse_error,
            )
        else:
            QMessageBox.information(
                self,
                f"文件: {file_info.original_name}",
                "文件正在解析中...",
            )

    def _on_parse_started(self, file_id: str) -> None:
        self._update_progress_display()
        self._progress_container.setVisible(True)

    def _on_parse_finished(self, file_id: str, result) -> None:
        file_info = self._controller.get_file(file_id)
        if file_info:
            self._file_list.update_file(file_info)
        self._update_progress_display()

    def _on_parse_error(self, file_id: str, error: str) -> None:
        file_info = self._controller.get_file(file_id)
        if file_info:
            self._file_list.update_file(file_info)
        self._update_progress_display()
        self._show_parse_error(file_id, error)

    def _update_progress_display(self) -> None:
        parsing_count = sum(1 for f in self._controller.get_all_files() if f.is_parsing)
        
        if parsing_count > 0:
            self._progress_container.setVisible(True)
            self._progress_label.setText(f"正在解析 {parsing_count} 个文件...")
            total_files = self._controller.file_count()
            parsed_count = sum(1 for f in self._controller.get_all_files() if f.is_parsed)
            progress = int((parsed_count / total_files) * 100) if total_files > 0 else 0
            self._progress_bar.setValue(progress)
        else:
            self._progress_container.setVisible(False)

    def _show_upload_error(self, error: str) -> None:
        self.upload_error_occurred.emit(error)
        QMessageBox.warning(self, "上传错误", error)

    def _show_parse_error(self, file_id: str, error: str) -> None:
        file_info = self._controller.get_file(file_id)
        if file_info:
            QMessageBox.warning(
                self,
                "解析错误",
                f"文件 {file_info.original_name} 解析失败:\n{error}",
            )

    def get_controller(self) -> FileUploadController:
        return self._controller

    def clear_files(self) -> None:
        self._controller.clear_all_files()

    def has_files(self) -> bool:
        return self._controller.has_files()

    def get_parsed_files_count(self) -> int:
        return len(self._controller.get_parsed_files())