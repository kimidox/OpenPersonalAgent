"""
Flet 定时任务管理页面

提供定时任务的创建、编辑、删除、启用/禁用功能，
并包含开机自启动设置。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

import flet as ft

import autostart
import config
import scheduled_tasks as tasks_module
from logger import get_logger
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    pass


REPEAT_TYPE_NAMES = {
    "none": "不重复",
    "daily": "每天",
    "weekly": "每周",
    "monthly": "每月",
}

NOTIFICATION_TYPE_NAMES = {
    "system": "系统通知",
    "toast": "Toast 通知",
}

EXECUTION_TYPE_NAMES = {
    "notification": "发送通知",
    "agent_conversation": "执行 Agent 对话",
}

STATUS_NAMES = {
    "pending": "待执行",
    "triggered": "已触发",
    "cancelled": "已取消",
    "deleted": "已删除",
}


class ScheduledTasksPage:
    """
    定时任务管理页面

    提供定时任务列表展示、增删改查以及开机自启动设置。
    """

    def __init__(self, page: ft.Page) -> None:
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # UI 组件引用
        self._task_list: Optional[ft.Column] = None
        self._status_filter: Optional[ft.Dropdown] = None
        self._status_text: Optional[ft.Text] = None
        self._autostart_switch: Optional[ft.Switch] = None

        # 当前编辑的任务ID
        self._editing_task_id: Optional[str] = None

        # 主容器
        self._container: Optional[ft.Container] = None

    def build(self) -> ft.Container:
        """构建页面 UI"""
        self._logger.info("ScheduledTasksPage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 标题
        title = ft.Text(
            "定时任务管理",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 说明
        info = ft.Text(
            "创建和管理定时触发的任务，支持发送通知或启动 Agent 对话。",
            size=10,
            color=colors.text_muted,
        )

        # 操作按钮
        create_btn = ft.ElevatedButton(
            "新建任务",
            icon=ft.Icons.ADD,
            style=ft.ButtonStyle(icon_size=16),
            on_click=self._on_create_click,
            bgcolor=colors.primary,
            color=colors.text_on_primary,
        )

        self._status_filter = ft.Dropdown(
            options=[
                ft.dropdown.Option("all", "全部"),
                ft.dropdown.Option("pending", "待执行"),
                ft.dropdown.Option("triggered", "已触发"),
                ft.dropdown.Option("cancelled", "已取消"),
            ],
            value="all",
            text_size=11,
            width=210,
            on_select=self._on_filter_change,
        )

        toolbar = ft.Row(
            [
                create_btn,
                ft.Container(expand=True),
                ft.Text("筛选：", size=11, weight=ft.FontWeight.BOLD, color=colors.text),
                self._status_filter,
            ],
            spacing=8,
        )

        # 任务列表
        self._task_list = ft.Column(
            [],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        list_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("任务列表", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=8),
                    self._task_list,
                ],
                spacing=0,
                expand=True,
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
            expand=True,
        )

        # 自启动设置
        autostart_section = self._build_autostart_section()

        # 状态栏
        self._status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        # 主容器
        self._container = ft.Container(
            content=ft.Column(
                [
                    title,
                    ft.Container(height=6),
                    info,
                    ft.Container(height=16),
                    toolbar,
                    ft.Container(height=10),
                    list_container,
                    ft.Container(height=16),
                    autostart_section,
                    ft.Container(height=10),
                    self._status_text,
                ],
                spacing=0,
                expand=True,
            ),
            padding=20,
            expand=True,
        )

        self._logger.info("ScheduledTasksPage: 页面构建完成")
        return self._container

    def _build_autostart_section(self) -> ft.Container:
        """构建自启动设置区域"""
        colors = self._theme_manager.get_color_scheme()

        self._autostart_switch = ft.Switch(
            label="开机自动启动",
            value=False,
            on_change=self._on_autostart_change,
        )

        self._autostart_status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("启动设置", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=8),
                    self._autostart_switch,
                    self._autostart_status_text,
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

    def _load_tasks(self) -> None:
        """加载任务列表"""
        if not self._task_list:
            return

        self._task_list.controls.clear()

        status = self._status_filter.value if self._status_filter else "all"
        if status == "all":
            status = None

        try:
            tasks = tasks_module.list_tasks(
                user_id=config.DEFAULT_SKILL_AGENT_USER,
                status=status,
            )
        except Exception as e:
            self._logger.exception("加载定时任务失败")
            self._show_snackbar(f"加载任务失败: {e}", success=False)
            tasks = []

        for task in tasks:
            item = self._create_task_item(task)
            self._task_list.controls.append(item)

        if self._status_text:
            self._status_text.value = f"共 {len(tasks)} 个任务"

        try:
            if self._page:
                self._page.update()
        except Exception:
            pass

    def _create_task_item(self, task: tasks_module.ScheduledTask) -> ft.Container:
        """创建单个任务项"""
        colors = self._theme_manager.get_color_scheme()

        title_text = ft.Text(
            task.title or "无标题",
            size=11,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        trigger_str = task.trigger_time.strftime("%Y-%m-%d %H:%M") if task.trigger_time else "未知"
        repeat_str = REPEAT_TYPE_NAMES.get(task.repeat_type, task.repeat_type)
        exec_str = EXECUTION_TYPE_NAMES.get(task.execution_type, task.execution_type)
        status_str = STATUS_NAMES.get(task.status, task.status)

        desc_text = ft.Text(
            f"触发时间: {trigger_str} · 重复: {repeat_str} · 执行方式: {exec_str} · 状态: {status_str}",
            size=10,
            color=colors.text_muted,
        )

        content_preview = ft.Text(
            task.content[:80] + "..." if len(task.content) > 80 else task.content,
            size=11,
            color=colors.text,
        )

        edit_btn = ft.IconButton(
            icon=ft.Icons.EDIT,
            icon_color=colors.primary,
            icon_size=16,
            tooltip="编辑",
            on_click=lambda e, tid=task.task_id: self._on_edit_click(tid),
        )

        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE,
            icon_color=colors.error,
            icon_size=16,
            tooltip="删除",
            on_click=lambda e, tid=task.task_id: self._on_delete_click(tid),
        )

        left_info = ft.Column(
            [
                title_text,
                desc_text,
                content_preview,
            ],
            spacing=6,
            expand=True,
        )

        row = ft.Row(
            [
                left_info,
                ft.Row([edit_btn, delete_btn], spacing=6),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=row,
            bgcolor=colors.bg_page,
            padding=10,
            border_radius=8,
            border=ft.Border(
                left=ft.BorderSide(1, colors.border),
                top=ft.BorderSide(1, colors.border),
                right=ft.BorderSide(1, colors.border),
                bottom=ft.BorderSide(1, colors.border),
            ),
        )

    def _load_autostart_state(self) -> None:
        """加载自启动状态"""
        if not self._autostart_switch:
            return

        try:
            enabled = autostart.is_autostart_enabled()
            self._autostart_switch.value = enabled
            self._update_autostart_status(enabled)
        except Exception as e:
            self._logger.exception("加载自启动状态失败")
            if self._autostart_status_text:
                self._autostart_status_text.value = f"读取状态失败: {e}"

    def _update_autostart_status(self, enabled: bool) -> None:
        """更新自启动状态文本"""
        if self._autostart_status_text:
            self._autostart_status_text.value = "已启用" if enabled else "未启用"

    def _on_filter_change(self, e) -> None:
        """筛选变化"""
        self._load_tasks()

    def _on_create_click(self, e) -> None:
        """新建任务"""
        self._editing_task_id = None
        self._show_task_dialog()

    def _on_edit_click(self, task_id: str) -> None:
        """编辑任务"""
        self._editing_task_id = task_id
        self._show_task_dialog()

    def _on_delete_click(self, task_id: str) -> None:
        """删除任务"""
        try:
            task = tasks_module.get_task(task_id)
        except Exception:
            self._show_snackbar("任务不存在", success=False)
            return

        def on_confirm():
            try:
                tasks_module.delete_task(task_id)
                self._load_tasks()
                self._show_snackbar("任务已删除", success=True)
            except Exception as ex:
                self._logger.exception("删除任务失败")
                self._show_snackbar(f"删除失败: {ex}", success=False)

        self._show_confirm_dialog(
            "确认删除",
            f"确定要删除任务 '{task.title}' 吗？",
            on_confirm,
        )

    def _show_task_dialog(self) -> None:
        """显示任务编辑对话框"""
        colors = self._theme_manager.get_color_scheme()

        task: Optional[tasks_module.ScheduledTask] = None
        if self._editing_task_id:
            try:
                task = tasks_module.get_task(self._editing_task_id)
            except Exception:
                self._show_snackbar("任务不存在", success=False)
                return

        now = datetime.now()
        default_time = now.replace(second=0, microsecond=0)

        title_field = ft.TextField(
            label="任务标题",
            value=task.title if task else "",
            autofocus=True,
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        content_field = ft.TextField(
            label="任务内容",
            value=task.content if task else "",
            multiline=True,
            min_lines=5,
            max_lines=9,
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        trigger_date_field = ft.TextField(
            label="触发日期 (YYYY-MM-DD)",
            value=(task.trigger_time if task else default_time).strftime("%Y-%m-%d"),
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        trigger_time_field = ft.TextField(
            label="触发时间 (HH:MM)",
            value=(task.trigger_time if task else default_time).strftime("%H:%M"),
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        repeat_dropdown = ft.Dropdown(
            label="重复类型",
            options=[ft.dropdown.Option(k, v) for k, v in REPEAT_TYPE_NAMES.items()],
            value=task.repeat_type if task else "none",
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        notification_dropdown = ft.Dropdown(
            label="通知类型",
            options=[ft.dropdown.Option(k, v) for k, v in NOTIFICATION_TYPE_NAMES.items()],
            value=task.notification_type if task else "system",
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        execution_dropdown = ft.Dropdown(
            label="执行方式",
            options=[ft.dropdown.Option(k, v) for k, v in EXECUTION_TYPE_NAMES.items()],
            value=task.execution_type if task else "notification",
            text_size=11,
            label_style=ft.TextStyle(size=11),
        )

        def on_save(e):
            title = title_field.value.strip()
            content = content_field.value.strip()
            date_str = trigger_date_field.value.strip()
            time_str = trigger_time_field.value.strip()
            repeat_type = repeat_dropdown.value or "none"
            notification_type = notification_dropdown.value or "system"
            execution_type = execution_dropdown.value or "notification"

            if not title:
                self._show_snackbar("请输入任务标题", success=False)
                return

            try:
                trigger_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                self._show_snackbar("日期或时间格式错误", success=False)
                return

            try:
                if self._editing_task_id:
                    tasks_module.update_task(
                        self._editing_task_id,
                        title=title,
                        content=content,
                        trigger_time=trigger_time,
                        repeat_type=repeat_type,
                        notification_type=notification_type,
                        execution_type=execution_type,
                    )
                    self._show_snackbar("任务已更新", success=True)
                else:
                    tasks_module.add_task(
                        user_id=config.DEFAULT_SKILL_AGENT_USER,
                        title=title,
                        content=content,
                        trigger_time=trigger_time,
                        repeat_type=repeat_type,
                        notification_type=notification_type,
                        execution_type=execution_type,
                    )
                    self._show_snackbar("任务已创建", success=True)

                dialog.open = False
                self._page.update()
                self._load_tasks()
            except Exception as ex:
                self._logger.exception("保存任务失败")
                self._show_snackbar(f"保存失败: {ex}", success=False)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("编辑任务" if self._editing_task_id else "新建任务", size=14),
            content=ft.Column(
                [
                    title_field,
                    content_field,
                    ft.Row([trigger_date_field, trigger_time_field], spacing=10),
                    repeat_dropdown,
                    notification_dropdown,
                    execution_dropdown,
                ],
                spacing=10,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
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

    def _on_autostart_change(self, e) -> None:
        """自启动开关变化"""
        enabled = self._autostart_switch.value if self._autostart_switch else False
        try:
            if enabled:
                success = autostart.enable_autostart()
                msg = "已启用开机自启动" if success else "启用自启动失败"
            else:
                success = autostart.disable_autostart()
                msg = "已禁用开机自启动" if success else "禁用自启动失败"

            self._update_autostart_status(enabled and success)
            self._show_snackbar(msg, success=success)
        except Exception as ex:
            self._logger.exception("修改自启动状态失败")
            self._show_snackbar(f"修改失败: {ex}", success=False)
            self._load_autostart_state()

    def _show_confirm_dialog(self, title: str, message: str, on_confirm: callable) -> None:
        """显示确认对话框"""
        colors = self._theme_manager.get_color_scheme()

        def on_confirm_click(e):
            dialog.open = False
            self._page.update()
            on_confirm()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=14),
            content=ft.Text(message, size=11, weight=ft.FontWeight.BOLD),
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
            content=ft.Text(message, size=11, color=colors.text_on_primary),
            bgcolor=colors.success if success else colors.error,
        )
        self._page.snack_bar.open = True
        self._page.update()

    async def async_load_data(self) -> None:
        """异步加载数据，在页面可见后调用"""
        await asyncio.sleep(0)  # yield to UI
        self._load_tasks()
        self._load_autostart_state()
        try:
            if self._page:
                self._page.update()
        except Exception:
            pass

    def refresh(self) -> None:
        """刷新页面"""
        self._load_tasks()
        self._load_autostart_state()
