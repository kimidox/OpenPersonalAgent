"""
文件上传区域组件

提供文件上传按钮、文件预览列表和解析进度显示。
基于旧版 PySide6 的 file_upload_area.py 重新实现。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, TYPE_CHECKING

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager, DEFAULT_SPACING_CONFIG
from ui_flet.utils.file_upload_controller import FileUploadController
from ui_flet.utils.file_upload_manager import UploadedFileInfo
from ui_flet.components.file_preview_card import FilePreviewList

if TYPE_CHECKING:
    pass


class FileUploadArea(ft.Container):
    """
    文件上传区域

    功能：
    - 上传按钮
    - 文件预览列表
    - 解析进度条
    - 文件解析状态反馈
    """

    def __init__(
        self,
        page: ft.Page,
        max_files: int = 5,
        on_files_changed: Callable[[list[UploadedFileInfo]], None] | None = None,
        on_upload_error: Callable[[str], None] | None = None,
    ) -> None:
        """
        初始化文件上传区域

        Args:
            page: Flet Page 对象
            max_files: 最大文件数量
            on_files_changed: 文件列表变化回调
            on_upload_error: 上传错误回调
        """
        super().__init__()
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        self._on_files_changed = on_files_changed
        self._on_upload_error = on_upload_error

        # 文件上传控制器
        self._controller = FileUploadController(max_files=max_files)
        self._controller.register_callback("file_added", self._on_file_added)
        self._controller.register_callback("file_removed", self._on_file_removed)
        self._controller.register_callback("file_parse_started", self._on_parse_update)
        self._controller.register_callback("file_parse_finished", self._on_parse_update)
        self._controller.register_callback("file_parse_error", self._on_parse_update)
        self._controller.register_callback("files_changed", self._on_files_changed_internal)
        self._controller.register_callback("upload_error", self._on_upload_error_internal)

        # 文件选择器（Service 控件，注册到 page.services 避免渲染占位）
        self._file_picker = ft.FilePicker()
        self._page.services.append(self._file_picker)

        # UI 引用
        self._upload_button: ft.IconButton | None = None
        self._progress_container: ft.Container | None = None
        self._progress_bar: ft.ProgressBar | None = None
        self._progress_label: ft.Text | None = None
        self._file_preview_list: FilePreviewList | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        """构建UI"""
        colors = self._colors

        # 上传按钮
        self._upload_button = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE,
            icon_color=colors.text_muted,
            tooltip="上传文件",
            on_click=self._on_upload_click,
            width=26,
            height=26,
            icon_size=18,
            padding=0,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: "transparent"},
            ),
        )

        # 解析进度容器
        self._progress_label = ft.Text(
            "正在解析文件...",
            size=11,
            color=colors.text_muted,
        )
        self._progress_bar = ft.ProgressBar(
            value=0,
            height=3,
            color=colors.primary,
            bgcolor=colors.border,
        )
        self._progress_container = ft.Container(
            content=ft.Column(
                [
                    self._progress_label,
                    self._progress_bar,
                ],
                spacing=4,
            ),
            visible=False,
            padding=ft.Padding(
                left=DEFAULT_SPACING_CONFIG.sm,
                top=DEFAULT_SPACING_CONFIG.xs,
                right=DEFAULT_SPACING_CONFIG.sm,
                bottom=DEFAULT_SPACING_CONFIG.xs,
            ),
        )

        # 文件预览列表
        self._file_preview_list = FilePreviewList(
            on_remove=self._on_remove_file,
            on_preview=self._on_preview_file,
        )

        # 主布局
        self.content = ft.Column(
            [
                self._progress_container,
                self._file_preview_list,
            ],
            spacing=DEFAULT_SPACING_CONFIG.xs,
        )
        self.padding = 0

    async def _on_upload_click(self, e: ft.ControlEvent) -> None:
        """上传按钮点击"""
        self._logger.info("FileUploadArea: 打开文件选择对话框")
        if not self._controller.can_add_file():
            self._show_snackbar(f"最多只能上传 {self._controller._max_files} 个文件")
            return

        files = await self._file_picker.pick_files(
            allow_multiple=True,
            allowed_extensions=self._controller.get_supported_extensions(),
            dialog_title="选择文件",
        )
        self._handle_picked_files(files)

    def _handle_picked_files(self, files: list[ft.FilePickerFile] | None) -> None:
        """处理选择的文件"""
        if not files:
            return

        remaining = self._controller.get_remaining_slots()
        files_to_add = files[:remaining]

        if len(files) > remaining:
            self._show_snackbar(
                f"已选择 {len(files)} 个文件，但只能再上传 {remaining} 个"
            )

        for file_info in files_to_add:
            path = Path(file_info.path) if file_info.path else None
            if path:
                self._controller.add_file(path)

        self._page.update()

    def _on_file_added(self, file_info: UploadedFileInfo) -> None:
        """文件添加回调"""
        if self._file_preview_list:
            self._file_preview_list.add_file(file_info)
        self._notify_files_changed()

    def _on_file_removed(self, file_info: UploadedFileInfo) -> None:
        """文件移除回调"""
        if self._file_preview_list:
            self._file_preview_list.remove_file(file_info.file_id)
        self._notify_files_changed()

    def _on_parse_update(self, file_info: UploadedFileInfo) -> None:
        """解析更新回调"""
        if self._file_preview_list:
            self._file_preview_list.update_file(file_info)
        self._update_progress_display()
        self._notify_files_changed()

    def _on_files_changed_internal(self, file_info: UploadedFileInfo | None = None) -> None:
        """文件列表变化内部处理"""
        self._update_progress_display()
        self._notify_files_changed()

    def _on_upload_error_internal(self, message: str) -> None:
        """上传错误内部处理"""
        self._show_snackbar(message, success=False)
        if self._on_upload_error:
            self._on_upload_error(message)

    def _on_remove_file(self, file_id: str) -> None:
        """移除文件"""
        self._controller.remove_file(file_id)

    def _on_preview_file(self, file_id: str) -> None:
        """预览文件"""
        file_info = self._controller.get_file(file_id)
        if not file_info:
            return

        if file_info.is_parsing:
            self._show_message_dialog("文件预览", "文件正在解析中，请稍后再试。")
            return

        if file_info.parse_error:
            self._show_message_dialog("解析失败", file_info.parse_error)
            return

        preview = file_info.content_preview or "无内容预览"
        self._show_message_dialog(
            f"文件预览: {file_info.original_name}",
            preview,
        )

    def _update_progress_display(self) -> None:
        """更新进度显示"""
        if not self._progress_container or not self._progress_bar or not self._progress_label:
            return

        files = self._controller.get_all_files()
        parsing_files = [f for f in files if f.is_parsing]

        if parsing_files:
            self._progress_container.visible = True
            total_progress = sum(f.parse_progress for f in parsing_files) / len(parsing_files)
            self._progress_bar.value = total_progress / 100
            status = parsing_files[0].parse_status or "解析中..."
            self._progress_label.value = f"正在解析文件... ({status})"
        else:
            self._progress_container.visible = False

    def _notify_files_changed(self) -> None:
        """通知外部文件变化"""
        if self._on_files_changed:
            self._on_files_changed(self._controller.get_all_files())

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """显示提示条"""
        try:
            self._page.show_snack_bar(
                ft.SnackBar(
                    content=ft.Text(message),
                    bgcolor=self._colors.success if success else self._colors.error,
                )
            )
        except Exception:
            pass

    def _show_message_dialog(self, title: str, content: str) -> None:
        """显示消息对话框"""
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(content, selectable=True),
            actions=[ft.TextButton("确定", on_click=lambda e: self._close_dialog(dialog))],
        )
        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _close_dialog(self, dialog: ft.AlertDialog) -> None:
        """关闭对话框"""
        dialog.open = False
        self._page.update()

    def get_controller(self) -> FileUploadController:
        """获取文件上传控制器"""
        return self._controller

    def get_upload_button(self) -> ft.IconButton:
        """获取上传按钮控件"""
        return self._upload_button

    def get_files(self) -> list[UploadedFileInfo]:
        """获取当前所有文件"""
        return self._controller.get_all_files()

    def clear(self) -> None:
        """清空所有文件"""
        self._controller.clear_all_files()
        if self._file_preview_list:
            self._file_preview_list.clear()
        self._update_progress_display()

    def has_files(self) -> bool:
        """是否有文件"""
        return self._controller.has_files()

    def can_add_file(self) -> bool:
        """是否还能添加文件"""
        return self._controller.can_add_file()

    def inject_summary_to_message(self, text: str) -> str:
        """将文件摘要注入消息文本"""
        return self._controller.inject_summary_to_message(text)

    def set_vision_enabled(self, enabled: bool) -> list[UploadedFileInfo]:
        """设置视觉能力启用状态

        Args:
            enabled: 是否启用视觉能力

        Returns:
            如果禁用视觉能力且有已上传图片，返回被清除的图片文件列表；
            否则返回空列表。
        """
        removed_files = self._controller.set_vision_enabled(enabled)

        # 更新文件预览列表（清除被移除的图片）
        if removed_files and self._file_preview_list:
            for file_info in removed_files:
                self._file_preview_list.remove_file(file_info.file_id)
            self._logger.info(
                f"FileUploadArea: 视觉能力禁用，已清除 {len(removed_files)} 个图片文件"
            )

        self._update_progress_display()
        self._notify_files_changed()
        return removed_files

    def is_vision_enabled(self) -> bool:
        """获取视觉能力启用状态"""
        return self._controller.is_vision_enabled()
