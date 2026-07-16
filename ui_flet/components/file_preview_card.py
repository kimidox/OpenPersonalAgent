"""
文件预览卡片组件

提供已上传文件的预览卡片，支持显示文件图标、名称、大小、解析状态和删除操作。
基于旧版 PySide6 的 file_preview_card.py 重新实现。
"""
from __future__ import annotations

from typing import Callable

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager
from ui_flet.utils.file_upload_manager import UploadedFileInfo


def get_file_icon(extension: str) -> str:
    """根据扩展名获取文件图标"""
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


def truncate_filename(name: str, max_length: int = 24) -> str:
    """截断文件名，超出长度时显示省略号"""
    if len(name) <= max_length:
        return name
    return name[:max_length - 3] + "..."


class FilePreviewCard(ft.Container):
    """
    文件预览卡片

    显示单个上传文件的信息，包括：
    - 文件类型图标
    - 文件名（带省略号）
    - 文件大小
    - 解析状态/进度
    - 删除按钮（可选）
    """

    def __init__(
        self,
        file_info: UploadedFileInfo,
        on_remove: Callable[[str], None] | None = None,
        on_preview: Callable[[str], None] | None = None,
        is_read_only: bool = False,
    ) -> None:
        """
        初始化文件预览卡片

        Args:
            file_info: 文件信息
            on_remove: 删除回调
            on_preview: 预览回调
            is_read_only: 是否只读（隐藏删除按钮）
        """
        super().__init__()
        self._logger = get_logger()
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        self._file_info = file_info
        self._on_remove = on_remove
        self._on_preview = on_preview
        self._is_read_only = is_read_only

        self._status_text: ft.Text | None = None
        self._progress_bar: ft.ProgressBar | None = None
        self._name_text: ft.Text | None = None

        self._build_ui()
        self._update_display()

    def _build_ui(self) -> None:
        """构建UI"""
        colors = self._colors

        # 文件图标
        icon_text = ft.Text(
            get_file_icon(self._file_info.extension),
            size=20,
            text_align=ft.TextAlign.CENTER,
            width=28,
            height=28,
        )

        # 文件名
        self._name_text = ft.Text(
            truncate_filename(self._file_info.original_name),
            size=12,
            weight=ft.FontWeight.W_500,
            color=colors.text,
            tooltip=self._file_info.original_name,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=140,
        )

        # 文件大小
        size_text = ft.Text(
            self._file_info.get_file_size_display(),
            size=11,
            color=colors.text_muted,
        )

        # 解析状态
        self._status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        # 进度条
        self._progress_bar = ft.ProgressBar(
            value=0,
            height=3,
            color=colors.primary,
            bgcolor=colors.border,
            visible=False,
        )

        # 信息列
        info_column = ft.Column(
            [
                self._name_text,
                ft.Row(
                    [size_text, self._status_text],
                    spacing=8,
                ),
                self._progress_bar,
            ],
            spacing=2,
            expand=True,
        )

        # 删除按钮
        controls: list[ft.Control] = [icon_text, info_column]
        if not self._is_read_only:
            remove_button = ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=14,
                icon_color=colors.text_muted,
                tooltip="移除",
                on_click=self._on_remove_click,
                width=20,
                height=20,
                padding=0,
                style=ft.ButtonStyle(
                    bgcolor={ft.ControlState.HOVERED: colors.error_soft},
                    icon_color={ft.ControlState.HOVERED: colors.error},
                ),
            )
            controls.append(remove_button)

        # 主布局
        row = ft.Row(
            controls,
            spacing=8,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.content = row
        self.bgcolor = colors.bg_page
        self.padding = 8
        self.border_radius = 8
        self.border = ft.Border(
            left=ft.BorderSide(1, colors.border),
            top=ft.BorderSide(1, colors.border),
            right=ft.BorderSide(1, colors.border),
            bottom=ft.BorderSide(1, colors.border),
        )
        self.width = 240
        self.height = 64
        self.animate = ft.animation.Animation(150, ft.AnimationCurve.EASE_OUT)

        if not self._is_read_only:
            self.on_hover = self._on_hover
            self.on_click = self._on_preview_click
            self.mouse_cursor = ft.MouseCursor.CLICK

    def _on_hover(self, e: ft.ControlEvent) -> None:
        """悬停效果"""
        if e.data == "true":
            self.bgcolor = self._colors.surface
            self.border = ft.Border(
                left=ft.BorderSide(1, self._colors.border_hover or self._colors.border),
                top=ft.BorderSide(1, self._colors.border_hover or self._colors.border),
                right=ft.BorderSide(1, self._colors.border_hover or self._colors.border),
                bottom=ft.BorderSide(1, self._colors.border_hover or self._colors.border),
            )
        else:
            self.bgcolor = self._colors.bg_page
            self.border = ft.Border(
                left=ft.BorderSide(1, self._colors.border),
                top=ft.BorderSide(1, self._colors.border),
                right=ft.BorderSide(1, self._colors.border),
                bottom=ft.BorderSide(1, self._colors.border),
            )
        self.update()

    def _on_remove_click(self, e: ft.ControlEvent) -> None:
        """删除按钮点击"""
        e.stop_propagation()
        if self._on_remove:
            self._on_remove(self._file_info.file_id)

    def _on_preview_click(self, e: ft.ControlEvent) -> None:
        """卡片点击预览"""
        if self._on_preview:
            self._on_preview(self._file_info.file_id)

    def _update_display(self) -> None:
        """更新显示状态"""
        if not self._status_text or not self._progress_bar:
            return

        if self._file_info.is_parsing:
            self._progress_bar.visible = True
            self._progress_bar.value = max(0.05, self._file_info.parse_progress / 100)
            self._status_text.value = self._file_info.parse_status or "解析中..."
            self._status_text.color = self._colors.primary
        elif self._file_info.is_success:
            self._progress_bar.visible = False
            self._status_text.value = "已解析"
            self._status_text.color = self._colors.success
        elif self._file_info.parse_error:
            self._progress_bar.visible = False
            self._status_text.value = "解析失败"
            self._status_text.color = self._colors.error
        else:
            self._progress_bar.visible = False
            self._status_text.value = "待解析"
            self._status_text.color = self._colors.text_muted

    def update_file_info(self, file_info: UploadedFileInfo) -> None:
        """更新文件信息并刷新显示"""
        self._file_info = file_info
        self._update_display()
        try:
            if self.page:
                self.update()
        except RuntimeError:
            pass

    def get_file_id(self) -> str:
        """获取文件ID"""
        return self._file_info.file_id


class FilePreviewList(ft.Container):
    """
    文件预览列表

    横向排列多个 FilePreviewCard。
    """

    def __init__(
        self,
        on_remove: Callable[[str], None] | None = None,
        on_preview: Callable[[str], None] | None = None,
        is_read_only: bool = False,
    ) -> None:
        """
        初始化文件预览列表

        Args:
            on_remove: 删除回调
            on_preview: 预览回调
            is_read_only: 是否只读
        """
        super().__init__()
        self._logger = get_logger()
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        self._on_remove = on_remove
        self._on_preview = on_preview
        self._is_read_only = is_read_only
        self._cards: dict[str, FilePreviewCard] = {}

        self._row = ft.Row(
            [],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )
        self.content = self._row
        self.visible = False

    def add_file(self, file_info: UploadedFileInfo) -> None:
        """添加文件卡片"""
        if file_info.file_id in self._cards:
            self._cards[file_info.file_id].update_file_info(file_info)
            return

        card = FilePreviewCard(
            file_info=file_info,
            on_remove=self._on_remove,
            on_preview=self._on_preview,
            is_read_only=self._is_read_only,
        )
        self._cards[file_info.file_id] = card
        self._row.controls.append(card)
        self.visible = True
        self._safe_update()

    def remove_file(self, file_id: str) -> bool:
        """移除文件卡片"""
        card = self._cards.pop(file_id, None)
        if card is None:
            return False
        self._row.controls.remove(card)
        if not self._cards:
            self.visible = False
        self._safe_update()
        return True

    def update_file(self, file_info: UploadedFileInfo) -> None:
        """更新文件卡片"""
        card = self._cards.get(file_info.file_id)
        if card:
            card.update_file_info(file_info)

    def clear(self) -> None:
        """清空所有卡片"""
        self._cards.clear()
        self._row.controls.clear()
        self.visible = False
        self._safe_update()

    def _safe_update(self) -> None:
        """安全更新控件（未挂载到页面时忽略）"""
        try:
            if self.page:
                self.update()
        except RuntimeError:
            pass

    def has_files(self) -> bool:
        """是否有文件"""
        return len(self._cards) > 0

    def get_file_count(self) -> int:
        """获取文件数量"""
        return len(self._cards)
