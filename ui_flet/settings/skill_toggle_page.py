"""
Flet Skill 开关管理页面

提供已加载 Skill 的启用/禁用管理，以及 Skill 与会话类型的绑定配置。
对应旧版 PySide6 设置对话框中的"Skill管理"标签页。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import flet as ft

import config
from logger import get_logger
from skill.registry import SkillRegistry
from skill_agent_preferences import load_disabled_skill_ids, save_disabled_skill_ids, load_skill_bindings, save_skill_bindings
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    pass


CONVERSATION_TYPES = [
    ("agent_conversation", "智能体会话"),
    ("human_chat_conversation", "浮动聊天会话"),
    ("record_conversation", "录音会话"),
]


class SkillTogglePage:
    """
    Skill 开关管理页面

    管理已加载 Skill 的启用/禁用状态，以及 Skill 在不同会话类型中的默认绑定。
    """

    def __init__(self, page: ft.Page) -> None:
        """
        初始化 Skill 开关管理页面

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # Skill 注册表
        self._registry = SkillRegistry(config.SKILLS_DIR, config.BUILTIN_SKILLS_DIR)

        # 禁用的 Skill ID 集合
        self._disabled_skills: set[str] = set(load_disabled_skill_ids())

        # UI 组件引用
        self._skill_list: Optional[ft.Column] = None
        self._status_text: Optional[ft.Text] = None
        self._container: Optional[ft.Container] = None

    def build(self) -> ft.Container:
        """
        构建页面 UI

        Returns:
            页面容器
        """
        self._logger.info("SkillTogglePage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 标题
        title = ft.Text(
            "Skill 开关管理",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 说明
        info = ft.Text(
            "启用或禁用已加载的 Skill。禁用的 Skill 不会被 SkillAgent 加载和使用。\n"
            "点击编辑按钮可配置 Skill 在不同会话类型中的默认启用状态。",
            size=10,
            color=colors.text_muted,
        )

        # Skill 列表
        self._skill_list = ft.Column(
            [],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        list_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("已加载 Skill 列表", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=6),
                    self._skill_list,
                ],
                spacing=0,
                expand=True,
            ),
            bgcolor=colors.surface,
            padding=10,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
            expand=True,
        )

        # 状态栏
        self._status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        status_container = ft.Container(
            content=self._status_text,
            padding=ft.Padding(top=0, bottom=6, left=0, right=0),
        )

        # 主容器
        self._container = ft.Container(
            content=ft.Column(
                [
                    title,
                    ft.Container(height=6),
                    info,
                    ft.Container(height=16),
                    list_container,
                    ft.Container(height=10),
                    status_container,
                ],
                spacing=0,
                expand=True,
            ),
            padding=ft.Padding(left=10, top=10, right=10, bottom=14),
            expand=True,
        )

        # 加载列表
        self._load_skills()

        self._logger.info("SkillTogglePage: 页面构建完成")
        return self._container

    def _load_skills(self) -> None:
        """加载并显示 Skill 列表"""
        if not self._skill_list:
            return

        self._skill_list.controls.clear()

        try:
            skills = sorted(
                self._registry.list_skills(),
                key=lambda s: (s.skill_id or "").lower(),
            )
        except Exception as e:
            self._logger.exception("加载 Skill 列表失败")
            self._show_status(f"加载 Skill 列表失败: {e}", success=False)
            return

        colors = self._theme_manager.get_color_scheme()

        for skill in skills:
            sid = (skill.skill_id or "").strip()
            if not sid:
                continue

            skill_type = getattr(skill, "skill_type", "user")
            is_builtin = skill_type == "builtin"
            is_enabled = sid not in self._disabled_skills

            # 启用开关
            enable_switch = ft.Switch(
                label="启用",
                value=is_enabled,
                on_change=lambda e, _sid=sid: self._on_skill_toggled(_sid, e.control.value),
            )

            # 类型标签
            type_badge = None
            if is_builtin:
                type_badge = ft.Container(
                    content=ft.Text("内置", size=10, color=colors.text_on_primary),
                    bgcolor=colors.primary_soft,
                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                    border_radius=4,
                )

            # Skill 名称和 ID
            name_text = ft.Text(
                f"{sid} · {skill.name or ''}",
                size=11,
                weight=ft.FontWeight.BOLD,
                color=colors.text,
            )

            name_row = ft.Row(
                [name_text, type_badge] if type_badge else [name_text],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

            # 操作按钮
            edit_btn = ft.IconButton(
                icon=ft.Icons.EDIT,
                icon_color=colors.primary,
                icon_size=16,
                tooltip="编辑会话绑定",
                on_click=lambda e, _sid=sid, _name=skill.name: self._on_edit_binding(_sid, _name),
            )

            action_buttons = [edit_btn]
            if not is_builtin:
                delete_btn = ft.IconButton(
                    icon=ft.Icons.DELETE,
                    icon_color=colors.error,
                    icon_size=16,
                    tooltip="删除 Skill",
                    on_click=lambda e, _sid=sid: self._on_delete_skill(_sid),
                )
                action_buttons.append(delete_btn)

            # 整行布局
            row = ft.Row(
                [
                    enable_switch,
                    ft.Container(width=12),
                    ft.Column(
                        [name_row],
                        spacing=0,
                        expand=True,
                    ),
                    ft.Row(action_buttons, spacing=6),
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

            item_container = ft.Container(
                content=row,
                bgcolor=colors.bg_page,
                padding=10,  # 原 padding=10，缩小 30% 后为 7
                border_radius=8,
                border=ft.Border(
                    left=ft.BorderSide(1, colors.border),
                    top=ft.BorderSide(1, colors.border),
                    right=ft.BorderSide(1, colors.border),
                    bottom=ft.BorderSide(1, colors.border),
                ),
            )

            self._skill_list.controls.append(item_container)

        self._update_status_text()

        try:
            if self._page:
                self._page.update()
        except Exception:
            pass

    def _on_skill_toggled(self, skill_id: str, enabled: bool) -> None:
        """
        Skill 启用状态切换

        Args:
            skill_id: Skill ID
            enabled: 是否启用
        """
        if enabled:
            self._disabled_skills.discard(skill_id)
        else:
            self._disabled_skills.add(skill_id)

        save_disabled_skill_ids(self._disabled_skills)
        self._logger.info(f"Skill {skill_id} 已{'启用' if enabled else '禁用'}")
        self._update_status_text()

    def _on_delete_skill(self, skill_id: str) -> None:
        """
        删除 Skill

        Args:
            skill_id: Skill ID
        """
        skill = self._registry.get(skill_id)
        if skill is None:
            return

        skill_type = getattr(skill, "skill_type", "user")
        if skill_type == "builtin":
            self._show_status("系统内置 Skill 不可删除", success=False)
            return

        def on_confirm():
            try:
                success = self._registry.delete_skill(skill_id)
                if success:
                    self._disabled_skills.discard(skill_id)
                    save_disabled_skill_ids(self._disabled_skills)
                    self._load_skills()
                    self._show_status(f"Skill「{skill_id}」已删除", success=True)
                else:
                    self._show_status(f"删除 Skill「{skill_id}」失败", success=False)
            except Exception as e:
                self._logger.exception("删除 Skill 失败")
                self._show_status(f"删除 Skill 时发生错误: {e}", success=False)

        self._show_confirm_dialog(
            "确认删除",
            f"确定要删除 Skill「{skill_id}」吗？\n\n这将删除该 Skill 的文件夹及其所有内容。",
            on_confirm,
        )

    def _on_edit_binding(self, skill_id: str, skill_name: Optional[str]) -> None:
        """
        编辑 Skill 会话绑定

        Args:
            skill_id: Skill ID
            skill_name: Skill 名称
        """
        colors = self._theme_manager.get_color_scheme()
        name = skill_name or skill_id

        bindings = load_skill_bindings()
        conv_types = set(bindings.get(skill_id, []))

        checkboxes: dict[str, ft.Checkbox] = {}
        checkbox_controls = []
        for value, label in CONVERSATION_TYPES:
            cb = ft.Checkbox(
                label=label,
                value=value in conv_types,
            )
            checkboxes[value] = cb
            checkbox_controls.append(cb)

        def on_save(e):
            selected = [v for v, cb in checkboxes.items() if cb.value]
            new_bindings = dict(bindings)
            if selected:
                new_bindings[skill_id] = selected
            elif skill_id in new_bindings:
                del new_bindings[skill_id]

            try:
                save_skill_bindings(new_bindings)
                self._show_status(f"Skill「{name}」的会话绑定已保存", success=True)
            except Exception as ex:
                self._logger.exception("保存 Skill 绑定失败")
                self._show_status(f"保存失败: {ex}", success=False)

            dialog.open = False
            self._page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"配置 Skill 会话绑定 - {name}", size=12),
            content=ft.Column(
                [
                    ft.Text(f"Skill ID：{skill_id}", size=11, color=colors.text_muted),
                    ft.Text(f"Skill 名称：{name}", size=11, color=colors.text_muted),
                    ft.Container(height=10),
                    ft.Text("选择该 Skill 在哪些会话类型中默认启用：", size=11, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=10),
                    *checkbox_controls,
                ],
                spacing=0,
                tight=True,
            ),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog(dialog)),
                ft.ElevatedButton(
                    "保存",
                    on_click=on_save,
                    bgcolor=colors.primary,
                    color=colors.text_on_primary,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _update_status_text(self) -> None:
        """更新状态文本"""
        if self._status_text:
            total = len(self._skill_list.controls) if self._skill_list else 0
            disabled_count = len(self._disabled_skills)
            self._status_text.value = f"共 {total} 个 Skill，已禁用 {disabled_count} 个"

    def _show_confirm_dialog(self, title: str, message: str, on_confirm: callable) -> None:
        """显示确认对话框"""
        colors = self._theme_manager.get_color_scheme()

        def on_confirm_click(e):
            dialog.open = False
            self._page.update()
            on_confirm()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=12),
            content=ft.Text(message, size=10),
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

    def _show_status(self, message: str, success: bool = True) -> None:
        """显示状态信息"""
        if self._status_text:
            colors = self._theme_manager.get_color_scheme()
            self._status_text.value = message
            self._status_text.color = colors.success if success else colors.error
            self._status_text.update()

    def refresh(self) -> None:
        """刷新页面"""
        self._registry.reload()
        self._disabled_skills = set(load_disabled_skill_ids())
        self._load_skills()
