"""
Flet 快捷键设置页面

提供快捷键配置界面，支持查看、修改和重置快捷键。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import flet as ft

from config import get_config, set_config
from logger import get_logger
from ui_flet.theme import ThemeManager, get_color

if TYPE_CHECKING:
    pass


# 默认快捷键配置
DEFAULT_HOTKEYS = {
    "record": {
        "name": "录音快捷键",
        "description": "开始/停止录音",
        "default": "ctrl+r",
        "config_key": "HOTKEY_RECORD",
    },
    "show_window": {
        "name": "显示窗口快捷键",
        "description": "显示/隐藏主窗口",
        "default": "ctrl+shift+w",
        "config_key": "HOTKEY_SHOW_WINDOW",
    },
    "send_message": {
        "name": "发送消息快捷键",
        "description": "发送当前输入的消息",
        "default": "ctrl+enter",
        "config_key": "HOTKEY_SEND_MESSAGE",
    },
    "new_conversation": {
        "name": "新建会话快捷键",
        "description": "创建新的会话",
        "default": "ctrl+n",
        "config_key": "HOTKEY_NEW_CONVERSATION",
    },
    "settings": {
        "name": "打开设置快捷键",
        "description": "打开设置对话框",
        "default": "ctrl+,",
        "config_key": "HOTKEY_SETTINGS",
    },
    "newline": {
        "name": "输入换行快捷键",
        "description": "在输入框中插入换行符",
        "default": "enter",
        "config_key": "HOTKEY_NEWLINE",
    },
}


class HotkeySettingsPage:
    """
    快捷键设置页面

    提供快捷键的配置功能，包括：
    - 查看当前快捷键配置
    - 修改快捷键（监听键盘事件）
    - 重置为默认快捷键
    """

    def __init__(self, page: ft.Page) -> None:
        """
        初始化快捷键设置页面

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # 当前正在编辑的快捷键ID
        self._editing_hotkey_id: Optional[str] = None

        # 快捷键显示文本框引用
        self._hotkey_text_fields: dict[str, ft.TextField] = {}

        # 保存原来的键盘事件处理器，编辑快捷键结束后恢复
        self._saved_keyboard_handler = None

        # 主容器
        self._container: Optional[ft.Container] = None

    def build(self) -> ft.Container:
        """
        构建页面 UI

        Returns:
            页面容器
        """
        self._logger.info("HotkeySettingsPage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        # 标题
        title = ft.Text(
            "快捷键设置",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 说明文字
        info_text = ft.Text(
            "点击快捷键输入框，然后按下新的快捷键组合进行修改。",
            size=11,
            color=colors.text_muted,
        )

        # 快捷键列表
        hotkey_list = self._build_hotkey_list()

        # 操作按钮
        reset_btn = ft.OutlinedButton(
            "重置所有快捷键",
            on_click=self._on_reset_all,
            icon=ft.Icons.RESTORE,
            style=ft.ButtonStyle(icon_size=16),
        )

        # 主内容
        content = ft.Column(
            [
                title,
                ft.Container(height=10),
                info_text,
                ft.Container(height=14),
                hotkey_list,
                ft.Container(height=14),
                reset_btn,
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self._container = ft.Container(
            content=content,
            padding=20,
        )

        self._logger.info("HotkeySettingsPage: 页面构建完成")
        return self._container

    def _build_hotkey_list(self) -> ft.Container:
        """
        构建快捷键列表

        Returns:
            快捷键列表容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 快捷键项
        hotkey_items = []

        for hotkey_id, hotkey_config in DEFAULT_HOTKEYS.items():
            item = self._build_hotkey_item(hotkey_id, hotkey_config)
            hotkey_items.append(item)
            hotkey_items.append(ft.Container(height=10))

        # 移除最后一个多余的间隔
        if hotkey_items:
            hotkey_items.pop()

        return ft.Container(
            content=ft.Column(
                hotkey_items,
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=10,
        )

    def _build_hotkey_item(
        self,
        hotkey_id: str,
        hotkey_config: dict[str, Any],
    ) -> ft.Container:
        """
        构建单个快捷键项

        Args:
            hotkey_id: 快捷键ID
            hotkey_config: 快捷键配置

        Returns:
            快捷键项容器
        """
        colors = self._theme_manager.get_color_scheme()

        # 获取当前快捷键值
        current_value = self._get_hotkey_value(hotkey_id, hotkey_config)

        # 快捷键名称
        name_text = ft.Text(
            hotkey_config["name"],
            size=11,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        # 快捷键描述
        desc_text = ft.Text(
            hotkey_config["description"],
            size=11,
            color=colors.text_muted,
        )

        # 快捷键输入框
        hotkey_field = ft.TextField(
            value=current_value,
            read_only=True,
            text_align=ft.TextAlign.CENTER,
            text_style=ft.TextStyle(
                size=20,
                weight=ft.FontWeight.BOLD,
            ),
            border_color=colors.border,
            focused_border_color=colors.primary,
            on_focus=lambda e, hid=hotkey_id: self._on_hotkey_focus(hid),
            on_blur=lambda e, hid=hotkey_id: self._on_hotkey_blur(hid),
            width=300,
        )

        # 保存引用
        self._hotkey_text_fields[hotkey_id] = hotkey_field

        # 重置按钮
        reset_btn = ft.IconButton(
            icon=ft.Icons.RESTORE,
            icon_color=colors.text_muted,
            icon_size=16,
            tooltip="重置为默认",
            on_click=lambda e, hid=hotkey_id: self._on_reset_single(hid),
        )

        # 行布局
        row = ft.Row(
            [
                ft.Column(
                    [
                        name_text,
                        desc_text,
                    ],
                    spacing=2,
                    expand=True,
                ),
                hotkey_field,
                reset_btn,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=row,
            padding=10,
            border_radius=8,
            ink=True,
            on_click=lambda e, hid=hotkey_id: self._on_hotkey_click(hid),
        )

    def _get_hotkey_value(self, hotkey_id: str, hotkey_config: dict) -> str:
        """
        获取快捷键当前值

        Args:
            hotkey_id: 快捷键ID
            hotkey_config: 快捷键配置

        Returns:
            快捷键值（如 "Ctrl+R"）
        """
        config_key = hotkey_config["config_key"]
        config_value = get_config(config_key)

        if config_value:
            return config_value.upper()

        # 返回默认值
        return hotkey_config["default"].upper()

    def _on_hotkey_click(self, hotkey_id: str) -> None:
        """
        快捷键项点击事件

        Args:
            hotkey_id: 快捷键ID
        """
        # 保存原来的键盘事件处理器（仅在首次进入编辑时保存）
        if self._editing_hotkey_id is None:
            self._saved_keyboard_handler = self._page.on_keyboard_event

        self._editing_hotkey_id = hotkey_id

        # 设置页面键盘事件监听
        self._page.on_keyboard_event = self._on_keyboard_event

        # 更新UI提示
        if hotkey_id in self._hotkey_text_fields:
            field = self._hotkey_text_fields[hotkey_id]
            field.border_color = self._theme_manager.get_color_scheme().primary
            field.update()

    def _on_hotkey_focus(self, hotkey_id: str) -> None:
        """
        快捷键输入框获取焦点

        Args:
            hotkey_id: 快捷键ID
        """
        # 保存原来的键盘事件处理器（仅在首次进入编辑时保存）
        if self._editing_hotkey_id is None:
            self._saved_keyboard_handler = self._page.on_keyboard_event

        self._editing_hotkey_id = hotkey_id
        self._page.on_keyboard_event = self._on_keyboard_event

    def _on_hotkey_blur(self, hotkey_id: str) -> None:
        """
        快捷键输入框失去焦点

        Args:
            hotkey_id: 快捷键ID
        """
        if self._editing_hotkey_id == hotkey_id:
            self._editing_hotkey_id = None
            # 恢复原来的键盘事件处理器，而非置 None（否则会丢失主窗口的全局快捷键）
            self._page.on_keyboard_event = self._saved_keyboard_handler

    def _on_keyboard_event(self, e) -> None:
        """
        键盘事件处理

        Args:
            e: 键盘事件对象
        """
        if not self._editing_hotkey_id:
            return

        # 忽略单独的修饰键
        if e.key.lower() in ["ctrl", "shift", "alt", "meta"]:
            return

        # 构建快捷键字符串
        modifiers = []
        if e.ctrl:
            modifiers.append("ctrl")
        if e.shift:
            modifiers.append("shift")
        if e.alt:
            modifiers.append("alt")
        if e.meta:
            modifiers.append("meta")

        # 获取主键
        key = e.key.lower()
        if key in ["control", "shift", "alt", "meta"]:
            return

        # 特殊键映射
        key_map = {
            "enter": "enter",
            "backspace": "backspace",
            "tab": "tab",
            "escape": "esc",
            "arrowup": "up",
            "arrowdown": "down",
            "arrowleft": "left",
            "arrowright": "right",
            "space": "space",
            "minus": "-",
            "equal": "=",
            "bracketleft": "[",
            "bracketright": "]",
            "semicolon": ";",
            "quote": "'",
            "comma": ",",
            "period": ".",
            "slash": "/",
        }

        if key in key_map:
            key = key_map[key]

        # 组合快捷键字符串
        hotkey_parts = modifiers + [key]
        hotkey_str = "+".join(hotkey_parts)

        # 保存快捷键
        self._save_hotkey(self._editing_hotkey_id, hotkey_str)

        # 更新UI
        if self._editing_hotkey_id in self._hotkey_text_fields:
            field = self._hotkey_text_fields[self._editing_hotkey_id]
            field.value = hotkey_str.upper()
            field.border_color = self._theme_manager.get_color_scheme().border
            field.update()

        self._logger.info(f"快捷键更新: {self._editing_hotkey_id} = {hotkey_str}")

    def _save_hotkey(self, hotkey_id: str, hotkey_str: str) -> None:
        """
        保存快捷键配置

        Args:
            hotkey_id: 快捷键ID
            hotkey_str: 快捷键字符串
        """
        if hotkey_id not in DEFAULT_HOTKEYS:
            return

        config_key = DEFAULT_HOTKEYS[hotkey_id]["config_key"]
        set_config(config_key, hotkey_str.lower())

    def _on_reset_single(self, hotkey_id: str) -> None:
        """
        重置单个快捷键

        Args:
            hotkey_id: 快捷键ID
        """
        if hotkey_id not in DEFAULT_HOTKEYS:
            return

        default_value = DEFAULT_HOTKEYS[hotkey_id]["default"]

        # 更新配置
        self._save_hotkey(hotkey_id, default_value)

        # 更新UI
        if hotkey_id in self._hotkey_text_fields:
            field = self._hotkey_text_fields[hotkey_id]
            field.value = default_value.upper()
            field.update()

        self._logger.info(f"快捷键已重置: {hotkey_id} = {default_value}")

    def _on_reset_all(self, e) -> None:
        """重置所有快捷键"""
        for hotkey_id, hotkey_config in DEFAULT_HOTKEYS.items():
            default_value = hotkey_config["default"]

            # 更新配置
            self._save_hotkey(hotkey_id, default_value)

            # 更新UI
            if hotkey_id in self._hotkey_text_fields:
                field = self._hotkey_text_fields[hotkey_id]
                field.value = default_value.upper()
                field.update()

        self._logger.info("所有快捷键已重置为默认值")

        # 显示提示
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text("所有快捷键已重置为默认值", size=11),
            action="确定",
        )
        self._page.snack_bar.open = True

