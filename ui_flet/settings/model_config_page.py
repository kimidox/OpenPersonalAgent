"""
Flet 模型配置页面

提供模型配置的管理界面，包括：
- 多模型配置列表
- 模型参数编辑
- 配置导入/导出
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import TYPE_CHECKING, Optional

import flet as ft
from click import style

from llm.llm_config_manager import (
    LLMConfigItem,
    MultiLLMConfig,
    add_config,
    delete_config,
    generate_config_id,
    get_active_config_item,
    get_current_multi_config,
    is_auto_switch_enabled,
    list_configs,
    set_active_config,
    set_multi_config,
    update_config,
)
from logger import get_logger
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    pass


class ModelConfigPage:
    """
    模型配置页面

    管理模型配置的界面，包括：
    - 左侧模型列表
    - 右侧配置编辑表单
    - 添加/编辑/删除/切换功能
    - 导入/导出功能
    """

    def __init__(self, page: ft.Page) -> None:
        """
        初始化模型配置页面

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # 当前选中的配置ID
        self._selected_config_id: Optional[str] = None

        # UI组件引用
        self._config_list_column: Optional[ft.Column] = None
        self._config_form: Optional[ft.Container] = None

        # 表单字段
        self._name_field: Optional[ft.TextField] = None
        self._model_name_field: Optional[ft.TextField] = None
        self._api_key_field: Optional[ft.TextField] = None
        self._base_url_field: Optional[ft.TextField] = None
        self._temperature_field: Optional[ft.TextField] = None
        self._top_p_field: Optional[ft.TextField] = None
        self._frequency_penalty_field: Optional[ft.TextField] = None

        # 能力开关控件
        self._enable_vision_switch: Optional[ft.Switch] = None
        self._enable_deep_thinking_switch: Optional[ft.Switch] = None
        self._enable_tool_call_switch: Optional[ft.Switch] = None

        # 文件选择器
        self._file_picker: Optional[ft.FilePicker] = None

        # 状态栏和自动切换控件引用
        self._status_text: Optional[ft.Text] = None
        self._auto_switch_switch: Optional[ft.Switch] = None

        # 创建页面内容
        self._build_page()

    def _build_page(self) -> None:
        """构建页面内容"""
        self._logger.info("ModelConfigPage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 创建标题
        title = ft.Text(
            "模型配置",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 创建左侧模型列表
        config_list_panel = self._create_config_list_panel()

        # 创建右侧配置编辑表单
        config_edit_panel = self._create_config_edit_panel()

        # 创建文件选择器（Service 控件，需注册到 page.services）
        self._file_picker = ft.FilePicker()
        self._page.services.append(self._file_picker)

        # 左右布局（左侧固定比例，右侧自适应，保持协调）
        body = ft.Row(
            [
                # 左侧：模型列表
                ft.Container(
                    content=config_list_panel,
                    expand=2,
                    bgcolor=colors.surface,
                    border_radius=8,
                    padding=10,
                ),
                # 右侧：配置编辑
                ft.Container(
                    content=config_edit_panel,
                    expand=3,
                    bgcolor=colors.bg_page,
                    border_radius=8,
                    padding=10,
                ),
            ],
            spacing=10,
            expand=True,
        )

        # 自动故障切换开关
        auto_switch_section = self._create_auto_switch_section()

        # 状态栏
        status_bar = self._create_status_bar()

        # 主容器
        self._content = ft.Column(
            [
                title,
                ft.Container(height=14),
                ft.Container(content=body, expand=13),  # 占 10 份
                ft.Container(height=8),
                ft.Container(content=auto_switch_section, expand=1),  # 占 1 份
                ft.Container(height=8),
                ft.Container(content=status_bar, expand=1),  # 占 1 份
            ],
            spacing=0,
            expand=True,
        )
        self._logger.info("ModelConfigPage: 页面构建完成")

    def _create_config_list_panel(self) -> ft.Column:
        """
        创建配置列表面板

        Returns:
            配置列表面板
        """
        colors = self._theme_manager.get_color_scheme()

        # 标题栏
        header = ft.Row(
            [
                ft.Text(
                    "配置列表",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=colors.text,
                ),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.ADD,
                    icon_color=colors.primary,
                    icon_size=16,
                    tooltip="添加新配置",
                    on_click=self._on_add_config_click,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # 配置列表
        self._config_list_column = ft.Column(
            [],
            spacing=5,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # 底部操作按钮
        action_buttons = ft.Row(
            [
                ft.TextButton(
                    "导入配置",
                    icon=ft.Icons.FILE_UPLOAD,
                    style=ft.ButtonStyle(icon_size=16),
                    on_click=self._on_import_config_click,
                ),
                ft.TextButton(
                    "导出配置",
                    icon=ft.Icons.FILE_DOWNLOAD,
                    style=ft.ButtonStyle(icon_size=16),
                    on_click=self._on_export_config_click,
                ),
            ],
            spacing=10,
        )

        panel = ft.Column(
            [
                header,
                ft.Container(height=10),
                self._config_list_column,
                ft.Container(height=10),
                action_buttons,
            ],
            spacing=0,
            expand=True,
        )

        return panel

    def _create_config_edit_panel(self) -> ft.Column:
        """
        创建配置编辑面板

        Returns:
            配置编辑面板
        """
        colors = self._theme_manager.get_color_scheme()

        # 标题
        title = ft.Text(
            "配置参数",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 表单字段
        self._name_field = ft.TextField(
            label="配置名称",
            hint_text="如：主配置、备用配置",
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        self._model_name_field = ft.TextField(
            label="模型名称",
            hint_text="如：qwen-plus、glm-4",
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        self._api_key_field = ft.TextField(
            label="API Key",
            hint_text="输入API密钥",
            password=True,
            can_reveal_password=True,
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        self._base_url_field = ft.TextField(
            label="Base URL",
            hint_text="API基础地址",
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        self._temperature_field = ft.TextField(
            label="温度系数",
            hint_text="0.7",
            value="0.7",
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
            helper="0-2，值越高越随机",
            helper_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        self._top_p_field = ft.TextField(
            label="Top P",
            hint_text="0.95",
            value="0.95",
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
            helper="0-1，值越小越聚焦",
            helper_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        self._frequency_penalty_field = ft.TextField(
            label="频率惩罚",
            hint_text="0.6",
            value="0.6",
            border_color=colors.border,
            focused_border_color=colors.primary,
            cursor_color=colors.primary,
            text_style=ft.TextStyle(color=colors.text, size=11),
            label_style=ft.TextStyle(color=colors.text_muted, size=11),
            hint_style=ft.TextStyle(color=colors.text_muted, size=10),
            helper="值越高越避免重复",
            helper_style=ft.TextStyle(color=colors.text_muted, size=10),
        )

        # 能力开关控件
        self._enable_vision_switch = ft.Switch(
            label="视觉能力",
            value=True,
        )

        self._enable_deep_thinking_switch = ft.Switch(
            label="深度思考能力",
            value=True,
        )

        self._enable_tool_call_switch = ft.Switch(
            label="工具调用能力",
            value=True,
        )

        # 保存按钮
        save_button = ft.ElevatedButton(
            "保存配置",
            icon=ft.Icons.SAVE,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                icon_size=16,
            ),
            on_click=self._on_save_config_click,
        )

        # 删除按钮
        delete_button = ft.OutlinedButton(
            "删除配置",
            icon=ft.Icons.DELETE,
            icon_color=colors.error,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                icon_size=16,
            ),
            on_click=self._on_delete_config_click,
        )

        # 表单容器
        form = ft.Column(
            [
                self._name_field,
                ft.Container(height=10),
                self._model_name_field,
                ft.Container(height=10),
                self._api_key_field,
                ft.Container(height=10),
                self._base_url_field,
                ft.Container(height=10),
                self._temperature_field,
                ft.Container(height=10),
                self._top_p_field,
                ft.Container(height=10),
                self._frequency_penalty_field,
                ft.Container(height=10),
                self._enable_vision_switch,
                ft.Container(height=10),
                self._enable_deep_thinking_switch,
                ft.Container(height=10),
                self._enable_tool_call_switch,
                ft.Container(height=14),
                ft.Container(
                    content=ft.Row([save_button, delete_button], spacing=12),
                    padding=ft.Padding(top=0, bottom=6, left=0, right=0),
                ),
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # 面板容器
        # expand=True 让容器填满父级剩余空间，使内部 form 的 scroll 能正确生效
        self._config_form = ft.Container(
            content=form,
            visible=False,
            expand=True,
        )

        panel = ft.Column(
            [
                title,
                ft.Container(height=10),
                self._config_form,
            ],
            spacing=0,
            expand=True,
        )

        return panel

    def _load_config_list(self) -> None:
        """加载配置列表"""
        if not self._config_list_column:
            return

        colors = self._theme_manager.get_color_scheme()

        # 清空现有列表
        self._config_list_column.controls.clear()

        # 获取所有配置
        configs = list_configs()
        multi_config = get_current_multi_config()
        active_config = multi_config.get_active_config()
        active_id = active_config.id if active_config else None

        # 添加配置项
        for config in configs:
            is_active = config.id == active_id
            config_item = self._create_config_list_item(config, is_active)
            self._config_list_column.controls.append(config_item)

        # 更新显示
        try:
            if self._config_list_column.page:
                self._config_list_column.update()
        except RuntimeError:
            # 控件尚未添加到页面，跳过更新
            pass

    def _create_config_list_item(
        self, config: LLMConfigItem, is_active: bool
    ) -> ft.Container:
        """
        创建配置列表项

        Args:
            config: 配置项
            is_active: 是否激活

        Returns:
            配置列表项容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 激活状态指示器
        indicator_color = colors.success if is_active else colors.border
        indicator = ft.Icon(
            ft.Icons.CIRCLE,
            size=10,
            color=indicator_color,
        )

        # 配置名称
        name_text = ft.Text(
            config.name,
            size=11,
            weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
            color=colors.text,
        )

        # 模型名称
        model_text = ft.Text(
            config.model_name,
            size=10,
            color=colors.text_muted,
        )

        # 信息列
        info_column = ft.Column(
            [name_text, model_text],
            spacing=3,
        )

        # 激活按钮（仅在非激活配置上显示）
        activate_button = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW if not is_active else ft.Icons.CHECK,
            icon_color=colors.primary if not is_active else colors.success,
            icon_size=16,
            tooltip="设为激活" if not is_active else "当前激活",
            on_click=lambda e, config_id=config.id: self._on_activate_config_click(
                config_id
            ),
            disabled=is_active,
            visible=True,
        )

        # 配置项容器
        item_container = ft.Container(
            content=ft.Row(
                [indicator, ft.Container(width=10), info_column, ft.Container(expand=True), activate_button],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=colors.primary_soft if is_active else colors.bg_page,
            border_radius=6,
            padding=10,
            on_click=lambda e, config_id=config.id: self._on_config_item_click(
                config_id
            ),
        )

        return item_container

    def _on_config_item_click(self, config_id: str) -> None:
        """
        配置项点击事件（选中编辑）

        Args:
            config_id: 配置ID
        """
        self._selected_config_id = config_id
        self._load_config_to_form(config_id)
        self._update_list_selection()

    def _on_activate_config_click(self, config_id: str) -> None:
        """
        激活配置按钮点击事件

        Args:
            config_id: 配置ID
        """
        if set_active_config(config_id):
            self._logger.info(f"已切换激活配置: {config_id}")
            self._show_snackbar("已切换激活配置")

            # 重新加载列表
            self._load_config_list()

            # 更新状态栏
            self._update_status_bar()
        else:
            self._show_snackbar("切换激活配置失败", error=True)

    def _update_list_selection(self) -> None:
        """更新列表选中状态"""
        # 重新加载列表（简化处理）
        self._load_config_list()

    def _load_config_to_form(self, config_id: str) -> None:
        """
        加载配置到表单

        Args:
            config_id: 配置ID
        """
        from llm.llm_config_manager import get_config

        config = get_config(config_id)
        if not config:
            return

        # 填充表单字段
        self._name_field.value = config.name
        self._model_name_field.value = config.model_name
        self._api_key_field.value = config.api_key
        self._base_url_field.value = config.base_url
        self._temperature_field.value = str(config.temperature)
        self._top_p_field.value = str(config.top_p)
        self._frequency_penalty_field.value = str(config.frequency_penalty)

        # 设置能力开关状态
        self._enable_vision_switch.value = config.enable_vision
        self._enable_deep_thinking_switch.value = config.enable_deep_thinking
        self._enable_tool_call_switch.value = config.enable_tool_call

        # 显示表单
        self._config_form.visible = True

        # 更新UI
        if self._config_form.page:
            self._config_form.update()

    def _clear_form(self) -> None:
        """清空表单"""
        self._name_field.value = ""
        self._model_name_field.value = ""
        self._api_key_field.value = ""
        self._base_url_field.value = ""
        self._temperature_field.value = "0.7"
        self._top_p_field.value = "0.95"
        self._frequency_penalty_field.value = "0.6"

        # 重置能力开关为 True
        self._enable_vision_switch.value = True
        self._enable_deep_thinking_switch.value = True
        self._enable_tool_call_switch.value = True

    def _on_add_config_click(self, e) -> None:
        """添加新配置按钮点击事件"""
        # 清空选中
        self._selected_config_id = None

        # 清空表单
        self._clear_form()

        # 显示表单
        self._config_form.visible = True

        # 更新UI
        if self._config_form.page:
            self._config_form.update()

    def _on_save_config_click(self, e) -> None:
        """保存配置按钮点击事件"""
        # 验证必填字段
        if not self._name_field.value or not self._name_field.value.strip():
            self._show_snackbar("请输入配置名称", error=True)
            return

        if not self._model_name_field.value or not self._model_name_field.value.strip():
            self._show_snackbar("请输入模型名称", error=True)
            return

        if not self._api_key_field.value or not self._api_key_field.value.strip():
            self._show_snackbar("请输入 API Key", error=True)
            return

        if not self._base_url_field.value or not self._base_url_field.value.strip():
            self._show_snackbar("请输入 Base URL", error=True)
            return

        # 验证数值字段
        try:
            temperature = float(self._temperature_field.value or "0.7")
            if temperature < 0 or temperature > 2:
                self._show_snackbar("温度系数必须在 0 到 2 之间", error=True)
                return
        except ValueError:
            self._show_snackbar("温度系数必须是数字", error=True)
            return

        try:
            top_p = float(self._top_p_field.value or "0.95")
            if top_p < 0 or top_p > 1:
                self._show_snackbar("Top P 必须在 0 到 1 之间", error=True)
                return
        except ValueError:
            self._show_snackbar("Top P 必须是数字", error=True)
            return

        try:
            frequency_penalty = float(self._frequency_penalty_field.value or "0.6")
        except ValueError:
            self._show_snackbar("频率惩罚必须是数字", error=True)
            return

        # 创建配置项
        config_item = LLMConfigItem(
            id=self._selected_config_id or generate_config_id(),
            name=self._name_field.value.strip(),
            model_name=self._model_name_field.value.strip(),
            api_key=self._api_key_field.value.strip(),
            base_url=self._base_url_field.value.strip(),
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            enable_vision=self._enable_vision_switch.value,
            enable_deep_thinking=self._enable_deep_thinking_switch.value,
            enable_tool_call=self._enable_tool_call_switch.value,
        )

        # 保存配置
        if self._selected_config_id:
            # 更新现有配置
            if update_config(self._selected_config_id, config_item):
                self._logger.info(f"已更新配置: {config_item.name}")
                self._show_snackbar("配置已更新")
            else:
                self._show_snackbar("更新配置失败", error=True)
                return
        else:
            # 添加新配置
            add_config(config_item)
            self._logger.info(f"已添加配置: {config_item.name}")
            self._show_snackbar("配置已添加")

        # 重新加载列表
        self._load_config_list()

    def _on_delete_config_click(self, e) -> None:
        """删除配置按钮点击事件"""
        if not self._selected_config_id:
            self._show_snackbar("请先选择要删除的配置", error=True)
            return

        # 检查是否是最后一个配置
        configs = list_configs()
        if len(configs) <= 1:
            self._show_snackbar("至少需要保留一个配置", error=True)
            return

        # 删除配置
        if delete_config(self._selected_config_id):
            self._logger.info(f"已删除配置: {self._selected_config_id}")
            self._show_snackbar("配置已删除")

            # 清空选中
            self._selected_config_id = None
            self._config_form.visible = False

            # 重新加载列表
            self._load_config_list()
        else:
            self._show_snackbar("删除配置失败", error=True)

    async def _on_import_config_click(self, e) -> None:
        """导入配置按钮点击事件"""
        if not self._file_picker:
            return

        # 打开文件选择器
        files = await self._file_picker.pick_files(
            allowed_extensions=["json"],
            allow_multiple=False,
        )
        if not files:
            return

        file_path = files[0].path

        try:
            # 读取文件内容
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 验证配置格式
            if not isinstance(data, dict):
                self._show_snackbar("配置文件格式错误", error=True)
                return

            # 检查是否是多配置格式
            if "configs" in data:
                # 多配置格式
                multi_config = MultiLLMConfig.from_dict(data)
                set_multi_config(multi_config)
                self._logger.info("已导入多配置文件")
                self._show_snackbar(f"已导入 {len(multi_config.configs)} 个配置")
            elif "model_name" in data:
                # 单配置格式（兼容旧格式）
                config_item = LLMConfigItem.from_dict(data)
                add_config(config_item)
                self._logger.info(f"已导入配置: {config_item.name}")
                self._show_snackbar(f"已导入配置: {config_item.name}")
            else:
                self._show_snackbar("配置文件格式不正确", error=True)
                return

            # 重新加载列表
            self._load_config_list()

        except Exception as ex:
            self._logger.exception("导入配置失败")
            self._show_snackbar(f"导入配置失败: {str(ex)}", error=True)

    async def _on_export_config_click(self, e) -> None:
        """导出配置按钮点击事件"""
        if not self._file_picker:
            return

        # 打开保存文件对话框
        path = await self._file_picker.save_file(
            allowed_extensions=["json"],
            file_name="llm_config.json",
        )
        if not path:
            return

        try:
            # 获取当前配置
            multi_config = get_current_multi_config()

            # 转换为字典
            data = multi_config.to_dict()

            # 写入文件
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self._logger.info(f"已导出配置到: {path}")
            self._show_snackbar(f"已导出配置到: {path}")

        except Exception as ex:
            self._logger.exception("导出配置失败")
            self._show_snackbar(f"导出配置失败: {str(ex)}", error=True)

    def _create_auto_switch_section(self) -> ft.Container:
        """创建自动故障切换区域"""
        colors = self._theme_manager.get_color_scheme()

        self._auto_switch_switch = ft.Switch(
            label="启用自动故障切换（当当前配置失败时自动切换到下一组）",
            value=True,
            on_change=self._on_auto_switch_changed,
        )

        return ft.Container(
            content=ft.Row([self._auto_switch_switch]),
            bgcolor=colors.surface,
            padding=10,
            border_radius=8,
        )

    def _create_status_bar(self) -> ft.Container:
        """创建状态栏"""
        colors = self._theme_manager.get_color_scheme()

        self._status_text = ft.Text(
            "加载中...",
            size=10,
            color=colors.text_muted,
        )

        return ft.Container(
            content=self._status_text,
            bgcolor=colors.surface,
            padding=10,
            border_radius=8,
        )

    def _on_auto_switch_changed(self, e: ft.ControlEvent) -> None:
        """自动切换开关变化事件"""
        if self._auto_switch_switch:
            enabled = self._auto_switch_switch.value
            multi_config = get_current_multi_config()
            multi_config.auto_switch_on_failure = enabled
            set_multi_config(multi_config)
            self._logger.info(f"自动故障切换已{'启用' if enabled else '禁用'}")

    def _update_status_bar(self) -> None:
        """更新状态栏显示"""
        if not self._status_text:
            return

        multi_config = get_current_multi_config()
        active_config = multi_config.get_active_config()
        if active_config:
            self._status_text.value = f"当前激活配置: {active_config.name} ({active_config.model_name})"
        else:
            self._status_text.value = "当前无激活配置"

        try:
            if self._status_text.page:
                self._status_text.update()
        except RuntimeError:
            pass

    def _show_snackbar(self, message: str, error: bool = False) -> None:
        """
        显示提示消息

        Args:
            message: 提示消息
            error: 是否是错误消息
        """
        colors = self._theme_manager.get_color_scheme()

        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(
                message,
                color=colors.text_on_primary,
                size=11,
            ),
            bgcolor=colors.error if error else colors.primary,
            duration=3000,
        )
        self._page.snack_bar.open = True
        self._page.update()

    async def async_load_data(self) -> None:
        """异步加载数据，在页面可见后调用"""
        # 加载配置列表
        self._load_config_list()

        # 读取自动切换状态
        self._auto_switch_switch.value = is_auto_switch_enabled()

        # 更新状态栏
        self._update_status_bar()

        # 更新页面
        try:
            if self._page:
                self._page.update()
        except Exception:
            pass

    def get_content(self) -> ft.Control:
        """
        获取页面内容

        Returns:
            页面内容控件
        """
        return self._content