"""
LLM状态指示器组件

显示LLM通信状态的指示器，包括状态图标和文本。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from ui_flet.theme import get_color, ThemeManager
from ui_flet.state import LLMCommunicationState

if TYPE_CHECKING:
    pass


def _get_state_color(state: str, colors) -> str:
    """根据状态获取对应的颜色

    Args:
        state: LLM通信状态
        colors: 主题颜色配置

    Returns:
        颜色字符串
    """
    # 状态颜色映射
    color_map = {
        "IDLE": colors.text_muted,  # 空闲：灰色
        "SENDING_REQUEST": colors.warning,  # 发送请求：橙色
        "WAITING_FOR_RESPONSE": colors.warning,  # 等待响应：黄色/橙色
        "RECEIVING_STREAM": colors.success,  # 接收响应：绿色
        "COMMUNICATION_ENDED": colors.text_muted,  # 通信结束：灰色
    }
    return color_map.get(state, colors.text_muted)


def _get_state_icon(state: str) -> str:
    """根据状态获取对应的图标

    Args:
        state: LLM通信状态

    Returns:
        图标名称
    """
    # 状态图标映射
    icon_map = {
        "IDLE": ft.Icons.CIRCLE_OUTLINED,
        "SENDING_REQUEST": ft.Icons.SEND,
        "WAITING_FOR_RESPONSE": ft.Icons.HOURGLASS_EMPTY,
        "RECEIVING_STREAM": ft.Icons.AUTO_AWESOME,
        "COMMUNICATION_ENDED": ft.Icons.CHECK_CIRCLE_OUTLINE,
    }
    return icon_map.get(state, ft.Icons.CIRCLE_OUTLINED)


def _get_state_display_text(state: str) -> str:
    """将状态枚举转换为友好的中文显示文本

    Args:
        state: LLM通信状态枚举值

    Returns:
        中文显示文本
    """
    state_map = {
        "IDLE": "空闲",
        "SENDING_REQUEST": "正在发送请求",
        "WAITING_FOR_RESPONSE": "等待响应中",
        "RECEIVING_STREAM": "正在接收响应",
        "COMMUNICATION_ENDED": "通信结束"
    }
    return state_map.get(state, state)


class LLMStatusIndicator:
    """
    LLM状态指示器组件

    显示当前LLM通信状态，包括：
    - 状态图标（带颜色）
    - 状态文本
    - 耗时信息（可选）

    使用方式：
        indicator = LLMStatusIndicator()
        indicator.update_state(state_data)
        page.add(indicator.get_control())
    """

    def __init__(self) -> None:
        """初始化状态指示器"""
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        # 当前状态
        self._current_state: LLMCommunicationState = LLMCommunicationState()

        # UI控件引用
        self._icon: ft.Icon | None = None
        self._text: ft.Text | None = None
        self._container: ft.Container | None = None

        # 初始化控件
        self._init_controls()

    def _init_controls(self) -> None:
        """初始化所有控件"""
        # 状态图标
        self._icon = ft.Icon(
            icon=_get_state_icon("IDLE"),
            color=_get_state_color("IDLE", self._colors),
            size=14,
        )

        # 状态文本
        self._text = ft.Text(
            value="",
            color=self._colors.text_muted,
            size=12,
        )

        # 状态容器（水平布局）
        status_row = ft.Row(
            [
                self._icon,
                self._text,
            ],
            spacing=4,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # 外层容器（带左内边距）
        self._container = ft.Container(
            content=status_row,
            padding=ft.Padding(left=8, top=2, right=8, bottom=2),
            visible=False,  # 默认隐藏，只在非空闲状态显示
        )

    def update_state(self, state: LLMCommunicationState) -> None:
        """更新状态显示

        Args:
            state: 新的LLM通信状态
        """
        self._current_state = state

        # 更新图标和颜色
        state_name = state.state
        self._icon.icon = _get_state_icon(state_name)
        self._icon.color = _get_state_color(state_name, self._colors)

        # 更新文本
        display_text = _get_state_display_text(state_name)
        if state.duration_ms > 0:
            self._text.value = f"{display_text} ({state.duration_ms}ms)"
        else:
            self._text.value = display_text

        # 非空闲状态时显示，空闲时隐藏
        self._container.visible = state_name != "IDLE"

    def get_control(self) -> ft.Container:
        """获取控件"""
        return self._container

    def update_theme(self) -> None:
        """更新主题颜色"""
        self._colors = self._theme_manager.get_color_scheme()
        # 根据当前状态重新设置颜色
        self._icon.color = _get_state_color(self._current_state.state, self._colors)
        self._text.color = self._colors.text_muted