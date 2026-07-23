"""
悬浮聊天窗口组件

提供可拖拽的浮动聊天窗口，支持消息发送和显示。
使用 Flet 的 overlay 实现弹出式聊天窗口。
"""
from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING

import flet as ft

from config import get_config, set_config
from ui_flet.theme import get_color, get_theme_manager, ThemeMode, DEFAULT_SPACING_CONFIG
from ui_flet.components.message_list import MessageList
from logger import get_logger

if TYPE_CHECKING:
    pass


class FloatingChatWindow:
    """
    悬浮聊天窗口组件

    基于 Flet 的浮动聊天窗口，支持：
    - 可拖拽的浮动面板
    - 简化的消息列表
    - 基本对话功能
    - 窗口位置记忆

    使用方式（作为 Overlay）：
        chat_window = FloatingChatWindow(page)
        chat_window.set_on_send(my_send_callback)
        chat_window.show()  # 显示窗口
        chat_window.hide()  # 隐藏窗口
    """

    # 窗口配置键
    CONFIG_KEY_POS_X = "UI_FLET_FLOATING_CHAT_POS_X"
    CONFIG_KEY_POS_Y = "UI_FLET_FLOATING_CHAT_POS_Y"

    # 默认窗口尺寸
    DEFAULT_WIDTH = 400
    DEFAULT_HEIGHT = 500
    MIN_WIDTH = 300
    MIN_HEIGHT = 400

    # 标题栏高度
    TITLE_BAR_HEIGHT = 40

    def __init__(self, page: ft.Page):
        """
        初始化悬浮聊天窗口

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()

        # 主题
        self._theme_manager = get_theme_manager()
        self._colors = self._theme_manager.get_color_scheme()

        # 窗口尺寸
        self._width = self.DEFAULT_WIDTH
        self._height = self.DEFAULT_HEIGHT

        # 位置状态
        self._window_left: float = 0.0
        self._window_top: float = 0.0

        # 拖拽状态
        self._is_dragging = False
        self._drag_start_left = 0.0
        self._drag_start_top = 0.0
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0

        # 窗口可见性
        self._is_visible = False

        # 事件回调
        self._on_send: Optional[Callable[[str], None]] = None
        self._on_close: Optional[Callable[[], None]] = None

        # UI 控件引用
        self._message_list: MessageList | None = None
        self._input_field: ft.TextField | None = None
        self._send_button: ft.IconButton | None = None
        self._main_container: ft.Container | None = None

        # 初始化组件
        self._init_controls()
        self._init_position()

    def _init_controls(self):
        """初始化所有控件"""
        self._logger.info("FloatingChatWindow: 初始化控件")
        # 创建消息列表（提供复制回调，不提供朗读回调）
        self._message_list = MessageList(
            on_copy=self._on_message_copy,
            on_speak=None,
            auto_scroll=True,
        )

        # 创建输入框
        self._input_field = ft.TextField(
            hint_text="输入消息... (Enter 发送)",
            multiline=True,
            min_lines=1,
            max_lines=3,
            text_style=ft.TextStyle(
                color=self._colors.text,
                size=14,
            ),
            hint_style=ft.TextStyle(
                color=self._colors.text_muted,
                size=14,
            ),
            bgcolor=self._colors.bg_page,
            border_color=self._colors.border,
            focused_border_color=self._colors.primary,
            focused_bgcolor=self._colors.surface,
            border_radius=DEFAULT_SPACING_CONFIG.radius_md,
            content_padding=DEFAULT_SPACING_CONFIG.sm,
            expand=True,
            on_submit=self._on_input_submit,
        )

        # 创建发送按钮（与主窗口一致：透明背景 + 蓝色箭头）
        self._send_button = ft.IconButton(
            icon=ft.Icons.SEND,
            icon_color=self._colors.primary,
            tooltip="发送消息",
            on_click=self._on_send_click,
            width=26,
            height=26,
            icon_size=18,
            padding=0,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: "transparent"},
            ),
        )

        # 创建输入行（输入框 + 发送按钮）
        input_row = ft.Row(
            [
                self._input_field,
                self._send_button,
            ],
            spacing=DEFAULT_SPACING_CONFIG.sm,
            alignment=ft.MainAxisAlignment.END,
        )

        # 创建输入区域容器
        input_container = ft.Container(
            content=input_row,
            bgcolor=self._colors.surface,
            border=ft.Border(
                top=ft.BorderSide(1, self._colors.border),
            ),
            padding=DEFAULT_SPACING_CONFIG.sm,
        )

        # 创建标题栏
        title_bar = self._create_title_bar()

        # 创建主内容区（标题栏 + 消息列表 + 输入区域）
        main_content = ft.Column(
            [
                title_bar,
                self._message_list,
                input_container,
            ],
            spacing=0,
            expand=True,
        )

        # 创建主窗口容器
        self._main_container = ft.Container(
            content=main_content,
            width=self._width,
            height=self._height,
            bgcolor=self._colors.surface,
            border=ft.Border.all(1, self._colors.border),
            border_radius=DEFAULT_SPACING_CONFIG.radius_lg,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.2, "black"),
            ),
            left=self._window_left,
            top=self._window_top,
            visible=False,
            animate_position=200,
        )

        # 使用 GestureDetector 包装以支持拖拽
        self._gesture_detector = ft.GestureDetector(
            content=self._main_container,
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_pan_end=self._on_pan_end,
            drag_interval=0,
        )

    def _create_title_bar(self) -> ft.Container:
        """创建标题栏"""
        # 图标按钮
        icon_btn = ft.IconButton(
            icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
            icon_color=self._colors.primary,
            icon_size=20,
            tooltip="悬浮聊天",
        )

        # 标题文本
        title_text = ft.Text(
            "快速对话",
            size=14,
            color=self._colors.text,
            weight=ft.FontWeight.BOLD,
        )

        # 关闭按钮
        close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=self._colors.text_muted,
            icon_size=18,
            tooltip="关闭窗口",
            on_click=self._on_close_click,
        )

        # 标题栏容器
        title_bar = ft.Container(
            content=ft.Row(
                [
                    icon_btn,
                    title_text,
                    ft.Container(expand=True),
                    close_btn,
                ],
                spacing=DEFAULT_SPACING_CONFIG.sm,
                tight=True,
            ),
            bgcolor=self._colors.surface,
            border=ft.Border(
                bottom=ft.BorderSide(1, self._colors.border),
            ),
            padding=DEFAULT_SPACING_CONFIG.md,
            height=self.TITLE_BAR_HEIGHT,
        )

        return title_bar

    def _init_position(self):
        """初始化位置 - 从配置文件加载或使用默认位置"""
        self._logger.info("FloatingChatWindow: 初始化位置")
        try:
            # 尝试从配置文件加载位置
            pos_x = get_config(self.CONFIG_KEY_POS_X)
            pos_y = get_config(self.CONFIG_KEY_POS_Y)

            if pos_x and pos_y:
                self._window_left = float(pos_x)
                self._window_top = float(pos_y)
            else:
                # 默认位置：屏幕右下角
                self._set_default_position()

        except Exception as e:
            self._logger.warning(f"加载悬浮窗口位置失败: {e}")
            self._set_default_position()

        self._update_position()

    def _set_default_position(self):
        """设置默认位置（屏幕右下角）"""
        if self._page:
            window_width = self._page.window.width or 1200
            window_height = self._page.window.height or 800

            # 右下角，留出边距
            self._window_left = window_width - self._width - 20
            self._window_top = window_height - self._height - 20

    def _update_position(self):
        """更新窗口位置"""
        if self._main_container:
            self._main_container.left = self._window_left
            self._main_container.top = self._window_top

    def _save_position(self):
        """保存窗口位置到配置文件"""
        try:
            set_config(self.CONFIG_KEY_POS_X, str(int(self._window_left)))
            set_config(self.CONFIG_KEY_POS_Y, str(int(self._window_top)))
            self._logger.info(f"FloatingChatWindow: 保存位置 ({self._window_left}, {self._window_top})")
        except Exception as e:
            self._logger.warning(f"保存悬浮窗口位置失败: {e}")

    # ==================== 事件处理 ====================

    def _on_input_submit(self, e: ft.ControlEvent):
        """输入框提交事件（Enter 键）"""
        self._send_message()

    def _on_send_click(self, e: ft.ControlEvent):
        """发送按钮点击"""
        self._send_message()

    def _send_message(self):
        """发送消息"""
        if not self._input_field:
            return

        text = (self._input_field.value or "").strip()
        if not text:
            return

        self._logger.info(f"FloatingChatWindow: 发送消息: {text[:50]}...")

        # 添加用户消息到消息列表
        if self._message_list:
            self._message_list.add_message("user", text)

        # 清空输入框
        self._input_field.value = ""

        # 调用回调
        if self._on_send:
            self._on_send(text)

        self._page.update()

    def _on_close_click(self, e: ft.ControlEvent):
        """关闭按钮点击"""
        self.hide()
        if self._on_close:
            self._on_close()

    def _on_pan_start(self, e: ft.DragStartEvent):
        """开始拖拽"""
        self._is_dragging = False  # 重置状态
        self._drag_start_left = self._window_left
        self._drag_start_top = self._window_top
        # 使用 global_position 获取全局坐标
        self._drag_start_x = e.global_position.x
        self._drag_start_y = e.global_position.y
        self._logger.debug(f"开始拖拽: start_x={self._drag_start_x}, start_y={self._drag_start_y}")

    def _on_pan_update(self, e: ft.DragUpdateEvent):
        """拖拽更新"""
        # 获取当前位置
        current_x = e.global_position.x
        current_y = e.global_position.y

        # 计算偏移量
        dx = current_x - self._drag_start_x
        dy = current_y - self._drag_start_y

        # 标记为拖拽状态（移动距离超过阈值）
        if abs(dx) > 5 or abs(dy) > 5:
            self._is_dragging = True

        # 更新位置
        self._window_left = self._drag_start_left + dx
        self._window_top = self._drag_start_top + dy

        # 边界检测
        self._apply_boundary_constraints()

        # 更新UI（拖拽时不使用动画）
        self._main_container.animate_position = None
        self._update_position()
        self._page.update()

    def _on_pan_end(self, e: ft.DragEndEvent):
        """结束拖拽"""
        # 恢复动画
        self._main_container.animate_position = 200

        # 边界检测和边缘吸附
        self._snap_to_edge()

        # 保存位置
        self._save_position()

        self._logger.debug(f"结束拖拽: left={self._window_left}, top={self._window_top}")
        self._page.update()

    def _apply_boundary_constraints(self):
        """应用边界约束"""
        if not self._page:
            return

        # 获取窗口尺寸
        window_width = self._page.window.width or 1200
        window_height = self._page.window.height or 800

        # 左边界
        if self._window_left < 0:
            self._window_left = 0

        # 上边界
        if self._window_top < 0:
            self._window_top = 0

        # 右边界
        if self._window_left + self._width > window_width:
            self._window_left = window_width - self._width

        # 下边界
        if self._window_top + self._height > window_height:
            self._window_top = window_height - self._height

    def _snap_to_edge(self):
        """吸附到屏幕边缘"""
        if not self._page:
            return

        # 获取窗口尺寸
        window_width = self._page.window.width or 1200
        window_height = self._page.window.height or 800

        # 吸附阈值（距离边缘多少像素时触发吸附）
        snap_threshold = 50

        # 左右边缘吸附
        if self._window_left < snap_threshold:
            # 吸附到左边
            self._window_left = 10
        elif self._window_left + self._width > window_width - snap_threshold:
            # 吸附到右边
            self._window_left = window_width - self._width - 10

        # 上下边界约束（不自动吸附到上下边缘，只做边界限制）
        if self._window_top < 0:
            self._window_top = 10
        elif self._window_top + self._height > window_height:
            self._window_top = window_height - self._height - 10

        # 更新位置
        self._page.update()

    def _on_message_copy(self, text: str) -> None:
        """
        消息复制回调

        Args:
            text: 要复制的文本
        """
        self._page.set_clipboard(text)
        self._logger.info("悬浮窗口消息已复制到剪贴板")

    # ==================== 公共方法 ====================

    def get_control(self) -> ft.Control:
        """
        获取悬浮窗口控件

        Returns:
            ft.Control: 悬浮窗口容器控件
        """
        return self._gesture_detector

    def show(self):
        """显示悬浮窗口"""
        if not self._is_visible:
            self._is_visible = True
            self._main_container.visible = True
            self._page.update()
            self._logger.info("显示悬浮聊天窗口")

    def hide(self):
        """隐藏悬浮窗口"""
        if self._is_visible:
            self._is_visible = False
            self._main_container.visible = False
            self._page.update()
            self._logger.info("隐藏悬浮聊天窗口")

    def toggle(self):
        """切换窗口显示/隐藏"""
        if self._is_visible:
            self.hide()
        else:
            self.show()

    def is_visible(self) -> bool:
        """检查窗口是否可见"""
        return self._is_visible

    def set_on_send(self, callback: Callable[[str], None]):
        """
        设置发送回调函数

        Args:
            callback: 回调函数，接收 (text) 参数
        """
        self._on_send = callback

    def set_on_close(self, callback: Callable[[], None]):
        """
        设置关闭回调函数

        Args:
            callback: 回调函数
        """
        self._on_close = callback

    def add_message(self, msg_type: str, content: str):
        """
        添加消息到消息列表

        Args:
            msg_type: 消息类型（"user", "assistant", "tool", "think"）
            content: 消息内容
        """
        if self._message_list:
            self._message_list.add_message(msg_type, content)
            self._page.update()

    def clear_messages(self):
        """清空消息列表"""
        if self._message_list:
            self._message_list.clear_all()
            self._page.update()

    def set_input_placeholder(self, text: str):
        """
        设置输入框占位文本

        Args:
            text: 占位文本
        """
        if self._input_field:
            self._input_field.hint_text = text
            self._page.update()

    def focus_input(self):
        """聚焦到输入框"""
        if self._input_field:
            self._input_field.focus()
            self._page.update()

    def update_theme(self):
        """更新主题"""
        self._colors = self._theme_manager.get_color_scheme()

        # 更新输入框样式
        if self._input_field:
            self._input_field.text_style = ft.TextStyle(color=self._colors.text)
            self._input_field.hint_style = ft.TextStyle(color=self._colors.text_muted)
            self._input_field.bgcolor = self._colors.bg_page
            self._input_field.border_color = self._colors.border
            self._input_field.focused_border_color = self._colors.primary

        # 更新按钮样式
        if self._send_button:
            self._send_button.icon_color = self._colors.text_on_primary
            self._send_button.bgcolor = self._colors.primary

        # 更新消息列表主题
        if self._message_list:
            self._message_list.bgcolor = self._colors.bg_page

        # 更新容器样式
        if self._main_container:
            self._main_container.bgcolor = self._colors.surface
            self._main_container.border = ft.Border.all(1, self._colors.border)

        self._page.update()