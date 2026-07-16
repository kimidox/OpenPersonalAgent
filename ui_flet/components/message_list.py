"""
消息列表组件

管理和显示消息卡片列表，支持自动滚动、流式更新等功能。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from ui_flet.components.message_card import MessageCard, MessageType
from ui_flet.theme import ThemeManager
from logger import get_logger

if TYPE_CHECKING:
    pass


class MessageList(ft.Container):
    """
    消息列表组件

    功能：
    - 管理消息卡片列表
    - 自动滚动到底部
    - 支持流式消息更新
    - 提供消息增删改查接口
    """

    def __init__(
        self,
        on_copy: Callable[[str], None] | None = None,
        on_speak: Callable[[str], None] | None = None,
        auto_scroll: bool = True,
    ):
        """
        初始化消息列表

        Args:
            on_copy: 复制回调函数
            on_speak: 朗读回调函数
            auto_scroll: 是否自动滚动到底部
        """
        super().__init__()

        self._logger = get_logger()
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        # 消息卡片列表
        self._message_cards: list[MessageCard] = []

        # 回调函数
        self._on_copy = on_copy
        self._on_speak = on_speak

        # 自动滚动
        self._auto_scroll = auto_scroll

        # 流式更新状态
        self._stream_task: asyncio.Task | None = None

        # 构建UI
        self._build_ui()

    def _build_ui(self) -> None:
        """构建消息列表UI"""
        self._logger.debug("MessageList: 构建 UI")
        # 创建消息容器（使用 ListView 实现滚动；旧版消息间距由 MessageCard 自身 margin 控制）
        self._list_view = ft.ListView(
            controls=[],
            expand=True,
            auto_scroll=self._auto_scroll,
            spacing=0,
            padding=0,
        )

        # 设置容器内容
        self.content = self._list_view
        self.expand = True
        self.bgcolor = self._colors.bg_page

    def _safe_update(self, control: ft.Control) -> None:
        """安全更新控件（未挂载到页面时忽略）

        优先调用 `page.update()` 触发整页重渲染，避免依赖
        `control.page` 在 Flet 0.85.3 中对 `ListView` 等子容器
        不可靠的问题（旧实现常导致新增的卡片"不渲染"）。
        """
        try:
            # 1. 优先使用 self.page（Flet 会自动沿 parent 链回溯）
            page = self.page
            if page is not None:
                page.update()
                return
            # 2. 回退到参数 control.page
            if getattr(control, "page", None) is not None:
                control.update()
                return
            self._logger.warning(
                "MessageList: _safe_update 跳过（控件未挂载到页面）"
            )
        except RuntimeError as e:
            # 静默吞掉 RuntimeError，保持向后兼容
            self._logger.warning(f"MessageList: _safe_update 异常: {e}")

    def add_message(
        self,
        msg_type: MessageType,
        content: str = "",
        token_usage: dict[str, Any] | None = None,
        update_ui: bool = True,
    ) -> MessageCard:
        """
        添加一条新消息

        Args:
            msg_type: 消息类型
            content: 消息内容
            token_usage: Token用量信息
            update_ui: 是否立即触发 UI 更新。
                批量加载历史消息时应传 False，由调用方在循环
                结束后统一调用 page.update()，避免 Flutter 在
                处理"清空→逐条添加"的中间布局状态时给 tight=True
                的 Column 分配错误的宽度约束（导致气泡变宽）。

        Returns:
            创建的消息卡片
        """
        # 创建消息卡片
        card = MessageCard(
            msg_type=msg_type,
            content=content,
            on_copy=self._on_copy,
            on_speak=self._on_speak if msg_type == "assistant" else None,
        )

        # 如果有 token_usage，立即完成渲染
        if token_usage and msg_type in ("assistant", "think"):
            card.finalize_content(token_usage)
        elif msg_type in ("tool_call", "tool"):
            card.finalize_content()

        # 添加到列表
        self._message_cards.append(card)
        self._list_view.controls.append(card)

        # 更新UI
        if update_ui:
            self._safe_update(self._list_view)
        self._logger.debug(f"MessageList: 添加消息 {msg_type}")

        return card

    def get_last_card(self) -> MessageCard | None:
        """获取最后一条消息卡片"""
        if self._message_cards:
            return self._message_cards[-1]
        return None

    def update_last_message(self, content: str) -> bool:
        """
        更新最后一条消息的内容

        Args:
            content: 新的消息内容

        Returns:
            是否成功更新
        """
        card = self.get_last_card()
        if card is None:
            return False

        card.update_content(content)
        return True

    def append_to_last_message(self, text: str) -> bool:
        """
        追加内容到最后一条消息（用于流式更新）

        Args:
            text: 要追加的文本

        Returns:
            是否成功追加
        """
        card = self.get_last_card()
        if card is None:
            return False

        card.append_content(text)
        return True

    def set_mode_badge_for_last(self, mode_text: str) -> bool:
        """
        为最后一条消息设置模式徽章

        Args:
            mode_text: 模式文本

        Returns:
            是否成功设置
        """
        card = self.get_last_card()
        if card is None:
            return False

        card.set_mode_badge(mode_text)
        return True

    def clear(self) -> None:
        """
        清空所有消息（与 clear_all 行为一致，兼容旧调用方）

        旧实现因 copy-paste 错误变成了"追加到最后一条卡片"，
        已在 bug 修复中改为真正的清空语义。
        """
        self.clear_all()

    def finalize_last_message(
        self,
        token_usage: dict[str, Any] | None = None,
    ) -> bool:
        """
        完成最后一条消息的渲染

        Args:
            token_usage: Token用量信息

        Returns:
            是否成功完成
        """
        card = self.get_last_card()
        if card is None:
            return False

        card.finalize_content(token_usage)
        return True

    def scroll_to_bottom(self) -> None:
        """滚动到底部"""
        # ListView 的 auto_scroll=True 会自动滚动
        # 这里提供手动滚动的方法
        if self._list_view.controls:
            # 通过更新触发滚动
            self._safe_update(self._list_view)

    def clear_all(self, update_ui: bool = True) -> None:
        """清空所有消息

        Args:
            update_ui: 是否立即触发 UI 更新。
                批量操作（如切换会话时先清空再加载）应传 False，
                由调用方在全部操作完成后统一更新。
        """
        self._message_cards.clear()
        self._list_view.controls.clear()
        if update_ui:
            self._safe_update(self._list_view)
        self._logger.debug("MessageList: 清空所有消息")

    def get_message_count(self) -> int:
        """获取消息总数"""
        return len(self._message_cards)

    def get_all_messages(self) -> list[dict]:
        """
        获取所有消息的数据

        Returns:
            消息数据列表
        """
        messages = []
        for card in self._message_cards:
            messages.append({
                "msg_type": card.get_message_type(),
                "content": card.get_content(),
                "is_finalized": card.is_finalized(),
            })
        return messages

    def start_streaming(self) -> None:
        """开始流式更新"""
        # 可以在这里添加流式更新的状态管理
        pass

    def stop_streaming(self) -> None:
        """停止流式更新"""
        if self._stream_task:
            self._stream_task.cancel()
            self._stream_task = None

    async def stream_append(self, text: str, delay: float = 0.01) -> None:
        """
        流式追加内容（异步方法）

        Args:
            text: 要追加的文本
            delay: 延迟时间（秒）
        """
        card = self.get_last_card()
        if card:
            card.append_content(text)
            # 添加小延迟，避免过于频繁的更新
            await asyncio.sleep(delay)

    def set_auto_scroll(self, auto_scroll: bool) -> None:
        """
        设置自动滚动

        Args:
            auto_scroll: 是否自动滚动
        """
        self._auto_scroll = auto_scroll
        self._list_view.auto_scroll = auto_scroll
        self._safe_update(self._list_view)