"""
等待用户回复卡片组件

当 Skill Agent 需要用户补充输入时显示，支持固定选项选择和自由回复提示。
"""
from __future__ import annotations

from typing import Any, Callable

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager, DEFAULT_SPACING_CONFIG


class AwaitUserCard(ft.Container):
    """
    等待用户回复卡片

    功能：
    - 显示 Agent 提出的问题
    - 显示可选上下文提示
    - 提供固定选项单选列表
    - 无选项时提示用户在输入框自由回复
    """

    def __init__(self):
        super().__init__()
        self._logger = get_logger()
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        self._selected_text: str | None = None
        self._on_confirm_send: Callable[[str], None] | None = None
        self._radio_group: ft.RadioGroup | None = None
        self._confirm_button: ft.ElevatedButton | None = None

        self._build_ui()
        self.visible = False

    def _build_ui(self) -> None:
        """构建基础 UI"""
        self.content = ft.Column([], spacing=8, tight=True)
        self.bgcolor = self._colors.surface
        self.border = ft.Border(
            left=ft.BorderSide(1, self._colors.border),
            top=ft.BorderSide(1, self._colors.border),
            right=ft.BorderSide(1, self._colors.border),
            bottom=ft.BorderSide(1, self._colors.border),
        )
        self.border_radius = 10
        self.padding = ft.Padding(left=12, top=10, right=12, bottom=10)
        self.margin = ft.Margin(left=16, top=0, right=16, bottom=10)

    def show_prompt(
        self,
        spec: dict[str, Any],
        *,
        on_confirm_send: Callable[[str], None] | None = None,
    ) -> None:
        """
        显示等待用户回复的提示

        Args:
            spec: 包含 question, context, choices 的字典
            on_confirm_send: 用户确认选项后的回调
        """
        self.clear_prompt()
        self._on_confirm_send = on_confirm_send

        question = str(spec.get("question") or "").strip()
        context = str(spec.get("context") or "").strip()
        choices_raw = spec.get("choices")
        choices: list[str] = []
        if isinstance(choices_raw, list):
            for c in choices_raw:
                if c is None:
                    continue
                s = str(c).strip()
                if s:
                    choices.append(s)

        controls: list[ft.Control] = []

        # 问题文本
        question_text = ft.Text(
            question or "（模型未提供具体问题）",
            size=15,
            weight=ft.FontWeight.W_600,
            color=self._colors.text,
        )
        controls.append(question_text)

        if choices:
            # 有固定选项
            if context:
                controls.append(
                    ft.Text(
                        context,
                        size=12,
                        color=self._colors.text_muted,
                    )
                )

            controls.append(
                ft.Text(
                    "请选择一个建议回答，点击下方「确定」将立即发送（无需再点发送）：",
                    size=12,
                    color=self._colors.text_muted,
                )
            )

            # 创建单选选项
            radio_options = [ft.Radio(value=c, label=c) for c in choices]
            self._radio_group = ft.RadioGroup(
                content=ft.Column(radio_options, spacing=8),
                on_change=self._on_choice_change,
            )

            # 选项滚动区域
            scroll_container = ft.Container(
                content=self._radio_group,
                height=min(320, max(120, len(choices) * 44)),
                padding=ft.Padding(right=6, top=0, left=0, bottom=0),
            )
            controls.append(scroll_container)

            # 确定按钮
            self._confirm_button = ft.ElevatedButton(
                "确定",
                on_click=self._on_confirm,
                disabled=True,
                style=ft.ButtonStyle(
                    color={
                        ft.ControlState.DEFAULT: self._colors.text_on_primary,
                        ft.ControlState.DISABLED: self._colors.text_muted,
                    },
                    bgcolor={
                        ft.ControlState.DEFAULT: self._colors.primary,
                        ft.ControlState.DISABLED: self._colors.border,
                    },
                    shape=ft.RoundedRectangleBorder(radius=6),
                    padding=ft.Padding(left=20, right=20, top=8, bottom=8),
                ),
            )
            controls.append(
                ft.Row(
                    [self._confirm_button],
                    alignment=ft.MainAxisAlignment.START,
                )
            )
        else:
            # 无固定选项
            if context:
                controls.append(
                    ft.Text(
                        context,
                        size=12,
                        color=self._colors.text_muted,
                    )
                )
            controls.append(
                ft.Text(
                    "未提供固定选项：请在下方输入框自由输入后发送。",
                    size=12,
                    color=self._colors.text_muted,
                )
            )

        self.content.controls = controls
        self.visible = True
        self._safe_update()

    def clear_prompt(self) -> None:
        """清空提示并隐藏卡片"""
        self.visible = False
        self._selected_text = None
        self._on_confirm_send = None
        self._radio_group = None
        self._confirm_button = None
        self.content.controls = []
        self._safe_update()

    def has_active_prompt(self) -> bool:
        """是否有正在显示的提示"""
        return self.visible

    def _on_choice_change(self, e: ft.ControlEvent) -> None:
        """选项变化事件"""
        self._selected_text = e.control.value
        if self._confirm_button:
            self._confirm_button.disabled = not bool(self._selected_text)
            self._confirm_button.update()

    def _on_confirm(self, e: ft.ControlEvent) -> None:
        """确定按钮点击事件"""
        if self._selected_text:
            self._logger.info(f"AwaitUserCard: 用户选择 {self._selected_text[:50]}...")
            if self._on_confirm_send:
                self._on_confirm_send(self._selected_text)
            self.clear_prompt()

    def _safe_update(self) -> None:
        """安全更新 UI"""
        try:
            self.update()
        except Exception:
            pass

    def update_theme(self) -> None:
        """更新主题"""
        self._colors = self._theme_manager.get_color_scheme()
        self.bgcolor = self._colors.surface
        self.border = ft.Border(
            left=ft.BorderSide(1, self._colors.border),
            top=ft.BorderSide(1, self._colors.border),
            right=ft.BorderSide(1, self._colors.border),
            bottom=ft.BorderSide(1, self._colors.border),
        )
        self._safe_update()
