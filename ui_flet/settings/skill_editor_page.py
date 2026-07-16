"""
Skill 编辑器页面

提供 Markdown 格式的 Skill 编辑功能，支持实时渲染和 "/" 触发工具列表。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional, TYPE_CHECKING

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    from skill.skill_manager import SkillData

logger = get_logger()


def get_all_tools_for_display() -> list[dict[str, Any]]:
    """获取所有工具用于显示"""
    try:
        from base_tool import get_tool_registry

        registry = get_tool_registry()
        tools = []
        for tool_info in registry.get_all_tools_flat():
            tool_name = tool_info.get("name", "")
            tool_desc = tool_info.get("description", "")
            tool_category = tool_info.get("category", "atomic")
            simple_desc = tool_desc.split("\n")[0] if tool_desc else ""
            tools.append({
                "name": tool_name,
                "category": tool_category,
                "description": simple_desc,
                "full_description": tool_desc,
                "parameters": tool_info.get("parameters", {}),
            })
        return tools
    except Exception:
        logger.exception("SkillEditorPage: 获取工具列表失败")
        return []


def generate_inline_expression(tool_dict: dict[str, Any]) -> str:
    """根据工具定义生成内联参数表达式"""
    tool_name = tool_dict.get("name", "")
    parameters = tool_dict.get("parameters", {})

    if not parameters:
        return f"{{{tool_name}}}"

    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    if not properties:
        return f"{{{tool_name}}}"

    param_parts = []
    for param_name, param_def in properties.items():
        is_required = param_name in required
        if is_required:
            param_parts.append(f'{param_name}="{{{{user_input.{param_name}}}}}"')
        else:
            default_val = param_def.get("default")
            if default_val is not None:
                if isinstance(default_val, bool):
                    default_val = str(default_val).lower()
                else:
                    default_val = str(default_val)
                param_parts.append(f'{param_name}="{default_val}"')

    if param_parts:
        inner = f"{tool_name}({', '.join(param_parts)})"
        return "{" + inner + "}"
    return "{" + tool_name + "}"


class SkillEditorPage:
    """
    Skill 编辑器页面

    提供 Markdown 编辑、实时预览、工具列表插入等功能。
    """

    def __init__(
        self,
        page: ft.Page,
        skill_data: "SkillData",
        *,
        on_save: Optional[Callable[[str], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        self._page = page
        self._skill_data = skill_data
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()
        self._logger = get_logger()

        self._editor: Optional[ft.TextField] = None
        self._preview: Optional[ft.Markdown] = None
        self._tool_popup: Optional[ft.Container] = None
        self._slash_pos: int = -1
        self._popup_active: bool = False
        self._dialog: Optional[ft.AlertDialog] = None
        self._result: Optional[str] = None
        self._on_save_callback = on_save
        self._on_cancel_callback = on_cancel

    def _build_dialog(self) -> ft.AlertDialog:
        """构建编辑器对话框"""
        # Markdown 编辑器
        self._editor = ft.TextField(
            value=self._skill_data.to_markdown(),
            multiline=True,
            min_lines=20,
            max_lines=40,
            expand=True,
            text_style=ft.TextStyle(
                font_family="Consolas, Monaco, monospace",
                size=12,
                color=self._colors.text,
            ),
            hint_text="输入 Markdown 内容...\n输入 '/' 可触发内置工具列表",
            hint_style=ft.TextStyle(color=self._colors.text_muted),
            bgcolor=self._colors.surface,
            border_color=self._colors.border,
            focused_border_color=self._colors.primary,
            content_padding=10,
            on_change=self._on_text_changed,
        )

        # Markdown 预览
        self._preview = ft.Markdown(
            value=self._editor.value or "",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme="github",
        )

        # 工具列表弹出框
        self._tool_popup = self._build_tool_popup()

        # 左侧编辑器区域
        editor_column = ft.Column(
            [
                ft.Text("Markdown 编辑", size=11, weight=ft.FontWeight.BOLD, color=self._colors.text),
                ft.Container(height=4),
                self._editor,
            ],
            spacing=0,
            expand=True,
        )

        # 右侧预览区域
        preview_column = ft.Column(
            [
                ft.Text("实时预览", size=11, weight=ft.FontWeight.BOLD, color=self._colors.text),
                ft.Container(height=4),
                ft.Container(
                    content=self._preview,
                    expand=True,
                    padding=10,
                    bgcolor=self._colors.surface,
                    border_radius=8,
                    border=ft.Border(
                        left=ft.BorderSide(1, self._colors.border),
                        top=ft.BorderSide(1, self._colors.border),
                        right=ft.BorderSide(1, self._colors.border),
                        bottom=ft.BorderSide(1, self._colors.border),
                    ),
                ),
            ],
            spacing=0,
            expand=True,
        )

        # 编辑器和预览并排
        editor_row = ft.Row(
            [editor_column, preview_column],
            spacing=10,
            expand=True,
        )

        # 工具栏
        toolbar = ft.Row(
            [
                ft.TextButton("帮助", on_click=self._show_help),
                ft.TextButton("插入工具", on_click=self._show_tool_list),
                ft.Container(expand=True),
            ],
            spacing=8,
        )

        # 主内容
        content = ft.Column(
            [
                ft.Text(
                    f"编辑 Skill: {self._skill_data.metadata.name}",
                    size=11,
                    weight=ft.FontWeight.BOLD,
                    color=self._colors.text,
                ),
                ft.Text(
                    "Skill 采用 Markdown 格式存储。输入 '/' 可触发内置工具列表，大模型将理解 Markdown 内容并执行自动化操作。",
                    size=10,
                    color=self._colors.text_muted,
                ),
                ft.Container(height=10),
                editor_row,
                toolbar,
            ],
            spacing=0,
            expand=True,
        )

        # 底部按钮
        cancel_btn = ft.TextButton("取消", on_click=self._on_cancel)
        save_btn = ft.ElevatedButton(
            "保存",
            on_click=self._on_save,
            bgcolor=self._colors.primary,
            color=self._colors.text_on_primary,
        )

        self._dialog = ft.AlertDialog(
            modal=True,
            content=content,
            actions=[cancel_btn, save_btn],
            actions_alignment=ft.MainAxisAlignment.END,
            content_padding=12,
            inset_padding=16,
        )

        return self._dialog

    def _build_tool_popup(self) -> ft.Container:
        """构建工具列表弹出框"""
        self._tool_list_column = ft.Column([], spacing=2, scroll=ft.ScrollMode.AUTO)

        popup = ft.Container(
            content=self._tool_list_column,
            bgcolor=self._colors.surface,
            border=ft.Border(
                left=ft.BorderSide(1, self._colors.border),
                top=ft.BorderSide(1, self._colors.border),
                right=ft.BorderSide(1, self._colors.border),
                bottom=ft.BorderSide(1, self._colors.border),
            ),
            border_radius=4,
            padding=4,
            width=280,
            height=300,
            visible=False,
        )
        return popup

    def open(self) -> None:
        """打开编辑器对话框"""
        dialog = self._build_dialog()
        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def get_result(self) -> Optional[str]:
        """获取编辑结果"""
        return self._result

    def _on_text_changed(self, e: ft.ControlEvent) -> None:
        """文本变化事件"""
        text = self._editor.value or ""
        cursor_pos = len(text)  # Flet 不直接提供光标位置，这里简化处理

        # 更新预览
        if self._preview:
            self._preview.value = text

        # 简化版的 "/" 检测：检查末尾是否有 "/word"
        if self._popup_active:
            # 检查是否应该关闭弹出框
            if self._slash_pos >= 0 and self._slash_pos < cursor_pos:
                filter_text = text[self._slash_pos + 1:cursor_pos]
                if filter_text and not all(c.isalnum() or c == "_" for c in filter_text):
                    self._close_tool_popup()
                else:
                    self._update_tool_popup(filter_text)
            else:
                self._close_tool_popup()
        else:
            # 检测是否输入了 "/"
            if cursor_pos > 0 and text[cursor_pos - 1] == "/":
                if cursor_pos == 1 or text[cursor_pos - 2] in (" ", "\n", "\t"):
                    self._slash_pos = cursor_pos - 1
                    self._show_tool_popup()

        self._page.update()

    def _show_tool_popup(self) -> None:
        """显示工具列表弹出框"""
        tools_data = get_all_tools_for_display()
        if not tools_data:
            return

        self._popup_active = True
        self._update_tool_popup("")
        if self._tool_popup:
            self._tool_popup.visible = True

    def _close_tool_popup(self) -> None:
        """关闭工具列表弹出框"""
        self._popup_active = False
        self._slash_pos = -1
        if self._tool_popup:
            self._tool_popup.visible = False

    def _update_tool_popup(self, filter_text: str) -> None:
        """更新工具列表弹出框内容"""
        tools_data = get_all_tools_for_display()
        category_names = {
            "locators": "定位器",
            "executors": "执行器",
            "extractors": "提取器",
            "conditions": "条件判断",
            "atomic": "原子工具",
            "control": "控制工具",
        }

        controls: list[ft.Control] = []
        current_category = None
        filtered_count = 0

        for tool in tools_data:
            category = tool.get("category", "atomic")
            if category != current_category:
                category_name = category_names.get(category, category)
                controls.append(
                    ft.Text(
                        f"── {category_name} ──",
                        size=10,
                        color=self._colors.text_muted,
                        weight=ft.FontWeight.BOLD,
                    )
                )
                current_category = category

            tool_name = tool["name"]
            if filter_text and filter_text.lower() not in tool_name.lower():
                continue

            filtered_count += 1
            controls.append(
                ft.Container(
                    content=ft.Text(f"/{tool_name}", size=10, color=self._colors.text),
                    padding=ft.Padding(left=8, top=6, right=8, bottom=6),
                    border_radius=4,
                    bgcolor={
                        ft.ControlState.HOVERED: self._colors.surface_hover,
                    },
                    on_click=lambda e, name=tool_name: self._insert_tool_reference(name),
                    tooltip=tool.get("description", ""),
                )
            )

        if filtered_count == 0:
            controls.append(
                ft.Text("无匹配工具", size=10, color=self._colors.text_muted)
            )

        self._tool_list_column.controls = controls

    def _insert_tool_reference(self, tool_name: str) -> None:
        """插入工具引用"""
        if not self._editor:
            return

        text = self._editor.value or ""
        cursor_pos = len(text)

        # 删除从 slash_pos 到当前光标的内容
        if self._slash_pos >= 0 and self._slash_pos < cursor_pos:
            text = text[:self._slash_pos] + text[cursor_pos:]
            cursor_pos = self._slash_pos

        # 查找工具定义
        try:
            from base_tool import get_tool_registry

            registry = get_tool_registry()
            tool_info = registry.get_tool_by_name(tool_name)
            if tool_info:
                definition = tool_info.get("definition", {})
                expr = generate_inline_expression(definition)
            else:
                expr = f"{{{tool_name}}}"
        except Exception:
            expr = f"{{{tool_name}}}"

        # 插入工具引用
        new_text = text[:cursor_pos] + f"使用工具{expr}" + text[cursor_pos:]
        self._editor.value = new_text
        self._preview.value = new_text

        self._close_tool_popup()
        self._page.update()

    def _show_help(self, e: ft.ControlEvent) -> None:
        """显示帮助信息"""
        help_text = """Skill Markdown 编辑帮助

