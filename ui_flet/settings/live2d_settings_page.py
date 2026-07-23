"""
Flet Live2D 悬浮球配置页面

提供 Live2D 模型的配置界面：
- 启用/禁用 Live2D 悬浮球
- 选择 Live2D 模型
- 设置悬浮球尺寸
- 查看模型目录说明
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import flet as ft

import config
from config import get_config, set_config
from logger import get_logger
from ui_flet.theme import ThemeManager
from ui_flet.live2d_model_manager import Live2DModelInfo, scan_models

if TYPE_CHECKING:
    pass


class Live2DSettingsPage:
    """
    Live2D 悬浮球配置页面

    提供 Live2D 视觉表现形式的配置功能，包括：
    - 启用/禁用 Live2D 模式
    - 扫描并选择 Live2D 模型
    - 调整悬浮球宽度和高度
    """

    def __init__(self, page: ft.Page) -> None:
        """
        初始化 Live2D 设置页面

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # UI 组件引用
        self._enable_switch: Optional[ft.Switch] = None
        self._model_dropdown: Optional[ft.Dropdown] = None
        self._model_info_text: Optional[ft.Text] = None
        self._width_field: Optional[ft.TextField] = None
        self._height_field: Optional[ft.TextField] = None
        self._status_text: Optional[ft.Text] = None

        # 模型数据
        self._models: list[Live2DModelInfo] = []

        # 主容器
        self._container: Optional[ft.Container] = None

    def build(self) -> ft.Container:
        """
        构建页面 UI

        Returns:
            页面容器
        """
        self._logger.info("Live2DSettingsPage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 标题
        title = ft.Text(
            "2D Live 悬浮球配置",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 说明文字
        info_text = ft.Text(
            "配置 Live2D 模型作为悬浮球的视觉表现形式。模型文件应放置在 PersonalData/2DLiveFiles 目录下，"
            "支持 Live2D Cubism 3/4 格式（.model3.json）。",
            size=10,
            color=colors.text_muted,
        )

        # 启用设置
        enable_section = self._build_enable_section()

        # 模型选择
        model_section = self._build_model_section()

        # 尺寸设置
        size_section = self._build_size_section()

        # 目录说明
        dir_section = self._build_dir_section()

        # 状态文本
        self._status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        # 主内容
        content = ft.Column(
            [
                title,
                ft.Container(height=10),
                info_text,
                ft.Container(height=14),
                enable_section,
                ft.Container(height=14),
                model_section,
                ft.Container(height=14),
                size_section,
                ft.Container(height=14),
                dir_section,
                ft.Container(height=14),
                self._status_text,
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self._container = ft.Container(
            content=content,
            padding=20,
        )

        # 加载模型列表
        self._refresh_model_list()

        self._logger.info("Live2DSettingsPage: 页面构建完成")
        return self._container

    def _build_enable_section(self) -> ft.Container:
        """构建启用设置区域"""
        colors = self._theme_manager.get_color_scheme()

        self._enable_switch = ft.Switch(
            label="启用 Live2D 悬浮球模式（替代传统纯色按钮）",
            value=config.LIVE2D_ENABLED,
            on_change=self._on_enable_changed,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("启用设置", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=8),
                    self._enable_switch,
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

    def _build_model_section(self) -> ft.Container:
        """构建模型选择区域"""
        colors = self._theme_manager.get_color_scheme()

        self._model_dropdown = ft.Dropdown(
            label="选择模型",
            label_style=ft.TextStyle(size=11),
            hint_text="扫描后选择模型",
            hint_style=ft.TextStyle(size=10),
            text_size=11,
            width=480,
            on_select=self._on_model_selected,
        )

        refresh_btn = ft.ElevatedButton(
            "刷新模型列表",
            icon=ft.Icons.REFRESH,
            on_click=self._on_refresh_click,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        load_btn = ft.ElevatedButton(
            "加载模型",
            icon=ft.Icons.DOWNLOAD,
            on_click=self._on_load_click,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        self._model_info_text = ft.Text(
            "",
            size=11,
            color=colors.text_muted,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("模型选择", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=10),
                    ft.Row(
                        [self._model_dropdown, refresh_btn, load_btn],
                        spacing=10,
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=10),
                    self._model_info_text,
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

    def _build_size_section(self) -> ft.Container:
        """构建尺寸设置区域"""
        colors = self._theme_manager.get_color_scheme()

        width = config.LIVE2D_BALL_WIDTH
        height = config.LIVE2D_BALL_HEIGHT

        self._width_field = ft.TextField(
            label="宽度（像素）",
            label_style=ft.TextStyle(size=11),
            value=str(width),
            width=240,
            text_size=11,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_size_changed,
        )

        self._height_field = ft.TextField(
            label="高度（像素）",
            label_style=ft.TextStyle(size=11),
            value=str(height),
            width=240,
            text_size=11,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_size_changed,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("悬浮球尺寸", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=10),
                    ft.Row(
                        [self._width_field, self._height_field],
                        spacing=24,
                    ),
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

    def _build_dir_section(self) -> ft.Container:
        """构建模型目录说明区域"""
        colors = self._theme_manager.get_color_scheme()

        dir_info = ft.Text(
            "Live2D 模型应放置在 PersonalData/2DLiveFiles 目录下。\n"
            "每个模型应放在独立的子目录中，目录结构如下：\n\n"
            "PersonalData/2DLiveFiles/\n"
            "├── model_name_1/\n"
            "│   ├── model.model3.json\n"
            "│   ├── model.moc3\n"
            "│   ├── textures/\n"
            "│   │   └── texture_00.png\n"
            "│   └── motions/\n"
            "│       └── idle.motion3.json\n"
            "└── model_name_2/\n"
            "    └── ...\n\n"
            "支持的格式：Live2D Cubism 3/4（.model3.json）",
            size=10,
            color=colors.text_muted,
            font_family="Consolas, Monaco, monospace",
            selectable=True,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("模型目录说明", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=10),
                    dir_info,
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

    def _refresh_model_list(self) -> None:
        """刷新模型列表"""
        try:
            self._models = scan_models()
        except Exception as e:
            self._logger.exception("扫描 Live2D 模型失败")
            self._models = []
            self._show_status(f"扫描模型失败: {e}", success=False)

        options = []
        current_model_name = config.LIVE2D_MODEL_NAME
        selected_value = None

        for model in self._models:
            value = model.model_dir.name
            display = f"{model.name} ({value})"
            options.append(ft.dropdown.Option(value, display))
            if current_model_name and (current_model_name == value or current_model_name == model.name):
                selected_value = value

        if not options:
            options.append(ft.dropdown.Option("", "未找到可用模型"))

        if self._model_dropdown:
            self._model_dropdown.options = options
            self._model_dropdown.value = selected_value

        self._update_model_info()

    def _update_model_info(self) -> None:
        """更新模型信息显示"""
        if not self._model_dropdown or not self._model_info_text:
            return

        value = self._model_dropdown.value
        if not value:
            self._model_info_text.value = "请选择一个 Live2D 模型。"
            return

        for model in self._models:
            if model.model_dir.name == value:
                info = (
                    f"名称: {model.name}\n"
                    f"目录: {model.model_dir.name}\n"
                    f"动作组: {', '.join(model.available_motions) if model.available_motions else '无'}\n"
                    f"物理效果: {'有' if model.has_physics else '无'}"
                )
                self._model_info_text.value = info
                return

        self._model_info_text.value = ""

    def _on_enable_changed(self, e) -> None:
        """启用状态变化"""
        enabled = bool(e.control.value)
        set_config("LIVE2D_ENABLED", "true" if enabled else "false")
        config.LIVE2D_ENABLED = enabled
        self._logger.info(f"Live2D 启用状态: {enabled}")
        self._show_status("启用设置已保存", success=True)

    def _on_refresh_click(self, e) -> None:
        """刷新模型列表按钮"""
        self._refresh_model_list()
        self._show_status(f"已刷新模型列表，共 {len(self._models)} 个模型", success=True)

    def _on_load_click(self, e) -> None:
        """加载模型按钮"""
        if not self._model_dropdown:
            return

        value = self._model_dropdown.value
        if not value or value == "":
            self._show_status("请先选择一个模型", success=False)
            return

        set_config("LIVE2D_MODEL_NAME", value)
        config.LIVE2D_MODEL_NAME = value
        self._logger.info(f"Live2D 模型已选择: {value}")
        self._show_status(f"模型已选择: {value}，重启后生效", success=True)

    def _on_model_selected(self, e) -> None:
        """模型下拉框选择事件"""
        self._update_model_info()

    def _on_size_changed(self, e) -> None:
        """尺寸变化事件"""
        if not self._width_field or not self._height_field:
            return

        try:
            width = int(self._width_field.value or "0")
            height = int(self._height_field.value or "0")
        except ValueError:
            return

        if width < 50 or width > 500 or height < 50 or height > 500:
            return

        set_config("LIVE2D_BALL_WIDTH", str(width))
        set_config("LIVE2D_BALL_HEIGHT", str(height))
        config.LIVE2D_BALL_WIDTH = width
        config.LIVE2D_BALL_HEIGHT = height
        self._logger.info(f"Live2D 尺寸已更新: {width}x{height}")

    def _show_status(self, message: str, success: bool = True) -> None:
        """显示状态信息"""
        if self._status_text:
            colors = self._theme_manager.get_color_scheme()
            self._status_text.value = message
            self._status_text.color = colors.success if success else colors.error
