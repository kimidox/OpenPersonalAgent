"""
悬浮球组件

提供可拖拽的悬浮球功能，支持右键菜单和事件回调。
"""
from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING
import flet as ft

from ui_flet.theme import get_color, get_theme_manager, ThemeMode

if TYPE_CHECKING:
    from ui_flet.views.floating_chat_window import FloatingChatWindow


class FloatingBall:
    """
    悬浮球组件

    基于 Flet 的可拖拽悬浮球，支持：
    - 拖拽移动
    - 边界检测和边缘吸附
    - 右键菜单
    - 事件回调

    使用方式（作为 Overlay）：
        floating_ball = FloatingBall(page)
        page.overlay.append(floating_ball.get_control())
        page.update()
    """

    def __init__(self, page: ft.Page):
        """
        初始化悬浮球

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = None

        # 悬浮球尺寸
        self._ball_size = 50

        # 位置状态
        self._ball_left: float = 0.0
        self._ball_top: float = 0.0

        # 拖拽状态
        self._is_dragging = False
        self._drag_start_left = 0.0
        self._drag_start_top = 0.0
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0

        # 录音状态
        self._is_recording = False

        # 聊天窗口引用
        self._chat_window: Optional[FloatingChatWindow] = None

        # 事件回调
        self._on_show_window: Optional[Callable[[], None]] = None
        self._on_start_recording: Optional[Callable[[], None]] = None
        self._on_stop_recording: Optional[Callable[[], None]] = None
        self._on_quit: Optional[Callable[[], None]] = None

        # 初始化组件
        self._init_logger()
        self._init_control()
        self._init_position()

    def _init_logger(self):
        """初始化日志器"""
        try:
            from logger import get_logger
            self._logger = get_logger()
        except ImportError:
            # 如果无法导入，使用空实现
            self._logger = None

    def _log(self, level: str, message: str):
        """记录日志"""
        if self._logger:
            getattr(self._logger, level)(f"FloatingBall: {message}")

    def _init_control(self):
        """初始化悬浮球控件"""
        self._log("info", "初始化悬浮球控件")
        # 获取主题颜色
        theme = get_theme_manager().current_theme
        primary_color = get_color("primary", theme)
        primary_hover_color = get_color("primary_hover", theme)

        # 创建悬浮球主体（内部容器）
        self._ball_inner = ft.Container(
            width=self._ball_size,
            height=self._ball_size,
            bgcolor=primary_color,
            border_radius=self._ball_size // 2,  # 圆形
            opacity=0.85,
            animate_opacity=300,
            content=ft.Icon(
                ft.Icons.CHAT_BUBBLE,
                color="white",
                size=24,
            ),
            ink=True,
            on_hover=lambda e: self._on_ball_hover(e, primary_hover_color, primary_color),
        )

        # 使用 GestureDetector 包装悬浮球以支持拖拽
        self._ball_container = ft.GestureDetector(
            content=self._ball_inner,
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_pan_end=self._on_pan_end,
            on_tap=self._on_ball_click,
            drag_interval=0,  # 实时更新
        )

        # 创建菜单按钮（保留引用以便动态更新）
        self._recording_menu_btn = ft.TextButton(
            "开始录音",
            icon=ft.Icons.MIC,
            on_click=self._on_menu_recording,
        )

        # 获取主题颜色
        colors = get_theme_manager().get_color_scheme()

        # 创建菜单面板（使用 Container 实现）
        self._menu_visible = False
        self._menu_panel = ft.Container(
            content=ft.Column(
                [
                    ft.TextButton(
                        "显示主窗口",
                        icon=ft.Icons.HOME,
                        on_click=self._on_menu_show_window,
                    ),
                    self._recording_menu_btn,
                    ft.Divider(),
                    ft.TextButton(
                        "退出",
                        icon=ft.Icons.EXIT_TO_APP,
                        on_click=self._on_menu_quit,
                    ),
                ],
                spacing=5,
            ),
            bgcolor=colors.surface,
            border_radius=10,
            padding=10,
            visible=False,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.2, "black"),
            ),
        )

        # 包装悬浮球和菜单
        self._stack = ft.Stack(
            controls=[self._ball_container, self._menu_panel],
            width=self._ball_size,
            height=self._ball_size,
        )

        # 主容器（用于定位）
        self._main_container = ft.Container(
            content=self._stack,
            left=self._ball_left,
            top=self._ball_top,
            width=self._ball_size,
            height=self._ball_size,
            animate_position=200,  # 动画持续时间（毫秒）
        )

    def _init_position(self):
        """初始化位置 - 默认屏幕右下角"""
        if self._page:
            # 获取窗口尺寸
            window_width = self._page.window.width or 1200
            window_height = self._page.window.height or 800

            # 右下角，留出边距
            self._ball_left = window_width - self._ball_size - 20
            self._ball_top = window_height - self._ball_size - 20

            self._update_position()

    def _update_position(self):
        """更新悬浮球位置"""
        if self._main_container:
            self._main_container.left = self._ball_left
            self._main_container.top = self._ball_top

    def get_control(self) -> ft.Control:
        """
        获取悬浮球控件

        Returns:
            ft.Control: 悬浮球容器控件
        """
        return self._main_container

    # ==================== 事件处理 ====================

    def _on_ball_hover(self, e: ft.ControlEvent, hover_color: str, normal_color: str):
        """悬浮球悬停事件"""
        if e.data == "true":
            self._ball_inner.bgcolor = hover_color
            self._ball_inner.opacity = 1.0
        else:
            self._ball_inner.bgcolor = normal_color
            self._ball_inner.opacity = 0.85
        self._page.update()

    def _on_ball_click(self, e: ft.ControlEvent):
        """悬浮球点击事件"""
        # 如果是拖拽后的点击，不触发（通过 _is_dragging 判断）
        if not self._is_dragging:
            self._log("info", "球被点击")
            # 打开聊天窗口
            self._toggle_chat_window()

    def _on_pan_start(self, e: ft.DragStartEvent):
        """开始拖拽"""
        self._is_dragging = False  # 重置状态
        self._drag_start_left = self._ball_left
        self._drag_start_top = self._ball_top
        # 使用 global_position 获取全局坐标
        self._drag_start_x = e.global_position.x
        self._drag_start_y = e.global_position.y
        self._log("debug", f"开始拖拽: start_x={self._drag_start_x}, start_y={self._drag_start_y}")

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
        self._ball_left = self._drag_start_left + dx
        self._ball_top = self._drag_start_top + dy

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

        self._log("debug", f"结束拖拽: left={self._ball_left}, top={self._ball_top}")
        self._page.update()

    def _apply_boundary_constraints(self):
        """应用边界约束"""
        if not self._page:
            return

        # 获取窗口尺寸
        window_width = self._page.window.width or 1200
        window_height = self._page.window.height or 800

        # 左边界
        if self._ball_left < 0:
            self._ball_left = 0

        # 上边界
        if self._ball_top < 0:
            self._ball_top = 0

        # 右边界
        if self._ball_left + self._ball_size > window_width:
            self._ball_left = window_width - self._ball_size

        # 下边界
        if self._ball_top + self._ball_size > window_height:
            self._ball_top = window_height - self._ball_size

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
        if self._ball_left < snap_threshold:
            # 吸附到左边
            self._ball_left = 10
        elif self._ball_left + self._ball_size > window_width - snap_threshold:
            # 吸附到右边
            self._ball_left = window_width - self._ball_size - 10

        # 上下边界约束（不自动吸附到上下边缘，只做边界限制）
        if self._ball_top < 0:
            self._ball_top = 10
        elif self._ball_top + self._ball_size > window_height:
            self._ball_top = window_height - self._ball_size - 10

        # 更新位置
        self._update_position()

    # ==================== 菜单相关 ====================

    def _show_menu(self):
        """显示菜单"""
        self._menu_visible = True
        self._menu_panel.visible = True
        self._log("info", "显示菜单")
        self._menu_panel.left = self._ball_left + self._ball_size + 5
        self._menu_panel.top = self._ball_top
        self._page.update()

    def _hide_menu(self):
        """隐藏菜单"""
        self._menu_visible = False
        self._menu_panel.visible = False
        self._log("info", "隐藏菜单")
        self._page.update()

    def _on_menu_show_window(self, e: ft.ControlEvent):
        """显示主窗口菜单项点击"""
        self._log("info", "显示主窗口")
        self._hide_menu()
        if self._on_show_window:
            self._on_show_window()

    def _on_menu_recording(self, e: ft.ControlEvent):
        """录音菜单项点击"""
        if self._is_recording:
            # 停止录音
            self._log("info", "停止录音")
            self._is_recording = False
            self._recording_menu_btn.text = "开始录音"
            self._recording_menu_btn.icon = ft.Icons.MIC
            if self._on_stop_recording:
                self._on_stop_recording()
        else:
            # 开始录音
            self._log("info", "开始录音")
            self._is_recording = True
            self._recording_menu_btn.text = "停止录音"
            self._recording_menu_btn.icon = ft.Icons.STOP
            if self._on_start_recording:
                self._on_start_recording()

        self._page.update()

    def _on_menu_quit(self, e: ft.ControlEvent):
        """退出菜单项点击"""
        self._log("info", "退出应用")
        self._hide_menu()
        if self._on_quit:
            self._on_quit()

    # ==================== 公共方法 ====================

    def set_chat_window(self, chat_window: FloatingChatWindow):
        """
        设置聊天窗口引用

        Args:
            chat_window: FloatingChatWindow 实例
        """
        self._chat_window = chat_window

    def _toggle_chat_window(self):
        """切换聊天窗口显示/隐藏"""
        if self._chat_window:
            self._chat_window.toggle()
            self._log("info", f"切换聊天窗口: {'显示' if self._chat_window.is_visible() else '隐藏'}")

    def set_on_show_window(self, callback: Callable[[], None]):
        """设置显示主窗口回调"""
        self._on_show_window = callback

    def set_on_start_recording(self, callback: Callable[[], None]):
        """设置开始录音回调"""
        self._on_start_recording = callback

    def set_on_stop_recording(self, callback: Callable[[], None]):
        """设置停止录音回调"""
        self._on_stop_recording = callback

    def set_on_quit(self, callback: Callable[[], None]):
        """设置退出应用回调"""
        self._on_quit = callback

    def show(self):
        """显示悬浮球"""
        if self._main_container:
            self._main_container.visible = True
            self._page.update()

    def hide(self):
        """隐藏悬浮球"""
        if self._main_container:
            self._main_container.visible = False
            self._page.update()

    def update_theme(self):
        """更新主题"""
        theme = get_theme_manager().current_theme
        primary_color = get_color("primary", theme)
        primary_hover_color = get_color("primary_hover", theme)

        self._ball_inner.bgcolor = primary_color
        # 保存颜色供悬停使用
        self._ball_inner.data = {
            "primary": primary_color,
            "hover": primary_hover_color,
        }
        self._page.update()

    def set_icon(self, icon: str, color: str = "white", size: int = 24):
        """
        设置悬浮球图标

        Args:
            icon: 图标名称（字符串）
            color: 图标颜色
            size: 图标大小
        """
        if self._ball_inner and isinstance(self._ball_inner.content, ft.Icon):
            self._ball_inner.content.name = icon
            self._ball_inner.content.color = color
            self._ball_inner.content.size = size
            self._page.update()

    def set_size(self, size: int):
        """
        设置悬浮球大小

        Args:
            size: 直径（像素）
        """
        self._ball_size = size

        if self._ball_inner:
            self._ball_inner.width = size
            self._ball_inner.height = size
            self._ball_inner.border_radius = size // 2

        if self._stack:
            self._stack.width = size
            self._stack.height = size

        if self._main_container:
            self._main_container.width = size
            self._main_container.height = size

        self._page.update()