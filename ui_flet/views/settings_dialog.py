"""
Flet 设置对话框

提供应用程序的设置界面，包括：
- 模型配置
- 技能管理
- 语音设置
- 快捷键设置
- 其他设置
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager, get_color
from ui_flet.settings.model_config_page import ModelConfigPage
from ui_flet.settings.skill_management_page import SkillManagementPage
from ui_flet.settings.skill_toggle_page import SkillTogglePage
from ui_flet.settings.voice_settings_page import VoiceSettingsPage
from ui_flet.settings.hotkey_settings_page import HotkeySettingsPage
from ui_flet.settings.scheduled_tasks_page import ScheduledTasksPage
from ui_flet.settings.prompt_template_page import PromptTemplatePage
from ui_flet.settings.live2d_settings_page import Live2DSettingsPage

if TYPE_CHECKING:
    pass


class SettingsDialog:
    """
    设置对话框类

    管理设置对话框的布局和交互，包括：
    - 左侧设置分类导航
    - 右侧设置内容区域
    - 导航切换逻辑
    """

    # 导航栏宽度
    NAV_WIDTH = 200

    # 页面边距（设置页面与窗口边缘的间距）
    PAGE_MARGIN = 40

    # 设置分类
    SETTINGS_CATEGORIES = [
        {"id": "model", "name": "模型配置", "icon": ft.Icons.SETTINGS},
        {"id": "skill_toggle", "name": "Skill开关", "icon": ft.Icons.TOGGLE_ON},
        {"id": "skills", "name": "用户Skill管理", "icon": ft.Icons.EXTENSION},
        {"id": "voice", "name": "语音设置", "icon": ft.Icons.MIC},
        {"id": "shortcuts", "name": "快捷键设置", "icon": ft.Icons.KEYBOARD},
        {"id": "scheduled_tasks", "name": "定时任务", "icon": ft.Icons.SCHEDULE},
        {"id": "prompt_template", "name": "系统提示词", "icon": ft.Icons.TEXT_SNIPPET},
        {"id": "live2d", "name": "2D Live", "icon": ft.Icons.EMOJI_EMOTIONS},
        {"id": "other", "name": "其他设置", "icon": ft.Icons.MORE_HORIZ},
    ]

    def __init__(self, page: ft.Page, on_close: Callable[[], None] | None = None) -> None:
        """
        初始化设置对话框

        Args:
            page: Flet Page 对象
            on_close: 关闭对话框时的回调函数
        """
        self._page = page
        self._logger = get_logger()
        self._on_close_callback = on_close

        # 主题管理
        self._theme_manager = ThemeManager()

        # 当前选中的分类
        self._current_category = "model"

        # 导航项引用
        self._nav_items: dict[str, ft.Container] = {}

        # 内容面板引用
        self._content_panels: dict[str, ft.Control] = {}

        # 内容区域引用（用于动态添加面板）
        self._content_area: ft.Column | None = None

        # 设置页面遮罩容器引用
        self._dialog: ft.Container | None = None

        # 模型配置页面引用
        self._model_config_page: ModelConfigPage | None = None

        # Skill 开关页面引用
        self._skill_toggle_page: SkillTogglePage | None = None

        # 技能管理页面引用
        self._skill_management_page: SkillManagementPage | None = None

        # 语音设置页面引用
        self._voice_settings_page: VoiceSettingsPage | None = None

        # 快捷键设置页面引用
        self._hotkey_settings_page: HotkeySettingsPage | None = None

        # 定时任务页面引用
        self._scheduled_tasks_page: ScheduledTasksPage | None = None

        # 系统提示词页面引用
        self._prompt_template_page: PromptTemplatePage | None = None

        # Live2D 设置页面引用
        self._live2d_settings_page: Live2DSettingsPage | None = None

        # 拖动相关状态
        self._is_dragging = False
        self._dialog_x = 0
        self._dialog_y = 0

        # 内层容器引用（用于拖动）
        self._inner_container: ft.Container | None = None

        # 加载占位符引用
        self._loading_placeholder: ft.Column | None = None

        # 创建对话框外壳（不创建任何页面实例）
        self._build_dialog_shell()

    def _build_dialog_shell(self) -> None:
        """构建对话框外壳（不含页面内容，页面内容将异步加载）"""
        self._logger.info("SettingsDialog: 开始构建对话框外壳")
        colors = self._theme_manager.get_color_scheme()

        # 创建顶部标题栏
        title_bar = self._create_title_bar()

        # 创建左侧导航
        navigation = self._create_navigation()

        # 创建右侧内容区域
        content_area = self._create_content_area()

        # 左右布局容器
        body = ft.Row(
            [
                navigation,
                ft.Container(
                    content=content_area,
                    expand=True,
                    bgcolor=colors.bg_page,
                    padding=10,
                ),
            ],
            spacing=0,
            expand=True,
        )

        # 主容器（占满弹窗内部空间）
        main_container = ft.Column(
            [
                title_bar,
                ft.Container(
                    content=body,
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        )

        # 内层容器（带边距、圆角和阴影，视觉上形成可拉宽拉高的设置页面）
        # 使用 absolute positioning 来支持拖动
        self._inner_container = ft.Container(
            content=main_container,
            width=960,  # 固定宽度（放大 20%）
            height=800,  # 固定高度（放大 20%）
            bgcolor=colors.surface,
            border_radius=12,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color="#00000033",
                offset=ft.Offset(0, 8),
            ),
            # 仅需定义 on_click 即可使 Container 在命中区域内消费点击事件，
            # 阻止点击穿透到下方遮罩层 GestureDetector（Flet 的 Event 对象
            # 没有 stop_propagation 方法，无需也无法调用）。
            on_click=lambda e: None,
        )

        # 使用 Stack 来实现绝对定位
        # 遮罩层使用 GestureDetector 来检测点击（关闭设置页面）
        stack = ft.Stack(
            [
                # 遮罩层（检测点击关闭）
                ft.GestureDetector(
                    content=ft.Container(expand=True),
                    on_tap=self._on_backdrop_click,
                ),
                # 内层容器（可拖动）
                self._inner_container,
            ],
            expand=True,
        )

        # 全屏遮罩容器（随主窗口大小变化自动拉宽拉高）
        self._dialog = ft.Container(
            content=stack,
            expand=True,
            bgcolor="#00000059",
        )
        self._logger.info("SettingsDialog: 对话框外壳构建完成")

    def _create_title_bar(self) -> ft.Container:
        """
        创建标题栏

        Returns:
            标题栏容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 标题
        title = ft.Text(
            "设置",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 关闭按钮
        close_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=colors.text_muted,
            icon_size=16,
            on_click=self._on_close_click,
        )

        # 标题栏内容
        title_content = ft.Row(
            [
                title,
                ft.Container(expand=True),
                close_button,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # 标题栏容器（支持拖动）
        # 使用 GestureDetector 来识别拖动手势
        title_bar = ft.Container(
            content=ft.GestureDetector(
                content=title_content,
                on_pan_start=self._on_title_bar_pan_start,
                on_pan_update=self._on_title_bar_pan_update,
                on_pan_end=self._on_title_bar_pan_end,
                drag_interval=10,  # 拖动更新频率（毫秒）
            ),
            bgcolor=colors.surface,
            padding=10,
            border=ft.Border(
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

        return title_bar

    def _create_navigation(self) -> ft.Container:
        """
        创建左侧导航栏

        Returns:
            导航栏容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 创建导航项
        nav_items = []
        for category in self.SETTINGS_CATEGORIES:
            nav_item = self._create_nav_item(category)
            self._nav_items[category["id"]] = nav_item
            nav_items.append(nav_item)

        # 导航容器
        navigation = ft.Container(
            content=ft.Column(
                nav_items,
                spacing=2,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=self.NAV_WIDTH,
            bgcolor=colors.surface,
            padding=10,
            border=ft.Border(
                right=ft.BorderSide(1, colors.border),
            ),
        )

        return navigation

    def _create_nav_item(self, category: dict) -> ft.Container:
        """
        创建单个导航项

        Args:
            category: 分类信息字典

        Returns:
            导航项容器
        """
        colors = self._theme_manager.get_color_scheme()
        is_selected = category["id"] == self._current_category

        # 图标
        icon = ft.Icon(
            category["icon"],
            size=14,
            color=colors.text if is_selected else colors.text_muted,
        )

        # 文字
        text = ft.Text(
            value=category["name"],
            size=11,
            color=colors.text if is_selected else colors.text_muted,
        )

        # 导航项容器
        nav_item = ft.Container(
            content=ft.Row(
                [
                    icon,
                    text,
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=colors.primary_soft if is_selected else colors.surface,
            border_radius=8,
            padding=10,
            on_click=lambda e, cat_id=category["id"]: self._on_nav_click(cat_id),
            on_hover=lambda e, cat_id=category["id"]: self._on_nav_hover(e, cat_id),
        )

        return nav_item

    def _create_content_area(self) -> ft.Column:
        """
        创建右侧内容区域（初始仅显示加载占位符，默认页面将异步加载）

        Returns:
            内容区域
        """
        colors = self._theme_manager.get_color_scheme()

        # 加载占位符
        self._loading_placeholder = ft.Column([
            ft.Container(height=40),
            ft.ProgressBar(width=200, color=colors.primary),
            ft.Container(height=16),
            ft.Text("加载中...", size=11, color=colors.text_muted, text_align=ft.TextAlign.CENTER),
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

        self._content_area = ft.Column(
            [self._loading_placeholder],
            spacing=0,
            expand=True,
        )

        return self._content_area

    def _show_loading_placeholder(self) -> None:
        """在内容区域显示加载占位符"""
        if not self._content_area or not self._loading_placeholder:
            return
        if self._loading_placeholder not in self._content_area.controls:
            # 隐藏其他面板
            for p in list(self._content_area.controls):
                if p != self._loading_placeholder:
                    p.visible = False
            self._content_area.controls.clear()
            self._content_area.controls.append(self._loading_placeholder)
        self._page.update()

    def _remove_loading_placeholder(self) -> None:
        """从内容区域移除加载占位符"""
        if self._content_area and self._loading_placeholder and self._loading_placeholder in self._content_area.controls:
            self._content_area.controls.remove(self._loading_placeholder)

    async def _async_create_and_load_panel(self, category_id: str) -> None:
        """异步创建内容面板并加载数据"""
        try:
            panel = self._create_content_panel(category_id)
            self._content_panels[category_id] = panel

            # 移除加载占位符并添加实际面板
            self._remove_loading_placeholder()
            if self._content_area:
                self._content_area.controls.append(panel)

            # 异步加载页面数据
            await self._async_load_page_data(category_id)

            # 显示面板
            panel.visible = True
            self._page.update()
        except Exception as e:
            self._logger.exception(f"异步创建面板失败: {e}")

    async def _async_load_page_data(self, category_id: str) -> None:
        """异步加载页面的数据"""
        await asyncio.sleep(0)  # 让出 UI 线程

        if category_id == "model" and self._model_config_page:
            await self._model_config_page.async_load_data()
        elif category_id == "skill_toggle" and self._skill_toggle_page:
            await self._skill_toggle_page.async_load_data()
        elif category_id == "skills" and self._skill_management_page:
            await self._skill_management_page.async_load_data()
        elif category_id == "voice" and self._voice_settings_page:
            await self._voice_settings_page.async_load_data()
        elif category_id == "shortcuts" and self._hotkey_settings_page:
            pass  # 快捷键设置无需异步加载
        elif category_id == "scheduled_tasks" and self._scheduled_tasks_page:
            await self._scheduled_tasks_page.async_load_data()
        elif category_id == "prompt_template" and self._prompt_template_page:
            await self._prompt_template_page.async_load_data()
        elif category_id == "live2d" and self._live2d_settings_page:
            await self._live2d_settings_page.async_load_data()

    def _create_content_panel(self, category_id: str) -> ft.Container:
        """
        创建内容面板

        Args:
            category_id: 分类ID

        Returns:
            内容面板容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 获取分类名称
        category_name = next(
            (c["name"] for c in self.SETTINGS_CATEGORIES if c["id"] == category_id),
            category_id
        )

        # 根据分类创建不同内容
        if category_id == "model":
            # 模型配置页面
            if self._model_config_page is None:
                self._model_config_page = ModelConfigPage(self._page)
            panel_content = self._model_config_page.get_content()
        elif category_id == "skill_toggle":
            # Skill 开关页面
            if self._skill_toggle_page is None:
                self._skill_toggle_page = SkillTogglePage(self._page)
            panel_content = self._skill_toggle_page.build()
        elif category_id == "skills":
            # 技能管理页面
            if self._skill_management_page is None:
                self._skill_management_page = SkillManagementPage(self._page)
            panel_content = self._skill_management_page.build()
        elif category_id == "voice":
            # 语音设置页面
            if self._voice_settings_page is None:
                self._voice_settings_page = VoiceSettingsPage(self._page)
            panel_content = self._voice_settings_page.build()
        elif category_id == "shortcuts":
            # 快捷键设置页面
            if self._hotkey_settings_page is None:
                self._hotkey_settings_page = HotkeySettingsPage(self._page)
            panel_content = self._hotkey_settings_page.build()
        elif category_id == "scheduled_tasks":
            # 定时任务页面
            if self._scheduled_tasks_page is None:
                self._scheduled_tasks_page = ScheduledTasksPage(self._page)
            panel_content = self._scheduled_tasks_page.build()
        elif category_id == "prompt_template":
            # 系统提示词页面
            if self._prompt_template_page is None:
                self._prompt_template_page = PromptTemplatePage(self._page)
            panel_content = self._prompt_template_page.build()
        elif category_id == "live2d":
            # Live2D 设置页面
            if self._live2d_settings_page is None:
                self._live2d_settings_page = Live2DSettingsPage(self._page)
            panel_content = self._live2d_settings_page.build()
        else:
            # 其他分类显示占位内容
            panel_content = ft.Column(
                [
                    ft.Text(
                        category_name,
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=colors.text,
                    ),
                    ft.Container(height=10),
                    ft.Text(
                        f"{category_name}功能正在开发中...",
                        size=11,
                        color=colors.text_muted,
                    ),
                ],
                spacing=0,
            )

        panel = ft.Container(
            content=panel_content,
            visible=False,  # 初始隐藏，通过 _create_content_area 设置当前选中的为可见
            expand=True,
        )

        return panel

    def _on_nav_click(self, category_id: str) -> None:
        """
        导航项点击事件

        Args:
            category_id: 分类ID
        """
        if category_id == self._current_category:
            return

        self._logger.info(f"SettingsDialog: 切换分类到 {category_id}")
        # 更新选中状态
        self._current_category = category_id

        # 刷新导航项样式
        self._update_nav_styles()

        # 切换内容面板
        self._switch_content_panel()

        # 更新页面
        self._page.update()

    def _on_nav_hover(self, e, category_id: str) -> None:
        """
        导航项悬停事件

        Args:
            e: 事件对象
            category_id: 分类ID
        """
        # 悬停效果（通过 CSS 或直接修改属性）
        nav_item = self._nav_items.get(category_id)
        if nav_item and category_id != self._current_category:
            colors = self._theme_manager.get_color_scheme()
            if e.data == "true":
                # 悬停
                nav_item.bgcolor = colors.surface_hover
            else:
                # 离开
                nav_item.bgcolor = colors.surface
            nav_item.update()

    def _update_nav_styles(self) -> None:
        """更新所有导航项的样式"""
        colors = self._theme_manager.get_color_scheme()

        for category_id, nav_item in self._nav_items.items():
            is_selected = category_id == self._current_category

            # 更新背景色
            nav_item.bgcolor = colors.primary_soft if is_selected else colors.surface

            # 更新图标和文字颜色
            if isinstance(nav_item.content, ft.Row):
                for control in nav_item.content.controls:
                    if isinstance(control, ft.Icon):
                        control.color = colors.text if is_selected else colors.text_muted
                    elif isinstance(control, ft.Text):
                        control.color = colors.text if is_selected else colors.text_muted

    def _switch_content_panel(self) -> None:
        """切换内容面板（异步加载）"""
        # 隐藏所有已有面板
        for panel in self._content_panels.values():
            panel.visible = False

        # 面板尚未创建，显示加载占位符并异步创建
        if self._current_category not in self._content_panels:
            self._logger.info(f"SettingsDialog: 异步创建面板 {self._current_category}")
            # 显示加载占位符
            self._show_loading_placeholder()
            # 异步创建并加载面板
            self._page.run_task(self._async_create_and_load_panel, self._current_category)
        else:
            # 面板已存在，确保它在内容区域中并显示
            panel = self._content_panels.get(self._current_category)
            if panel:
                # 移除加载占位符（如果存在）
                self._remove_loading_placeholder()
                # 确保面板在内容区域中
                if panel not in self._content_area.controls:
                    self._content_area.controls.append(panel)
                panel.visible = True
            # 异步重新加载当前面板的数据
            self._page.run_task(self._async_load_page_data, self._current_category)

    def _on_close_click(self, e) -> None:
        """
        关闭按钮点击事件

        Args:
            e: 事件对象
        """
        self.close()

    def _on_backdrop_click(self, e) -> None:
        """点击遮罩层关闭设置页面"""
        self.close()

    def _on_title_bar_pan_start(self, e) -> None:
        """
        标题栏拖动开始事件

        Args:
            e: 事件对象
        """
        self._is_dragging = True
        self._logger.debug(f"拖动开始: local_x={e.local_position.x}, local_y={e.local_position.y}")

    def _on_title_bar_pan_update(self, e) -> None:
        """
        标题栏拖动更新事件

        Args:
            e: 事件对象
        """
        if not self._is_dragging or not self._inner_container:
            return

        # 使用 local_delta.x/y 累加偏移，避免 local_x 因控件移动产生跳变
        self._dialog_x += e.local_delta.x
        self._dialog_y += e.local_delta.y

        # 获取当前窗口大小
        window_width = self._page.window.width or 1200
        window_height = self._page.window.height or 800
        dialog_width = self._inner_container.width
        dialog_height = self._inner_container.height

        max_x = window_width - dialog_width
        max_y = window_height - dialog_height
        self._dialog_x = max(0, min(self._dialog_x, max_x))
        self._dialog_y = max(0, min(self._dialog_y, max_y))

        # 更新 inner_container 的位置
        self._inner_container.left = self._dialog_x
        self._inner_container.top = self._dialog_y
        self._inner_container.update()

        self._logger.debug(f"拖动更新: delta_x={e.local_delta.x}, delta_y={e.local_delta.y}, x={self._dialog_x}, y={self._dialog_y}")

    def _on_title_bar_pan_end(self, e) -> None:
        """
        标题栏拖动结束事件

        Args:
            e: 事件对象
        """
        self._is_dragging = False
        self._logger.debug("拖动结束")

    def is_open(self) -> bool:
        """检查设置对话框是否处于打开状态"""
        return self._dialog is not None and self._dialog in self._page.overlay

    def open(self) -> None:
        """打开设置页面"""
        if self._dialog:
            self._logger.info("SettingsDialog: 打开设置对话框")
            if self._dialog not in self._page.overlay:
                self._page.overlay.append(self._dialog)

            # 计算初始位置（居中显示）
            if self._inner_container:
                window_width = self._page.window.width or 1200
                window_height = self._page.window.height or 800
                dialog_width = self._inner_container.width
                dialog_height = self._inner_container.height

                # 计算居中位置
                self._dialog_x = (window_width - dialog_width) / 2
                self._dialog_y = (window_height - dialog_height) / 2

                # 设置初始位置
                self._inner_container.left = self._dialog_x
                self._inner_container.top = self._dialog_y

                self._logger.debug(f"设置页面初始位置: x={self._dialog_x}, y={self._dialog_y}")

            # 检查默认面板是否已创建，根据情况处理面板显示和数据加载
            if self._current_category not in self._content_panels:
                # 面板未创建：调用 _switch_content_panel() 异步创建面板并加载数据
                self._switch_content_panel()
            else:
                # 面板已创建：确保面板在内容区域中并重新加载数据
                panel = self._content_panels.get(self._current_category)
                if panel and self._content_area:
                    # 移除加载占位符（如果存在）
                    self._remove_loading_placeholder()
                    # 确保面板在内容区域中
                    if panel not in self._content_area.controls:
                        self._content_area.controls.append(panel)
                    panel.visible = True
                # 异步重新加载当前面板的数据
                self._page.run_task(self._async_load_page_data, self._current_category)

            self._page.update()

    def close(self) -> None:
        """关闭设置页面"""
        if self._dialog and self._dialog in self._page.overlay:
            self._logger.info("SettingsDialog: 关闭设置对话框")
            self._page.overlay.remove(self._dialog)
            self._page.update()

            # 调用关闭回调
            if self._on_close_callback:
                try:
                    self._on_close_callback()
                except Exception as e:
                    self._logger.exception(f"SettingsDialog: 关闭回调执行失败: {e}")