1. YAML Front Matter（元数据）
   ---
   id: skill_001
   name: Skill名称
   description: Skill描述
   tags: [automation, browser]
   created_at: 2026-06-13T10:00:00
   ---
   这部分定义Skill的基本信息。

2. Markdown内容
   使用标准Markdown语法编写Skill内容。

3. 工具引用
   输入 '/' 可触发内置工具列表，选择工具后自动插入引用模板。

   工具引用格式：
   使用 /tool_name 执行操作
   - 参数：param1="value1", param2="value2"

4. 参数引用
   使用 {{user_input.xxx}} 引用用户输入参数
   使用 {{step_n_result}} 引用前一步骤的结果

5. 执行流程
   在"执行流程"部分按顺序描述操作步骤，
   大模型将理解并执行这些操作。"""

        self._show_message_dialog("编辑帮助", help_text)

    def _show_tool_list(self, e: ft.ControlEvent) -> None:
        """显示工具列表对话框"""
        tools_data = get_all_tools_for_display()
        category_names = {
            "atomic": "原子工具",
            "control": "控制工具",
            "locators": "定位器",
            "executors": "执行器",
            "extractors": "提取器",
            "conditions": "条件判断",
        }

        tool_items = []
        for tool in tools_data:
            category = category_names.get(tool.get("category", "unknown"), tool.get("category", "unknown"))
            tool_name = tool["name"]
            desc = tool.get("description", "")

            tool_items.append(
                ft.ListTile(
                    title=ft.Text(f"/{tool_name} [{category}]", size=11, color=self._colors.text),
                    subtitle=ft.Text(desc, size=10, color=self._colors.text_muted),
                    on_click=lambda e, name=tool_name: self._insert_tool_from_dialog(name, dialog),
                )
            )

        list_view = ft.ListView(tool_items, expand=True, spacing=2)

        content = ft.Column(
            [
                ft.Text("内置工具列表", size=10, weight=ft.FontWeight.BOLD, color=self._colors.text),
                ft.Text("以下是目前系统定义的所有工具，可在 Skill 中引用：", size=10, color=self._colors.text_muted),
                ft.Container(height=8),
                ft.Container(content=list_view, expand=True, height=400),
            ],
            spacing=0,
            expand=True,
        )

        close_btn = ft.TextButton("关闭", on_click=lambda e: self._close_dialog(dialog))

        dialog = ft.AlertDialog(
            modal=True,
            title=None,
            content=content,
            actions=[close_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _insert_tool_from_dialog(self, tool_name: str, dialog: ft.AlertDialog) -> None:
        """从工具列表对话框插入选中的工具"""
        self._insert_tool_reference(tool_name)
        dialog.open = False
        self._page.update()

    def _on_save(self, e: ft.ControlEvent) -> None:
        """保存 Skill"""
        content = self._editor.value.strip() if self._editor else ""
        if not content:
            self._show_snackbar("Skill 内容不能为空", success=False)
            return

        self._result = content
        if self._dialog:
            self._dialog.open = False
        self._page.update()

        if self._on_save_callback:
            try:
                self._on_save_callback(self._result)
            except Exception:
                self._logger.exception("SkillEditorPage: on_save 回调执行失败")

    def _on_cancel(self, e: ft.ControlEvent) -> None:
        """取消编辑"""
        if self._dialog:
            self._dialog.open = False
        self._page.update()

        if self._on_cancel_callback:
            try:
                self._on_cancel_callback()
            except Exception:
                self._logger.exception("SkillEditorPage: on_cancel 回调执行失败")

    def _show_snackbar(self, message: str, success: bool = True) -> None:
        """显示提示消息"""
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=self._colors.text_on_primary),
            bgcolor=self._colors.success if success else self._colors.error,
        )
        self._page.snack_bar.open = True
        self._page.update()

    def _show_message_dialog(self, title: str, message: str) -> None:
        """显示消息对话框"""
        content = ft.Column(
            [
                ft.Text(title, size=10, weight=ft.FontWeight.BOLD, color=self._colors.text),
                ft.Container(height=8),
                ft.Text(message, size=10, color=self._colors.text_muted, selectable=True),
            ],
            spacing=0,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )

        close_btn = ft.TextButton("关闭", on_click=lambda e: self._close_dialog(dialog))

        dialog = ft.AlertDialog(
            modal=True,
            title=None,
            content=content,
            actions=[close_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _close_dialog(self, dialog: ft.AlertDialog) -> None:
        """关闭对话框"""
        dialog.open = False
        self._page.update()
