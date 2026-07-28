"""
输入区域组件

提供消息输入、文件上传和发送功能。
"""
from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING

import flet as ft

from logger import get_logger
from ui_flet.theme import get_color, get_theme_manager, ThemeMode, DEFAULT_SPACING_CONFIG
from ui_flet.utils.file_upload_controller import FileUploadController
from ui_flet.utils.file_upload_manager import UploadedFileInfo
from ui_flet.components.file_upload_area import FileUploadArea

if TYPE_CHECKING:
    pass


# 保持向后兼容的旧版文件信息类
class UploadedFile:
    """已上传文件信息（兼容旧版接口）"""

    def __init__(self, path: str, name: str, size: int):
        self.path = path
        self.name = name
        self.size = size

    def get_size_display(self) -> str:
        """获取文件大小的显示文本"""
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        else:
            return f"{self.size / 1024 / 1024:.1f} MB"


class InputArea:
    """
    输入区域组件

    基于 Flet 的消息输入组件，支持：
    - 多行文本输入
    - Enter 发送，Shift+Enter 换行
    - 文件上传（多文件，含解析状态）
    - 文件预览和删除
    - 发送按钮

    使用方式：
        input_area = InputArea(page)
        input_area.set_on_send(my_send_callback)
        page.add(input_area.get_control())
    """

    # 输入区域尺寸配置
    MIN_INPUT_HEIGHT = 60
    MAX_INPUT_HEIGHT = 120

    def __init__(self, page: ft.Page):
        """
        初始化输入区域

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()

        # 主题
        self._theme_manager = get_theme_manager()
        self._colors = self._theme_manager.get_color_scheme()

        # 文件上传区域（复用独立组件）
        self._file_upload_area = FileUploadArea(
            page=page,
            max_files=5,
            on_files_changed=self._on_files_changed,
            on_upload_error=self._on_upload_error,
        )

        # 事件回调
        self._on_send: Optional[Callable[[str, list[UploadedFileInfo]], None]] = None
        self._on_stop: Optional[Callable[[], None]] = None

        # UI 控件引用
        self._input_field: Optional[ft.TextField] = None
        self._send_button: Optional[ft.IconButton] = None
        self._upload_button: Optional[ft.IconButton] = None
        self._thinking_button: Optional[ft.IconButton] = None
        self._main_container: Optional[ft.Container] = None

        # 思考模式状态
        self._enable_thinking = False

        # 推理运行状态
        self._is_inference_running = False

        # 初始化组件
        self._init_controls()

    def _init_controls(self):
        """初始化所有控件"""
        self._logger.info("InputArea: 初始化控件")
        # 创建输入框（与旧版 PySide6 占位文案一致）
        self._input_field = ft.TextField(
            hint_text="输入业务问题后发送…",
            multiline=True,
            min_lines=1,
            max_lines=4,
            text_style=ft.TextStyle(
                color=self._colors.text,
                size=14,
            ),
            hint_style=ft.TextStyle(
                color=self._colors.text_muted,
                size=14,
            ),
            bgcolor=self._colors.bg_page,
            border_color=self._colors.border,
            focused_border_color=self._colors.primary,
            focused_bgcolor=self._colors.surface,
            border_radius=DEFAULT_SPACING_CONFIG.radius_md,
            content_padding=DEFAULT_SPACING_CONFIG.sm,
            expand=True,
            on_change=self._on_input_change,
        )

        # 使用 FileUploadArea 的上传按钮
        self._upload_button = self._file_upload_area.get_upload_button()

        # 创建思考按钮（漩涡图标，与旧版一致：26x26）
        self._thinking_button = ft.IconButton(
            icon=ft.Icons.CYCLONE,
            icon_color=self._colors.text_muted,
            tooltip="切换思考模式",
            on_click=self._on_thinking_click,
            width=26,
            height=26,
            icon_size=18,
            padding=0,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: "transparent"},
            ),
        )

        # 创建发送按钮（与旧版一致：透明背景 + 蓝色箭头，26x26）
        self._send_button = ft.IconButton(
            icon=ft.Icons.SEND,
            icon_color=self._colors.primary,
            tooltip="发送消息",
            on_click=self._on_send_click,
            width=26,
            height=26,
            icon_size=18,
            padding=0,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: "transparent"},
            ),
        )

        # 创建输入行（输入框 + 上传 + 思考 + 发送，与旧版一致）
        input_row = ft.Row(
            [
                self._input_field,
                self._upload_button,
                self._thinking_button,
                self._send_button,
            ],
            spacing=DEFAULT_SPACING_CONFIG.sm,
            alignment=ft.MainAxisAlignment.END,
        )

        # 创建主容器（与旧版 PySide6 一致：高度自适应，不固定 120px）
        self._main_container = ft.Container(
            content=ft.Column(
                [
                    self._file_upload_area,
                    input_row,
                ],
                spacing=DEFAULT_SPACING_CONFIG.xs,
            ),
            bgcolor=self._colors.surface,
            border=ft.Border(
                top=ft.BorderSide(1, self._colors.border),
            ),
            padding=DEFAULT_SPACING_CONFIG.sm,
        )

    # ==================== 事件处理 ====================

    def _on_input_change(self, e: ft.ControlEvent):
        """输入内容变化"""
        # 可以在这里添加输入状态变化逻辑
        pass

    def _on_upload_error(self, message: str) -> None:
        """上传错误回调"""
        self._show_snackbar(message, success=False)

    def _on_files_changed(self, files: list[UploadedFileInfo]) -> None:
        """文件列表变化回调"""
        try:
            self._page.update()
        except Exception:
            pass

    def _on_send_click(self, e: ft.ControlEvent):
        """发送按钮点击"""
        # 如果正在推理，则停止推理
        if self._is_inference_running:
            self._logger.info("InputArea: 检测到推理运行中，执行停止操作")
            if self._on_stop:
                self._on_stop()
            return

        # 否则发送消息
        self._send_message()

    def _on_thinking_click(self, e: ft.ControlEvent):
        """思考按钮点击：切换思考模式"""
        self._enable_thinking = not self._enable_thinking
        self._update_thinking_button_style()
        self._logger.info(f"InputArea: 思考模式 {'开启' if self._enable_thinking else '关闭'}")
        self._page.update()

    def _update_thinking_button_style(self):
        """更新思考按钮样式（与旧版一致：开启时蓝底蓝框蓝字）"""
        if self._thinking_button:
            if self._enable_thinking:
                self._thinking_button.icon_color = self._colors.primary
                self._thinking_button.tooltip = "思考模式已开启"
                self._thinking_button.style = ft.ButtonStyle(
                    bgcolor=self._colors.primary_soft,
                    side=ft.BorderSide(1, self._colors.primary_border),
                    shape=ft.RoundedRectangleBorder(radius=4),
                )
            else:
                self._thinking_button.icon_color = self._colors.text_muted
                self._thinking_button.tooltip = "切换思考模式"
                self._thinking_button.style = ft.ButtonStyle(
                    bgcolor="transparent",
                    side=ft.BorderSide(1, self._colors.border),
                    shape=ft.RoundedRectangleBorder(radius=4),
                )

    # ==================== 核心方法 ====================

    def _send_message(self):
        """发送消息"""
        if not self._input_field:
            return

        text = (self._input_field.value or "").strip()
        if not text and not self._file_upload_area.has_files():
            return

        self._logger.info(f"InputArea: 发送消息: {text[:50] if text else ''}...")

        # 获取文件列表
        files = self._file_upload_area.get_files()

        # 调用回调（文件内容由 main_window 嵌入系统提示词，不注入用户消息）
        if self._on_send:
            self._on_send(text, files)

        # 清空输入和文件
        self._input_field.value = ""
        self._file_upload_area.clear()

        # 设置推理状态为运行中
        self.set_inference_running(True)

        self._page.update()

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """显示提示消息"""
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=self._colors.text_on_primary),
            bgcolor=self._colors.success if success else self._colors.error,
        )
        self._page.snack_bar.open = True
        self._page.update()

    # ==================== 公共方法 ====================

    def get_control(self) -> ft.Control:
        """
        获取输入区域控件

        Returns:
            ft.Control: 输入区域容器控件
        """
        return self._main_container

    def attach_to_page(self) -> None:
        """确保文件选择器已注册到页面（供外部延迟调用）"""
        # FileUploadArea 已在初始化时注册 FilePicker
        pass

    def set_on_send(self, callback: Callable[[str, list[UploadedFileInfo]], None]):
        """
        设置发送回调函数

        Args:
            callback: 回调函数，接收 (text, files) 参数
        """
        self._on_send = callback

    def set_on_stop(self, callback: Callable[[], None]):
        """
        设置停止回调函数

        Args:
            callback: 回调函数，用于停止推理
        """
        self._on_stop = callback

    def send_message(self):
        """公共方法：发送当前输入框中的消息（供快捷键调用）"""
        self._send_message()

    def insert_newline(self):
        """在输入框当前光标位置插入换行符"""
        if not self._input_field:
            return
        current = self._input_field.value or ""
        self._input_field.value = current + "\n"
        try:
            self._input_field.update()
        except Exception:
            pass

    def clear(self):
        """清空输入框和文件"""
        self._logger.info("InputArea: 清空输入")
        if self._input_field:
            self._input_field.value = ""
        self._file_upload_area.clear()
        self._page.update()

    def set_placeholder(self, text: str):
        """
        设置输入框占位文本

        Args:
            text: 占位文本
        """
        if self._input_field:
            self._input_field.hint_text = text
            self._page.update()

    def focus(self):
        """聚焦到输入框"""
        if self._input_field:
            self._input_field.focus()
            self._page.update()

    def is_thinking_enabled(self) -> bool:
        """是否启用了思考模式"""
        return self._enable_thinking

    def set_vision_enabled(self, enabled: bool) -> list[UploadedFileInfo]:
        """设置视觉能力启用状态

        Args:
            enabled: 是否启用视觉能力

        Returns:
            如果禁用视觉能力且有已上传图片，返回被清除的图片文件列表；
            否则返回空列表。
        """
        if self._file_upload_area:
            return self._file_upload_area.set_vision_enabled(enabled)
        return []

    def is_vision_enabled(self) -> bool:
        """获取视觉能力启用状态"""
        if self._file_upload_area:
            return self._file_upload_area.is_vision_enabled()
        return True

    def set_inference_running(self, running: bool) -> None:
        """
        设置推理运行状态

        Args:
            running: 是否正在推理
        """
        if self._is_inference_running == running:
            return

        self._is_inference_running = running
        self._update_send_button_style()
        self._logger.info(f"InputArea: 推理状态 {'运行中' if running else '已停止'}")

        try:
            self._page.update()
        except Exception:
            pass

    def _update_send_button_style(self) -> None:
        """更新发送按钮样式"""
        if not self._send_button:
            return

        if self._is_inference_running:
            # 推理中：显示红色方块（停止图标）
            self._send_button.icon = ft.Icons.STOP
            self._send_button.icon_color = ft.Colors.WHITE
            self._send_button.tooltip = "正在推理..."
            self._send_button.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.RED},
                shape=ft.RoundedRectangleBorder(radius=2),  # 接近方块的圆角
            )
        else:
            # 正常状态：显示发送箭头
            self._send_button.icon = ft.Icons.SEND
            self._send_button.icon_color = self._colors.primary
            self._send_button.tooltip = "发送消息"
            self._send_button.style = ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: "transparent"},
            )

    def update_theme(self):
        """更新主题"""
        self._colors = self._theme_manager.get_color_scheme()

        # 更新输入框样式
        if self._input_field:
            self._input_field.text_style = ft.TextStyle(color=self._colors.text)
            self._input_field.hint_style = ft.TextStyle(color=self._colors.text_muted)
            self._input_field.bgcolor = self._colors.bg_page
            self._input_field.border_color = self._colors.border
            self._input_field.focused_border_color = self._colors.primary

        # 更新按钮样式
        if self._upload_button:
            self._upload_button.icon_color = self._colors.text_muted

        self._update_thinking_button_style()

        # 更新发送按钮样式（根据当前推理状态）
        self._update_send_button_style()

        # 更新容器样式
        if self._main_container:
            self._main_container.bgcolor = self._colors.surface
            self._main_container.border = ft.Border(
                top=ft.BorderSide(1, self._colors.border)
            )

        self._page.update()
