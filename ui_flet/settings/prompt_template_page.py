"""
Flet 系统提示词模板配置页面

提供三种会话类型的系统提示词模板编辑、验证、重置功能。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import flet as ft

import prompt_template_config as template_config
from logger import get_logger
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    pass


CONVERSATION_TYPE_NAMES = {
    "agent_conversation": "智能体会话",
    "human_chat_conversation": "聊天会话",
    "record_conversation": "录音会话",
}


class PromptTemplatePage:
    """
    系统提示词模板配置页面

    支持按会话类型编辑模板、验证占位符、重置默认值。
    """

    def __init__(self, page: ft.Page) -> None:
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # UI 组件引用
        self._type_dropdown: Optional[ft.Dropdown] = None
        self._editor: Optional[ft.TextField] = None
        self._preview: Optional[ft.Markdown] = None
        self._status_text: Optional[ft.Text] = None
        self._placeholder_list: Optional[ft.Column] = None

        # 当前模板数据
        self._templates: dict[str, str] = {}

        # 主容器
        self._container: Optional[ft.Container] = None

    def build(self) -> ft.Container:
        """构建页面 UI"""
        self._logger.info("PromptTemplatePage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 加载模板
        self._templates = template_config.load_template_config()

        # 标题
        title = ft.Text(
            "系统提示词配置",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 说明
        info = ft.Text(
            "为不同会话类型配置系统提示词模板。使用 {PLACEHOLDER} 格式引用动态内容。",
            size=11,
            color=colors.text_muted,
        )

        # 会话类型选择
        self._type_dropdown = ft.Dropdown(
            label="会话类型",
            options=[
                ft.dropdown.Option(k, v) for k, v in CONVERSATION_TYPE_NAMES.items()
            ],
            value="agent_conversation",
            width=390,
            on_select=self._on_type_changed,
        )

        # 编辑器
        self._editor = ft.TextField(
            value="",
            multiline=True,
            min_lines=16,
            max_lines=30,
            expand=True,
            text_style=ft.TextStyle(
                font_family="Consolas, Monaco, monospace",
                size=15,
                color=colors.text,
            ),
            hint_text="在此输入系统提示词模板...",
            hint_style=ft.TextStyle(color=colors.text_muted),
            bgcolor=colors.surface,
            border_color=colors.border,
            focused_border_color=colors.primary,
            content_padding=12,
            on_change=self._on_editor_changed,
        )

        # 实时预览
        self._preview = ft.Markdown(
            value="",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme="github",
        )

        # 占位符说明列表
        self._placeholder_list = ft.Column([], spacing=4, scroll=ft.ScrollMode.AUTO)
        self._load_placeholder_list()

        # 状态文本
        self._status_text = ft.Text(
            "",
            size=11,
            color=colors.text_muted,
        )

        # 按钮
        save_btn = ft.ElevatedButton(
            "保存",
            icon=ft.Icons.SAVE,
            on_click=self._on_save,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        reset_btn = ft.OutlinedButton(
            "重置为默认",
            icon=ft.Icons.RESTORE,
            on_click=self._on_reset,
        )

        reset_all_btn = ft.OutlinedButton(
            "重置全部",
            icon=ft.Icons.RESTORE_PAGE,
            on_click=self._on_reset_all,
        )

        # 左侧编辑区
        editor_section = ft.Container(
            content=ft.Column(
                [
                    ft.Text("模板编辑", size=11, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=4),
                    self._editor,
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )

        # 右侧预览区
        preview_section = ft.Container(
            content=ft.Column(
                [
                    ft.Text("实时预览", size=11, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=4),
                    ft.Container(
                        content=self._preview,
                        expand=True,
                        padding=10,
                        bgcolor=colors.surface,
                        border_radius=8,
                        border=ft.Border(
                            left=ft.BorderSide(1, colors.border),
                            top=ft.BorderSide(1, colors.border),
                            right=ft.BorderSide(1, colors.border),
                            bottom=ft.BorderSide(1, colors.border),
                        ),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )

        # 占位符帮助区
        help_section = ft.Container(
            content=ft.Column(
                [
                    ft.Text("可用占位符", size=11, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=4),
                    self._placeholder_list,
                ],
                spacing=0,
                expand=True,
            ),
            width=390,
            padding=10,
            bgcolor=colors.surface,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

        # 中间编辑和预览并排
        editor_preview_row = ft.Row(
            [editor_section, preview_section],
            spacing=10,
            expand=True,
        )

        # 主内容
        content = ft.Column(
            [
                title,
                ft.Container(height=4),
                info,
                ft.Container(height=16),
                ft.Row([self._type_dropdown, ft.Container(expand=True)]),
                ft.Container(height=10),
                ft.Row(
                    [editor_preview_row, help_section],
                    spacing=10,
                    expand=True,
                ),
                ft.Container(height=10),
                ft.Row(
                    [save_btn, reset_btn, reset_all_btn, ft.Container(expand=True), self._status_text],
                    spacing=10,
                ),
            ],
            spacing=0,
            expand=True,
        )

        self._container = ft.Container(
            content=content,
            padding=20,
            expand=True,
        )

        # 初始加载
        self._load_current_template()

        self._logger.info("PromptTemplatePage: 页面构建完成")
        return self._container

    def _load_placeholder_list(self) -> None:
        """加载占位符说明列表"""
        colors = self._theme_manager.get_color_scheme()
        descriptions = template_config.get_all_placeholder_descriptions()

        controls: list[ft.Control] = []
        for placeholder, desc in descriptions.items():
            controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                f"{{{placeholder}}}",
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color=colors.primary,
                                font_family="Consolas, Monaco, monospace",
                            ),
                            ft.Text(desc, size=10, color=colors.text_muted),
                        ],
                        spacing=3,
                    ),
                    padding=ft.Padding(left=0, top=6, right=0, bottom=6),
                    on_click=lambda e, p=placeholder: self._insert_placeholder(p),
                    tooltip="点击插入占位符",
                )
            )

        self._placeholder_list.controls = controls

    def _load_current_template(self) -> None:
        """加载当前选中的模板到编辑器"""
        conv_type = self._type_dropdown.value if self._type_dropdown else "agent_conversation"
        template = self._templates.get(conv_type, "")
        if self._editor:
            self._editor.value = template
        if self._preview:
            self._preview.value = template
        self._validate_and_show_status(template)

    def _validate_and_show_status(self, template: str) -> None:
        """验证模板并显示状态"""
        is_valid, invalid = template_config.validate_template(template)
        if self._status_text:
            if is_valid:
                self._status_text.value = "模板有效"
                self._status_text.color = self._theme_manager.get_color_scheme().success
            else:
                self._status_text.value = f"无效占位符: {', '.join(invalid)}"
                self._status_text.color = self._theme_manager.get_color_scheme().error

    def _on_type_changed(self, e) -> None:
        """会话类型切换"""
        self._load_current_template()
        try:
            self._page.update()
        except Exception:
            pass

    def _on_editor_changed(self, e) -> None:
        """编辑器内容变化"""
        if self._preview:
            self._preview.value = self._editor.value or ""
        self._validate_and_show_status(self._editor.value or "")
        try:
            self._page.update()
        except Exception:
            pass

    def _insert_placeholder(self, placeholder: str) -> None:
        """在编辑器中插入占位符"""
        if not self._editor:
            return

        text = self._editor.value or ""
        insertion = f"{{{placeholder}}}"
        self._editor.value = text + insertion
        self._preview.value = self._editor.value
        self._validate_and_show_status(self._editor.value)
        try:
            self._page.update()
        except Exception:
            pass

    def _on_save(self, e) -> None:
        """保存当前模板"""
        conv_type = self._type_dropdown.value if self._type_dropdown else "agent_conversation"
        template = self._editor.value or ""

        is_valid, invalid = template_config.validate_template(template)
        if not is_valid:
            self._show_snackbar(f"保存失败，无效占位符: {', '.join(invalid)}", success=False)
            return

        try:
            template_config.update_template_for_conversation_type(conv_type, template)
            self._templates = template_config.load_template_config()
            self._show_snackbar("模板已保存", success=True)
        except Exception as ex:
            self._logger.exception("保存模板失败")
            self._show_snackbar(f"保存失败: {ex}", success=False)

    def _on_reset(self, e) -> None:
        """重置当前模板为默认"""
        conv_type = self._type_dropdown.value if self._type_dropdown else "agent_conversation"
        name = CONVERSATION_TYPE_NAMES.get(conv_type, conv_type)

        def on_confirm():
            try:
                template_config.reset_template_for_conversation_type(conv_type)
                self._templates = template_config.load_template_config()
                self._load_current_template()
                self._show_snackbar(f"{name} 模板已重置", success=True)
            except Exception as ex:
                self._logger.exception("重置模板失败")
                self._show_snackbar(f"重置失败: {ex}", success=False)

        self._show_confirm_dialog(
            "确认重置",
            f"确定要将 {name} 的模板重置为默认吗？",
            on_confirm,
        )

    def _on_reset_all(self, e) -> None:
        """重置所有模板为默认"""
        def on_confirm():
            try:
                template_config.reset_all_templates()
                self._templates = template_config.load_template_config()
                self._load_current_template()
                self._show_snackbar("所有模板已重置为默认", success=True)
            except Exception as ex:
                self._logger.exception("重置模板失败")
                self._show_snackbar(f"重置失败: {ex}", success=False)

        self._show_confirm_dialog(
            "确认重置全部",
            "确定要将所有会话类型的模板重置为默认吗？此操作不可撤销。",
            on_confirm,
        )

    def _show_confirm_dialog(self, title: str, message: str, on_confirm: callable) -> None:
        """显示确认对话框"""
        colors = self._theme_manager.get_color_scheme()

        def on_confirm_click(e):
            dialog.open = False
            self._page.update()
            on_confirm()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "确定",
                    on_click=on_confirm_click,
                    bgcolor=colors.primary,
                    color=colors.text_on_primary,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _close_dialog(self, dialog: ft.AlertDialog) -> None:
        """关闭对话框"""
        dialog.open = False
        self._page.update()

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """显示提示消息"""
        colors = self._theme_manager.get_color_scheme()
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=colors.text_on_primary),
            bgcolor=colors.success if success else colors.error,
        )
        self._page.snack_bar.open = True
        self._page.update()

    def refresh(self) -> None:
        """刷新页面"""
        self._templates = template_config.load_template_config()
        self._load_current_template()
