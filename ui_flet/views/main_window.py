"""
Flet 主窗口视图

提供应用程序的主窗口布局，包括侧边栏和主内容区。
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

import config
from config import get_config, set_config
from logger import get_logger
from executor import Executor
from memory import SqliteMemory
from skill_agent import SkillAgent, SKILL_AGENT_AWAITING_USER_REPLY
from ui_flet.state import AppState, StreamType
from ui_flet.theme import ThemeManager, get_color
from ui_flet.components.message_list import MessageList
from ui_flet.components.input_area import InputArea
from ui_flet.utils.file_upload_manager import UploadedFileInfo
from ui_flet.components.await_user_card import AwaitUserCard
from ui_flet.components.conversation_sidebar import ConversationSidebar
from ui_flet.views.floating_chat_window import FloatingChatWindow
from ui_flet.views.settings_dialog import SettingsDialog

if TYPE_CHECKING:
    from skill_agent import SkillAgent


class MainWindow:
    """
    主窗口视图类

    管理主窗口的布局和交互，包括：
    - 左侧会话侧边栏
    - 右侧主内容区（消息列表 + 输入区域）
    - 悬浮聊天窗口
    - 窗口状态保存/恢复
    - 窗口控制（最小化/关闭）
    """

    # 窗口状态配置键
    CONFIG_KEY_WIDTH = "UI_FLET_WINDOW_WIDTH"
    CONFIG_KEY_HEIGHT = "UI_FLET_WINDOW_HEIGHT"
    CONFIG_KEY_POS_X = "UI_FLET_WINDOW_POS_X"
    CONFIG_KEY_POS_Y = "UI_FLET_WINDOW_POS_Y"

    # 默认窗口尺寸
    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 800
    MIN_WIDTH = 800
    MIN_HEIGHT = 600

    # 侧边栏宽度（与旧版 PySide6 前端一致：固定 182px）
    SIDEBAR_WIDTH = 182
    SIDEBAR_MIN_WIDTH = 168
    SIDEBAR_MAX_WIDTH = 224

    def __init__(self, page: ft.Page) -> None:
        """
        初始化主窗口

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._logger.info("MainWindow: 开始初始化")

        # 状态管理
        self._app_state = AppState()
        self._setup_stream_callbacks()

        # 主题管理
        self._theme_manager = ThemeManager()

        # 初始化后端组件
        self._init_backend_components()

        # UI 组件引用
        self._conversation_sidebar: ConversationSidebar | None = None
        self._sidebar_container: ft.Container | None = None
        self._sidebar_toggle_btn: ft.IconButton | None = None
        self._message_list: MessageList | None = None
        self._input_area: InputArea | None = None
        self._floating_chat_window: FloatingChatWindow | None = None

        # 侧边栏折叠状态
        self._sidebar_collapsed = False

        # 设置对话框
        self._settings_dialog: SettingsDialog | None = None

        # 工作线程管理
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 录音实时识别文本缓冲区
        self._recording_text: str = ""

        # 流式打字机任务
        self._stream_typing_task: asyncio.Task | None = None
        self._stream_typing_active = False
        # 打字机目标卡片：用于把"打字机只更新最后一条卡片"改为"打字机只更新该具体卡片"，
        # 避免 LLM 在一个 step 内既输出思考文本又调用工具时，旧打字机任务把
        # 已积累的 assistant 文本写入随后追加的 tool_call/tool 卡片中。
        self._current_typing_card: Any = None
        # 打字机代数计数器：每次启动新任务时 +1，typing_loop 在每轮迭代检查；
        # 配合 _stream_typing_active，可保证旧任务在收到 _stop_stream_typing
        # 信号后立即退出，不会因为后续 _start_stream_typing 再次把 active
        # 置 True 而"复活"。
        self._typing_generation: int = 0

        # 初始化窗口配置
        self._setup_window()
        self._setup_window_events()

        # 创建布局
        self._build_layout()

        # 异步加载初始会话
        self._logger.info("MainWindow: 开始异步加载初始会话")
        self._page.run_task(self._load_initial_conversations_async)
        self._logger.info("MainWindow: 初始化完成")

    def _setup_window(self) -> None:
        """设置窗口基础配置"""
        self._page.title = "PersonalWindowGLM"

        # 加载窗口状态
        self._load_window_state()

        # 设置最小尺寸
        self._page.window.min_width = self.MIN_WIDTH
        self._page.window.min_height = self.MIN_HEIGHT

        # 防止直接关闭
        self._page.window.prevent_close = True

        # 应用主题
        self._apply_theme()

    def _init_backend_components(self) -> None:
        """初始化后端组件（SkillAgent、Executor、Memory）"""
        try:
            self._logger.info("初始化后端组件...")

            # 初始化 Executor
            self.work_dir = config.WORKER_DIR
            self.executor = Executor(self.work_dir)
            self._logger.info(f"Executor 初始化完成: {self.work_dir}")

            # 初始化 Memory
            self._memory = SqliteMemory(username=config.DEFAULT_SKILL_AGENT_USER)
            self._logger.info(f"Memory 初始化完成: {config.DEFAULT_SKILL_AGENT_USER}")

            # 初始化 SkillAgent
            self.skill_agent = SkillAgent(
                self.work_dir,
                executor=self.executor,
                memory=self._memory,
                username=config.DEFAULT_SKILL_AGENT_USER,
            )
            self._logger.info("SkillAgent 初始化完成")

        except Exception:
            self._logger.exception("后端组件初始化失败")
            # 即使初始化失败，也要创建基本组件以避免程序崩溃
            self.work_dir = config.WORKER_DIR
            self.executor = None
            self._memory = None
            self.skill_agent = None

    def _setup_window_events(self) -> None:
        """设置窗口事件处理"""
        self._page.window.on_event = self._on_window_event

    def _on_window_event(self, e) -> None:
        """
        窗口事件处理器

        Args:
            e: 窗口事件对象
        """
        event_type = e.type if hasattr(e, 'type') else None
        if event_type == ft.WindowEventType.CLOSE:
            self._handle_close_request()
        elif event_type == ft.WindowEventType.MINIMIZE:
            self._handle_minimize()
        elif event_type in (ft.WindowEventType.RESIZE, ft.WindowEventType.RESIZED):
            self._save_window_state()

    def _handle_close_request(self) -> None:
        """处理关闭请求"""
        # 显示确认对话框
        self._show_close_confirmation()

    def _handle_minimize(self) -> None:
        """处理最小化"""
        self._logger.info("窗口最小化")
        self._save_window_state()

    def _show_close_confirmation(self) -> None:
        """显示关闭确认对话框"""
        def on_minimize(e):
            """最小化到任务栏"""
            self._page.window.minimized = True
            self._dismiss_close_dialog()
            self._page.update()

        async def on_floating_ball(e):
            """进入悬浮球模式"""
            self._dismiss_close_dialog()
            # 保存窗口状态
            self._save_window_state()
            # 隐藏主窗口
            self._page.window.minimized = True
            self._page.window.visible = False
            self._page.update()
            self._logger.info("进入悬浮球模式")
            # 启动悬浮球（通过调用 main 模块的函数）
            from ui_flet import main as main_module
            if hasattr(main_module, '_start_floating_ball_mode'):
                main_module._start_floating_ball_mode()

        async def on_close(e):
            """直接关闭"""
            self._save_window_state()
            self._dismiss_close_dialog()
            self._page.window.prevent_close = False
            await self._page.window.close()

        # 创建对话框
        self._close_confirmation_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("关闭确认"),
            content=ft.Text("请选择关闭方式："),
            actions=[
                ft.TextButton("最小化到任务栏", on_click=on_minimize),
                ft.TextButton("悬浮球模式", on_click=on_floating_ball),
                ft.TextButton("直接关闭", on_click=on_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(self._close_confirmation_dialog)
        self._close_confirmation_dialog.open = True
        self._page.update()

    def _dismiss_close_dialog(self) -> None:
        """关闭对话框"""
        if hasattr(self, '_close_confirmation_dialog') and self._close_confirmation_dialog:
            self._close_confirmation_dialog.open = False
            self._page.update()

    def _load_window_state(self) -> None:
        """从配置加载窗口状态"""
        try:
            width = get_config(self.CONFIG_KEY_WIDTH)
            height = get_config(self.CONFIG_KEY_HEIGHT)
            pos_x = get_config(self.CONFIG_KEY_POS_X)
            pos_y = get_config(self.CONFIG_KEY_POS_Y)

            # 设置尺寸
            if width and height:
                self._page.window.width = int(width)
                self._page.window.height = int(height)
            else:
                self._page.window.width = self.DEFAULT_WIDTH
                self._page.window.height = self.DEFAULT_HEIGHT

            # 设置位置（带有效性验证）
            if pos_x and pos_y:
                window_x = int(pos_x)
                window_y = int(pos_y)
                window_w = int(self._page.window.width)
                window_h = int(self._page.window.height)

                # 验证窗口位置是否有效
                if self._is_window_position_valid(window_x, window_y, window_w, window_h):
                    self._page.window.left = window_x
                    self._page.window.top = window_y
                    self._logger.info(f"窗口位置已恢复: ({window_x}, {window_y})")
                else:
                    # 位置无效，居中显示
                    self._center_window()
                    self._logger.warning(
                        f"窗口位置无效 ({window_x}, {window_y})，已居中显示"
                    )
            else:
                # 没有保存的位置，居中显示
                self._center_window()
                self._logger.info("未找到保存的窗口位置，居中显示")

        except Exception as e:
            self._logger.warning(f"加载窗口状态失败: {e}")
            self._page.window.width = self.DEFAULT_WIDTH
            self._page.window.height = self.DEFAULT_HEIGHT
            self._center_window()

    def _is_window_position_valid(
        self, x: int, y: int, width: int, height: int
    ) -> bool:
        """
        验证窗口位置是否在屏幕范围内

        Args:
            x: 窗口左上角 X 坐标
            y: 窗口左上角 Y 坐标
            width: 窗口宽度
            height: 窗口高度

        Returns:
            True 如果位置有效（至少部分可见），False 如果完全在屏幕外
        """
        try:
            # 尝试使用 screeninfo 获取多显示器信息
            try:
                from screeninfo import get_monitors

                monitors = get_monitors()
                if monitors:
                    for monitor in monitors:
                        # 检查窗口是否与任一显示器的工作区域有交集
                        # 允许窗口部分超出屏幕，但至少要有一定比例可见
                        min_visible_width = min(width, 200)  # 至少 200px 宽度可见
                        min_visible_height = min(height, 100)  # 至少 100px 高度可见

                        # 窗口右边界和下边界
                        window_right = x + width
                        window_bottom = y + height

                        # 显示器边界（使用工作区域，排除任务栏）
                        monitor_right = monitor.x + monitor.width
                        monitor_bottom = monitor.y + monitor.height

                        # 检查水平方向是否有足够的可见区域
                        horizontal_visible = max(
                            0,
                            min(window_right, monitor_right)
                            - max(x, monitor.x),
                        )
                        # 检查垂直方向是否有足够的可见区域
                        vertical_visible = max(
                            0,
                            min(window_bottom, monitor_bottom)
                            - max(y, monitor.y),
                        )

                        # 如果在任一显示器上有足够的可见区域，则位置有效
                        if (
                            horizontal_visible >= min_visible_width
                            and vertical_visible >= min_visible_height
                        ):
                            self._logger.info(
                                f"窗口位置在显示器 {monitor.name} 范围内有效"
                            )
                            return True

                    self._logger.info(
                        f"窗口位置 ({x}, {y}) 不在任何显示器范围内"
                    )
                    return False

            except ImportError:
                # screeninfo 未安装，使用 tkinter 获取主显示器尺寸
                self._logger.debug("screeninfo 未安装，使用 tkinter 获取屏幕尺寸")
                import tkinter as tk

                root = tk.Tk()
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                root.destroy()

                # 简单检查：窗口是否在主显示器上有足够的可见区域
                min_visible_width = min(width, 200)
                min_visible_height = min(height, 100)

                # 检查水平方向
                horizontal_visible = max(
                    0, min(x + width, screen_width) - max(x, 0)
                )
                # 检查垂直方向
                vertical_visible = max(
                    0, min(y + height, screen_height) - max(y, 0)
                )

                is_valid = (
                    horizontal_visible >= min_visible_width
                    and vertical_visible >= min_visible_height
                )

                if is_valid:
                    self._logger.info(
                        f"窗口位置在主显示器范围内有效 (屏幕: {screen_width}x{screen_height})"
                    )
                else:
                    self._logger.info(
                        f"窗口位置 ({x}, {y}) 不在主显示器范围内 (屏幕: {screen_width}x{screen_height})"
                    )

                return is_valid

        except Exception as e:
            self._logger.warning(f"验证窗口位置时出错: {e}，默认视为有效")
            return True  # 出错时保守处理，不改变位置

    def _center_window(self) -> None:
        """将窗口居中显示在主显示器上"""
        try:
            import tkinter as tk

            root = tk.Tk()
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            root.destroy()

            window_width = int(self._page.window.width)
            window_height = int(self._page.window.height)

            # 计算居中位置
            x = (screen_width - window_width) // 2
            y = (screen_height - window_height) // 2

            self._page.window.left = x
            self._page.window.top = y

            self._logger.info(
                f"窗口已居中: ({x}, {y}), 屏幕: {screen_width}x{screen_height}"
            )

        except Exception as e:
            self._logger.warning(f"居中窗口失败: {e}")
            # 使用默认位置（Flet 会自动处理）
            pass

    def _save_window_state(self) -> None:
        """保存窗口状态到配置"""
        try:
            set_config(self.CONFIG_KEY_WIDTH, str(int(self._page.window.width)))
            set_config(self.CONFIG_KEY_HEIGHT, str(int(self._page.window.height)))
            set_config(self.CONFIG_KEY_POS_X, str(int(self._page.window.left)))
            set_config(self.CONFIG_KEY_POS_Y, str(int(self._page.window.top)))
        except Exception as e:
            self._logger.warning(f"保存窗口状态失败: {e}")

    def _has_saved_position(self) -> bool:
        """检查是否有保存的窗口位置"""
        return bool(get_config(self.CONFIG_KEY_POS_X) and get_config(self.CONFIG_KEY_POS_Y))

    def _apply_theme(self) -> None:
        """应用主题样式"""
        colors = self._theme_manager.get_color_scheme()

        # 设置页面背景色
        self._page.bgcolor = colors.bg_page
        self._logger.info(f"设置页面背景色: {colors.bg_page}")

        # 根据主题设置 Flet 主题
        if self._theme_manager.current_theme.value == "dark":
            self._page.theme_mode = ft.ThemeMode.DARK
        else:
            self._page.theme_mode = ft.ThemeMode.LIGHT
        self._logger.info(f"设置主题模式: {self._page.theme_mode}")

    def _build_layout(self) -> None:
        """构建主窗口布局（与旧版 PySide6 前端结构保持一致）"""
        self._logger.info("MainWindow: 开始构建布局")
        colors = self._theme_manager.get_color_scheme()

        # 创建会话侧边栏
        self._conversation_sidebar = ConversationSidebar(
            page=self._page,
            session_state=self._app_state.session,
            on_conversation_changed=self._handle_conversation_changed,
            on_new_conversation=self._handle_new_conversation,
            on_delete_conversation=self._handle_delete_conversation,
            on_rename_conversation=self._handle_rename_conversation,
            on_settings_click=self._on_settings_click,
        )

        # 侧边栏容器（旧版 PySide6 无边距，内边距由 ConversationSidebar 自身控制）
        self._sidebar_container = ft.Container(
            content=self._conversation_sidebar,
            width=self.SIDEBAR_WIDTH,
            bgcolor=colors.surface,
            border=ft.Border(
                right=ft.BorderSide(1, colors.border),
            ),
            padding=0,
        )

        # 侧边栏折叠切换按钮（与旧版 PySide6 一致：宽 24，高度接近默认按钮）
        self._sidebar_toggle_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            icon_color=colors.text_muted,
            icon_size=16,
            tooltip="收起侧边栏",
            on_click=self._toggle_sidebar,
            width=24,
            height=28,
        )

        # 左侧容器（侧边栏 + 切换按钮）
        left_container = ft.Row(
            [
                self._sidebar_container,
                self._sidebar_toggle_btn,
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # 创建消息列表
        self._message_list = MessageList(
            on_copy=self._on_message_copy,
            on_speak=self._on_message_speak,
            auto_scroll=True,
        )

        # 创建等待用户回复卡片
        self._await_user_card = AwaitUserCard()

        # 创建输入区域
        self._input_area = InputArea(self._page)
        self._input_area.set_on_send(self._on_message_send)

        # 右侧聊天区域（消息列表 + 等待用户卡片 + 输入区域，与旧版 PySide6 一致：内边距 10，间距 8）
        chat_content = ft.Column(
            [
                self._message_list,
                self._await_user_card,
                self._input_area.get_control(),
            ],
            spacing=8,
            expand=True,
        )

        chat_container = ft.Container(
            content=chat_content,
            padding=10,
            expand=True,
        )

        # 主布局容器（左侧容器 + 右侧聊天区域）
        main_layout = ft.Row(
            [
                left_container,
                chat_container,
            ],
            spacing=0,
            expand=True,
        )

        # 创建悬浮聊天窗口
        self._create_floating_chat_window()

        # 添加到页面
        self._page.add(main_layout)
        self._logger.info(f"已添加主布局到页面，controls 数量: {len(self._page.controls)}")
        self._logger.info("MainWindow: 布局构建完成")

    def _toggle_sidebar(self, e: ft.ControlEvent) -> None:
        """切换侧边栏折叠/展开状态"""
        self._sidebar_collapsed = not self._sidebar_collapsed
        colors = self._theme_manager.get_color_scheme()

        if self._sidebar_collapsed:
            self._sidebar_container.width = 0
            self._sidebar_container.visible = False
            self._sidebar_toggle_btn.icon = ft.Icons.CHEVRON_RIGHT
            self._sidebar_toggle_btn.tooltip = "展开侧边栏"
        else:
            self._sidebar_container.width = self.SIDEBAR_WIDTH
            self._sidebar_container.visible = True
            self._sidebar_toggle_btn.icon = ft.Icons.CHEVRON_LEFT
            self._sidebar_toggle_btn.tooltip = "收起侧边栏"

        self._logger.info(f"侧边栏{'收起' if self._sidebar_collapsed else '展开'}")
        self._page.update()

    def _create_floating_chat_window(self) -> None:
        """创建悬浮聊天窗口"""
        # 创建悬浮聊天窗口实例
        self._floating_chat_window = FloatingChatWindow(self._page)

        # 设置消息发送回调
        self._floating_chat_window.set_on_send(self._on_floating_chat_send)

        # 将悬浮聊天窗口添加到页面 overlay
        self._page.overlay.append(self._floating_chat_window.get_control())

    # ==================== 消息发送回调 ====================

    def _on_message_send(self, text: str, files: list[UploadedFileInfo]) -> None:
        """
        消息发送回调

        Args:
            text: 消息文本
            files: 上传的文件列表
        """
        self._logger.info(f"发送消息: {text[:50] if text else ''}...")
        if files:
            self._logger.info(f"附带文件: {[f.name for f in files]}")

        # 检查 SkillAgent 是否初始化
        if not self.skill_agent:
            self._logger.error("SkillAgent 未初始化")
            return

        # 检查是否有正在运行的任务
        if self._worker_thread and self._worker_thread.is_alive():
            # 检查是否是 ask_user 等待回复场景
            if self._is_awaiting_user_reply():
                # 允许用户回复继续处理
                self._logger.info("检测到 ask_user 等待回复，允许用户回复")
            else:
                self._logger.warning("已有任务在运行，忽略新的发送请求")
                return

        # 获取或创建当前会话
        conversation_id = self._app_state.session.get_current_conversation()
        if not conversation_id:
            # 创建新会话
            conversation_id = self._create_new_conversation()
            if not conversation_id:
                self._logger.error("创建新会话失败")
                return

        # 清空输入框
        if self._input_area:
            self._input_area.clear()

        # 添加用户消息到消息列表
        if self._message_list:
            self._message_list.add_message("user", text)

        # 设置 UI 状态为运行中
        self._app_state.ui.set_task_running(True)

        # 设置发送按钮为推理状态（红色方块）
        if self._input_area:
            self._input_area.set_inference_running(True)

        # 启动工作线程处理 SkillAgent 调用
        self._start_skill_agent_worker(text, conversation_id)

    def _on_floating_chat_send(self, text: str) -> None:
        """
        悬浮聊天窗口消息发送回调

        Args:
            text: 消息文本
        """
        self._logger.info(f"悬浮聊天窗口发送消息: {text[:50] if text else ''}...")

        # 检查 SkillAgent 是否初始化
        if not self.skill_agent:
            self._logger.error("SkillAgent 未初始化")
            return

        # 检查是否有正在运行的任务
        if self._worker_thread and self._worker_thread.is_alive():
            # 检查是否是 ask_user 等待回复场景
            if self._is_awaiting_user_reply():
                # 允许用户回复继续处理
                self._logger.info("检测到 ask_user 等待回复，允许用户回复")
            else:
                self._logger.warning("已有任务在运行，忽略新的发送请求")
                return

        # 获取或创建当前会话
        conversation_id = self._app_state.session.get_current_conversation()
        if not conversation_id:
            # 创建新会话
            conversation_id = self._create_new_conversation()
            if not conversation_id:
                self._logger.error("创建新会话失败")
                return

        # 添加用户消息到悬浮窗口
        if self._floating_chat_window:
            self._floating_chat_window.add_message("user", text)

        # 设置 UI 状态为运行中
        self._app_state.ui.set_task_running(True)

        # 设置发送按钮为推理状态（红色方块）
        if self._input_area:
            self._input_area.set_inference_running(True)

        # 启动工作线程处理 SkillAgent 调用
        self._start_skill_agent_worker(text, conversation_id)

    # ==================== 会话管理回调 ====================

    def _handle_conversation_changed(self, conversation_id: str) -> None:
        """
        会话切换回调

        Args:
            conversation_id: 会话ID
        """
        self._logger.info(f"切换到会话: {conversation_id}")
        # 切换到指定会话
        self._switch_to_conversation(conversation_id)

    def _handle_new_conversation(self) -> None:
        """创建新会话回调"""
        self._logger.info("创建新会话")

        # 检查是否有正在运行的任务
        if self._worker_thread and self._worker_thread.is_alive():
            self._logger.warning("当前仍有对话在执行，请结束后再新建会话")
            # 可以添加一个提示对话框
            return

        # 创建新会话
        self._create_new_conversation()

    def _handle_delete_conversation(self, conversation_id: str) -> None:
        """
        删除会话回调

        Args:
            conversation_id: 会话ID
        """
        self._logger.info(f"删除会话: {conversation_id}")

        # 检查是否有正在运行的任务
        if self._worker_thread and self._worker_thread.is_alive():
            self._logger.warning("该会话正在执行中，请结束后再删除")
            self._show_snackbar("该会话正在执行中，请结束后再删除", error=True)
            return

        # 检查是否只剩一个会话
        if self._app_state.session.conversation_count() < 1:
            self._logger.warning("至少保留一个会话")
            self._show_snackbar("至少保留一个会话", error=True)
            return

        # 记录当前会话 ID（用于后续判断是否需要清空消息列表）
        current_cid = self._app_state.session.get_current_conversation()
        is_current_conversation = current_cid == conversation_id

        # Step 1: 如果删除的是当前会话，先切换到另一个会话
        if is_current_conversation:
            all_sessions = self._app_state.session.get_all_conversations()
            for session in all_sessions:
                if session.conversation_id != conversation_id:
                    self._switch_to_conversation(session.conversation_id)
                    break

        # Step 2: 先执行数据库删除（确保持久化成功后再更新 UI）
        try:
            if self._memory:
                self._memory.clear_conversation(conversation_id)
            self._logger.info(f"数据库删除成功: {conversation_id}")
        except Exception as e:
            self._logger.exception(f"数据库删除失败: {e}")
            self._show_snackbar("删除会话失败，请重试", error=True)
            # 数据库删除失败，不更新 UI，保持原状态
            return

        # Step 3: 数据库删除成功后，更新 UI 和状态
        # 更新侧边栏
        if self._conversation_sidebar:
            self._conversation_sidebar.remove_conversation(conversation_id)

        # 从状态管理中移除
        self._app_state.session.remove_conversation(conversation_id)

        # 清空消息列表（如果删除的是当前会话）
        if is_current_conversation and self._message_list:
            self._message_list.clear()

        self._logger.info(f"已删除会话: {conversation_id}")
        self._show_snackbar("会话已删除")

    def _show_snackbar(self, message: str, error: bool = False) -> None:
        """
        显示提示消息

        Args:
            message: 提示消息内容
            error: 是否为错误消息
        """
        colors = ThemeManager().get_color_scheme()
        self._page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=colors.text_on_primary),
            bgcolor=colors.error if error else colors.success,
        )
        self._page.snack_bar.open = True
        self._page.update()

    def _handle_rename_conversation(self, conversation_id: str, new_title: str) -> None:
        """
        重命名会话回调

        Args:
            conversation_id: 会话ID
            new_title: 新的会话标题
        """
        self._logger.info(f"重命名会话: {conversation_id} -> {new_title}")

        try:
            # 更新状态管理中的标题
            self._app_state.session.update_conversation_title(
                conversation_id, new_title
            )

            # 持久化到数据库
            if self._memory:
                self._memory.update_conversation_title(conversation_id, new_title)

            # 同步更新侧边栏 UI
            if self._conversation_sidebar:
                self._conversation_sidebar.update_conversation_title(
                    conversation_id, new_title
                )

            self._logger.info(f"已重命名会话: {conversation_id}")

        except Exception as e:
            self._logger.exception(f"重命名会话失败: {e}")

    # ==================== 消息复制和朗读 ====================

    def _on_message_copy(self, text: str) -> None:
        """
        消息复制回调

        Args:
            text: 要复制的文本
        """
        self._page.set_clipboard(text)
        self._logger.info("消息已复制到剪贴板")

    def _on_message_speak(self, text: str) -> None:
        """
        消息朗读回调

        Args:
            text: 要朗读的文本
        """
        self._logger.info(f"开始朗读消息: {text[:50]}...")
        # TODO: 实现 TTS 朗读功能

    # ==================== 公共方法 ====================

    def get_floating_chat_window(self) -> FloatingChatWindow | None:
        """获取悬浮聊天窗口实例"""
        return self._floating_chat_window

    def get_input_area(self) -> InputArea | None:
        """获取输入区域实例"""
        return self._input_area

    # ==================== 设置对话框 ====================

    def _on_settings_click(self) -> None:
        """设置按钮点击回调"""
        # 创建设置对话框（如果尚未创建）
        if not self._settings_dialog:
            self._settings_dialog = SettingsDialog(self._page)

        # 打开设置对话框
        self._settings_dialog.open()

    # ==================== 会话管理方法 ====================

    def _create_new_conversation(self) -> str | None:
        """创建新会话并返回会话ID"""
        if not self.skill_agent:
            self._logger.error("SkillAgent 未初始化，无法创建会话")
            return None

        try:
            # 调用 SkillAgent 创建新会话
            conversation_id, title = self.skill_agent.start_new_conversation()
            self._logger.info(f"创建新会话: {conversation_id}")

            # 添加到状态管理
            # 注意：session.add_conversation 会触发 SessionState 的
            # on_conversation_added 回调，ConversationSidebar 已在
            # _setup_state_callbacks 中注册该回调并自动添加侧边栏项。
            # 因此这里**不能**再手动调用 sidebar.add_conversation，
            # 否则会出现重复项（与 issue "新增会话创建两个" 对应）。
            self._app_state.session.add_conversation(
                conversation_id,
                title=title or f"新会话-{conversation_id[:5]}",
                pending_db_history=False,
            )

            # 切换到新会话（同时负责把新会话标记为选中）
            self._switch_to_conversation(conversation_id)

            return conversation_id

        except Exception as e:
            self._logger.exception(f"创建新会话失败: {e}")
            return None

    def _switch_to_conversation(self, conversation_id: str) -> None:
        """切换到指定会话"""
        if not conversation_id:
            return

        # 设置当前会话
        self._app_state.session.set_current_conversation(conversation_id)

        # 设置 SkillAgent 的当前会话
        if self.skill_agent:
            self.skill_agent.set_conversation_id(conversation_id)

        # 更新侧边栏选中状态
        if self._conversation_sidebar:
            self._conversation_sidebar.set_selected_conversation(conversation_id)

        # 清空消息列表（切换会话时必须清除旧消息，否则会追加到旧消息后面）
        # 注意：update_ui=False —— 不立即触发 page.update()，避免 Flutter 在
        # "清空→逐条添加"的中间布局状态时给 tight=True 的 Column 分配错误
        # 的宽度约束（表现为切换会话后气泡变宽）。全部消息添加完后统一更新。
        if self._message_list:
            self._message_list.clear_all(update_ui=False)

        # 标记为需要重新加载，确保 _load_conversation_messages 不会因
        # pending_db_history=False 而跳过
        self._app_state.session.set_pending_db_history(conversation_id, True)

        # 加载会话历史消息（内部 add_message 使用 update_ui=False）
        self._load_conversation_messages(conversation_id)

        # 清除等待用户回复卡片
        if self._await_user_card:
            self._await_user_card.clear_prompt()

        # 统一触发一次 UI 更新（清空 + 加载全部完成后）
        self._page.update()

        self._logger.info(f"切换到会话: {conversation_id}")

    def _load_conversation_messages(self, conversation_id: str) -> None:
        """加载会话的历史消息"""
        if not self.skill_agent or not self._message_list:
            return

        try:
            # 检查是否需要加载历史
            if not self._app_state.session.is_pending_db_history(conversation_id):
                return

            # 标记为已加载
            self._app_state.session.set_pending_db_history(conversation_id, False)

            # 从 SkillAgent 获取消息记录
            records = self.skill_agent.message_records_for_conversation(conversation_id)

            # 重放消息
            for record in records:
                role = str(record.get("role", ""))
                content = str(record.get("content", ""))
                metadata = record.get("metadata", {})

                if role == "user":
                    msg_type = "user"
                elif role == "assistant":
                    msg_type = metadata.get("type", "assistant")
                    if msg_type not in ["assistant", "think", "tool_call"]:
                        msg_type = "assistant"
                elif role == "tool":
                    msg_type = "tool"
                else:
                    continue

                # 添加消息到列表
                # update_ui=False：批量加载时不逐条触发 page.update()，
                # 由 _switch_to_conversation 在全部加载完后统一更新
                self._message_list.add_message(msg_type, content, update_ui=False)

        except Exception as e:
            self._logger.exception(f"加载会话消息失败: {e}")

    async def _load_initial_conversations_async(self) -> None:
        """异步加载初始会话"""
        try:
            self._logger.info("开始异步加载初始会话")

            # 显示加载状态
            if self._conversation_sidebar:
                self._conversation_sidebar.show_loading()

            # 在后台线程执行同步操作
            await asyncio.get_event_loop().run_in_executor(
                None, self._load_initial_conversations_sync
            )

            # 隐藏加载状态
            if self._conversation_sidebar:
                self._conversation_sidebar.hide_loading()

            self._logger.info("初始会话加载完成")
        except Exception:
            self._logger.exception("异步加载初始会话失败")
            # 发生异常时也要隐藏加载状态
            if self._conversation_sidebar:
                self._conversation_sidebar.hide_loading()

    def _load_initial_conversations_sync(self) -> None:
        """加载初始会话列表"""
        if not self.skill_agent or not self._conversation_sidebar:
            return

        try:
            # 获取所有会话
            all_sessions = [
                c for c in self.skill_agent.list_saved_conversations()
                if (c.conversation_id or "").strip()
            ]

            # 使用单次查询获取所有有消息的会话 ID
            conversation_ids_with_messages = (
                self._memory.get_conversations_with_messages()
                if self._memory else set()
            )

            # 筛选有消息的会话
            sessions_with_messages = [
                conv for conv in all_sessions
                if (conv.conversation_id or "").strip() in conversation_ids_with_messages
            ]

            # 如果没有会话，创建新会话
            if not sessions_with_messages:
                self._create_new_conversation()
                return

            # 加载会话到状态管理
            self._app_state.session.load_from_conversations(sessions_with_messages)

            # 加载到侧边栏
            self._conversation_sidebar.load_conversations(sessions_with_messages)

            # 切换到第一个会话
            first_cid = (sessions_with_messages[0].conversation_id or "").strip()
            if first_cid:
                self._switch_to_conversation(first_cid)

            self._logger.info(f"加载了 {len(sessions_with_messages)} 个会话")

        except Exception as e:
            self._logger.exception(f"加载初始会话失败: {e}")
            # 创建新会话作为降级方案
            self._create_new_conversation()

    # ==================== 流式打字机效果 ====================

    def _setup_stream_callbacks(self) -> None:
        """设置流状态回调"""
        self._app_state.stream.set_callbacks(
            on_stream_started=self._on_stream_started,
            on_stream_tick=self._on_stream_tick,
            on_stream_completed=self._on_stream_completed,
        )

    def _on_stream_started(self, session_id: str) -> None:
        """流开始回调"""
        self._logger.info(f"[StreamCallback] _on_stream_started 被调用, session_id={session_id}")
        try:
            if not self._message_list:
                self._logger.warning("[StreamCallback] _message_list 为空，跳过处理")
                return

            stream_type = self._app_state.stream.get_current_type()
            msg_type = "think" if stream_type == StreamType.THINK else "assistant"
            self._logger.info(f"[StreamCallback] 流类型: {stream_type}, 消息类型: {msg_type}")

            # 添加一条空消息卡片，并立即把它登记为本次流的"打字机目标卡片"。
            # 之后无论 LLM 在同一 step 内追加多少 tool_call/tool 卡片，
            # 打字机任务都只更新这张卡片，不会污染后续卡片。
            new_card = self._message_list.add_message(msg_type, "")
            self._current_typing_card = new_card
            self._logger.info(f"[StreamCallback] 已添加空消息卡片, target_card_id={id(new_card)}")

            # 启动打字机效果任务
            self._start_stream_typing()
            self._logger.info("[StreamCallback] 打字机效果已启动")
        except Exception as e:
            self._logger.exception(f"[StreamCallback] _on_stream_started 执行异常: {e}")

    def _on_stream_tick(self, session_id: str, shown_chars: int) -> None:
        """流推进回调"""
        self._logger.debug(f"[StreamCallback] _on_stream_tick 被调用: session_id={session_id}, shown_chars={shown_chars}")
        try:
            if not self._message_list:
                self._logger.warning("[StreamCallback] _on_stream_tick: _message_list 为空，跳过更新")
                return

            full_text = self._app_state.stream.get_full_text()
            shown_text = full_text[:shown_chars]
            self._logger.debug(f"[StreamCallback] _on_stream_tick: full_text长度={len(full_text)}, shown_text长度={len(shown_text)}")

            # 更新最后一条消息的内容
            success = self._message_list.update_last_message(shown_text)
            if not success:
                self._logger.warning(f"[StreamCallback] _on_stream_tick: update_last_message 返回 False")
            else:
                self._logger.debug(f"[StreamCallback] _on_stream_tick: UI 更新完成")
        except Exception as e:
            self._logger.exception(f"[StreamCallback] _on_stream_tick 执行异常: {e}")

    def _on_stream_completed(self, session_id: str, token_usage: dict[str, Any] | None) -> None:
        """流完成回调"""
        self._logger.info(f"[StreamCallback] _on_stream_completed 被调用, session_id={session_id}, token_usage={token_usage}")
        try:
            # 先在清除目标卡片之前保留引用——下面 _stop_stream_typing 会清空它
            target_card = self._current_typing_card

            # 停止打字机效果
            self._stop_stream_typing()
            self._logger.info("[StreamCallback] 打字机效果已停止")

            if not self._message_list:
                self._logger.warning("[StreamCallback] _on_stream_completed: _message_list 为空")
                return

            # 确保显示完整文本
            full_text = self._app_state.stream.get_full_text()
            self._logger.info(f"[StreamCallback] 完整文本长度: {len(full_text)}")

            # 关键：直接更新"目标卡片"（即本次流开始时新建的卡片），
            # 而不是 update_last_message。原因：在 tool/base_tool 处理器中，
            # 流的 complete 会在 add_message 之前触发；如果按最后一条卡片更新，
            # 会把 assistant 的最终文本写进刚追加的 tool_call/tool 卡片。
            if target_card is not None:
                target_card.update_content(full_text)
                target_card.finalize_content(token_usage)
                self._logger.info(
                    f"[StreamCallback] 已更新并完成目标卡片 (id={id(target_card)}, length={len(full_text)})"
                )
            else:
                # 回退：目标卡片丢失时仍按"最后一条卡片"行为兜底
                success = self._message_list.update_last_message(full_text)
                if not success:
                    self._logger.warning("[StreamCallback] update_last_message 返回 False")
                self._message_list.finalize_last_message(token_usage)
                self._logger.info("[StreamCallback] 已完成最后一条消息的渲染（fallback）")

            # 同步完整消息到悬浮窗口
            if self._floating_chat_window:
                stream_type = self._app_state.stream.get_current_type()
                msg_type = "think" if stream_type == StreamType.THINK else "assistant"
                self._floating_chat_window.add_message(msg_type, full_text)
                self._logger.info(f"[StreamCallback] 已同步完整消息到悬浮窗口: type={msg_type}, length={len(full_text)}")
        except Exception as e:
            self._logger.exception(f"[StreamCallback] _on_stream_completed 执行异常: {e}")

    def _start_stream_typing(self) -> None:
        """启动打字机效果循环"""
        self._logger.info("[打字机] _start_stream_typing 被调用")

        if self._stream_typing_active:
            self._logger.warning("[打字机] _start_stream_typing: 已经有打字机任务在运行，跳过")
            return

        self._stream_typing_active = True
        # 增加代数：让可能仍在跑的旧任务在下一轮迭代立刻退出。
        # 配合 _stream_typing_active，避免"旧任务被取消后被新任务的 active=True 复活"。
        self._typing_generation += 1
        current_generation = self._typing_generation
        # 在闭包内捕获目标卡片。后续无论 message_list 追加多少 tool_call/tool 卡片，
        # 打字机都只更新这一张卡片，绝不调用 update_last_message。
        target_card = self._current_typing_card
        target_card_id = id(target_card) if target_card is not None else None
        self._logger.info(
            f"[打字机] _stream_typing_active 已设置为 True, "
            f"generation={current_generation}, target_card_id={target_card_id}"
        )

        async def typing_loop() -> None:
            self._logger.info(
                f"[打字机] typing_loop 开始执行, generation={current_generation}, target_card_id={target_card_id}"
            )
            iteration_count = 0

            while self._stream_typing_active and self._typing_generation == current_generation:
                iteration_count += 1
                stream_state = self._app_state.stream

                self._logger.debug(
                    f"[打字机] typing_loop 迭代 #{iteration_count}: is_streaming={stream_state.is_streaming()}, "
                    f"active={self._stream_typing_active}, gen_ok={self._typing_generation == current_generation}"
                )

                if not stream_state.is_streaming():
                    self._logger.info(
                        f"[打字机] typing_loop: 流已停止，退出循环 (迭代 #{iteration_count})"
                    )
                    break

                buf = stream_state.get_buffer()
                if buf.is_complete():
                    self._logger.debug(
                        f"[打字机] typing_loop: 缓冲区已完成，等待更多内容 (迭代 #{iteration_count})"
                    )
                    await asyncio.sleep(0.05)
                    continue

                # 手动推进 buffer——直接修改 shown_chars，**不再调用 stream_state.advance_stream()**，
                # 因为 advance_stream 会触发 _on_stream_tick → update_last_message，
                # 在一个 step 内"思考 + 工具调用 + 工具结果 + 下一轮 assistant 文本"混在一起时，
                # 旧任务的最后一次 advance_stream 会把上一次残留的 assistant 文本
                # 写进本轮新增的 tool_call/tool 卡片，表现为"调用工具卡片/工具卡片
                # 重复显示 assistant 文本"。这里只更新本次流的目标卡片。
                next_shown = min(
                    len(buf.full_text),
                    buf.shown_chars + max(1, buf.chars_per_tick),
                )
                buf.shown_chars = next_shown

                if target_card is not None:
                    shown_text = buf.full_text[:next_shown]
                    try:
                        target_card.update_content(shown_text)
                    except Exception as e:
                        self._logger.warning(f"[打字机] 更新目标卡片失败: {e}")

                # 二次检查 generation：即便 active 被新任务置 True，也能立即识别
                if self._typing_generation != current_generation:
                    self._logger.info(
                        f"[打字机] typing_loop: 代数已变更，退出循环 (迭代 #{iteration_count})"
                    )
                    break

                # 控制打字速度
                await asyncio.sleep(0.03)

            self._stream_typing_active = False
            self._logger.info(
                f"[打字机] typing_loop 循环结束，共迭代 {iteration_count} 次, generation={current_generation}"
            )

        try:
            self._logger.info("[打字机] 准备调用 run_task(typing_loop)")
            self._stream_typing_task = self._page.run_task(typing_loop)
            self._logger.info(
                f"[打字机] run_task 已调用，task={self._stream_typing_task}, generation={current_generation}"
            )
        except Exception as e:
            self._logger.warning(f"[打字机] 启动打字机效果失败: {e}")
            self._stream_typing_active = False
            # 失败时让下一次 _start_stream_typing 可以重新启动
            self._typing_generation += 1

    def _stop_stream_typing(self) -> None:
        """停止打字机效果循环"""
        self._logger.info(
            f"[打字机] _stop_stream_typing 被调用, current generation={self._typing_generation}"
        )
        # 关键修复 1：先让代数 +1，让 typing_loop 在下一轮迭代立刻退出，
        # 不再受后续 _start_stream_typing 把 active 重新置 True 的影响。
        self._typing_generation += 1
        # 关键修复 2：立刻清空目标卡片引用，避免 typing_loop 还在飞的最后一帧
        # advance_stream 把残留的 assistant 文本写入本 step 内后续追加的
        # tool_call/tool 卡片（即使 typing_loop 已经"读"了 target_card 的局部变量，
        # 这一步仍可作为防御性兜底）。
        self._current_typing_card = None
        self._stream_typing_active = False
        if self._stream_typing_task and not self._stream_typing_task.done():
            try:
                self._stream_typing_task.cancel()
            except Exception:
                pass
        self._stream_typing_task = None

    # ==================== 工作线程和消息处理 ====================

    def _start_skill_agent_worker(self, query: str, conversation_id: str) -> None:
        """启动 SkillAgent 工作线程"""
        # 重置停止事件
        self._stop_event.clear()

        # 设置思考模式状态
        if self.skill_agent and self._input_area:
            self.skill_agent.set_enable_thinking(self._input_area.is_thinking_enabled())

        # 创建并启动工作线程
        self._worker_thread = threading.Thread(
            target=self._skill_agent_worker_thread,
            args=(query, conversation_id),
            name=f"skill-agent-worker-{conversation_id[:8]}",
            daemon=True,
        )
        self._worker_thread.start()

        self._logger.info(f"启动工作线程: {conversation_id}")

    def _skill_agent_worker_thread(self, query: str, conversation_id: str) -> None:
        """SkillAgent 工作线程"""
        try:
            # 设置会话 ID
            if self.skill_agent:
                self.skill_agent.set_conversation_id(conversation_id)

            # 定义日志回调函数
            def log_callback(message: str, msg_type: str) -> None:
                # 检查是否被请求停止
                if self._stop_event.is_set():
                    return

                # 在主线程中更新 UI
                self._page.run_task(self._handle_worker_message, message, msg_type, conversation_id)

            # 调用 SkillAgent
            result = self.skill_agent.run(
                query,
                log_callback=log_callback,
                stop_check_callback=self._stop_event.is_set,
            )

            # 处理完成
            self._page.run_task(self._handle_worker_finished, result, conversation_id)

        except Exception as e:
            self._logger.exception(f"工作线程执行失败: {e}")
            # 处理错误
            self._page.run_task(self._handle_worker_finished, f"执行出错: {e}", conversation_id)

    async def _handle_worker_message(self, message: str, msg_type: str, conversation_id: str) -> None:
        """处理工作线程的消息（在主线程中运行）"""
        # 添加调试日志：确认消息是否被接收
        self._logger.debug("[_handle_worker_message] 收到消息: type=%s, conversation_id=%s, content前50字=%s",
                           msg_type, conversation_id[:8] + "...", message[:50] if message else "(空)")

        # 检查是否为当前会话
        current_cid = self._app_state.session.get_current_conversation()
        if current_cid != conversation_id:
            self._logger.debug("[_handle_worker_message] 非当前会话，跳过处理: current_cid=%s", current_cid[:8] + "..." if current_cid else "(空)")
            return

        # 根据消息类型处理
        if msg_type == "assistant":
            # 流式助手消息
            self._handle_stream_message(message, "assistant", conversation_id)
            # 注意：不在此处同步到悬浮窗口，流式消息已在 _handle_stream_message 中处理
        elif msg_type == "think":
            # 思考消息
            self._handle_stream_message(message, "think", conversation_id)
            # 注意：不在此处同步到悬浮窗口，流式消息已在 _handle_stream_message 中处理
        elif msg_type == "tool":
            # 工具调用消息（只在主窗口显示）
            # 关键修复：必须先 complete 当前流，再添加 tool_call 卡片。
            # 否则打字机任务仍会继续运行，把 stream buffer 累积的 assistant
            # 文本通过 update_last_message 写入新创建的 tool_call 卡片，
            # 同时下一个 step 的 LLM 流来时 stream_state.is_streaming() 仍为
            # True，会走 append_to_stream 分支造成 buffer 跨 step 累积，
            # 最终导致多个"调用工具"卡片重复显示流式 assistant 文本。
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()
            if self._message_list:
                self._message_list.add_message("tool_call", message)
        elif msg_type == "base_tool":
            # 基础工具结果（只在主窗口显示）
            # 同样需要先 complete 当前流，避免 typing 写入新的 tool 卡片
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()
            if self._message_list:
                self._message_list.add_message("tool", message)
        elif msg_type == "token_usage":
            # Token 使用信息
            self._handle_token_usage(message, conversation_id)
            # 同步到悬浮窗口
            if self._floating_chat_window:
                import json
                try:
                    token_usage = json.loads(message)
                    self._floating_chat_window.finalize_last_message(token_usage)
                except:
                    pass
        elif msg_type == "await_user":
            # 等待用户回复
            self._handle_await_user(message, conversation_id)
            # 同步到悬浮窗口
            if self._floating_chat_window:
                import json
                try:
                    spec = json.loads(message)
                    self._floating_chat_window.show_await_user_prompt(
                        spec,
                        on_confirm_send=lambda t: self._on_floating_chat_send(t)
                    )
                except:
                    pass
        elif msg_type == "mode":
            # 模式消息（用于显示徽章）
            pass  # 可以在这里添加模式徽章显示
        elif msg_type == "plan":
            # 计划消息
            # 同样需要先 complete 当前流，避免 typing 写入新的 assistant 卡片
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()
            if self._message_list:
                self._message_list.add_message("assistant", message)
            # 同步到悬浮窗口
            if self._floating_chat_window:
                self._floating_chat_window.add_message("assistant", message)
        else:
            # 其他消息类型（info, tool_call等）
            if self._message_list and msg_type in ["info", "tool_call"]:
                pass  # 暂不处理

        # 更新页面
        self._page.update()

    async def _handle_worker_finished(self, result: str, conversation_id: str) -> None:
        """处理工作线程完成"""
        # 重置 UI 状态
        self._app_state.ui.set_task_running(False)

        # 恢复发送按钮为正常状态
        if self._input_area:
            self._input_area.set_inference_running(False)

        # 检查是否为当前会话
        current_cid = self._app_state.session.get_current_conversation()
        if current_cid != conversation_id:
            return

        # 处理结果
        if result == SKILL_AGENT_AWAITING_USER_REPLY:
            # 等待用户回复，不添加额外消息
            self._logger.info("SkillAgent 等待用户回复")
        else:
            # 非等待状态，清除等待用户卡片
            if self._await_user_card:
                self._await_user_card.clear_prompt()

            # 完成当前流（如果还在进行）
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()

            # 仅在流**从未启动**时把 result 补成一张 assistant 卡片。
            # 注意：不能用 `not is_streaming()`，因为 is_streaming() 在流
            # 被 complete_stream 关闭后也会变 False（_is_completed=True），
            # 那样会把已经流式渲染过的 result 重复再写一张卡。
            if (
                result
                and result.strip()
                and stream_state.get_current_type() == StreamType.NONE
            ):
                if self._message_list:
                    self._message_list.add_message("assistant", result)

        # 清理流状态
        self._app_state.stream.clear()

        # 更新页面
        self._page.update()

        self._logger.info(f"工作线程完成: {conversation_id}")

    def _handle_stream_message(self, message: str, msg_type: str, conversation_id: str) -> None:
        """处理流式消息：将内容追加到流缓冲区，由打字机效果异步显示"""
        # 添加调试日志：确认流状态是否正确设置
        self._logger.debug("[_handle_stream_message] 收到流消息: type=%s, conversation_id=%s, content前50字=%s",
                           msg_type, conversation_id[:8] + "...", message[:50] if message else "(空)")

        if not self._message_list:
            self._logger.debug("[_handle_stream_message] message_list 为空，跳过处理")
            return

        stream_state = self._app_state.stream

        # 检查是否需要切换流类型
        current_stream_type = stream_state.get_current_type()
        new_stream_type = StreamType.THINK if msg_type == "think" else StreamType.CONTENT

        self._logger.debug("[_handle_stream_message] 流状态: current_type=%s, new_type=%s, is_streaming=%s",
                           current_stream_type, new_stream_type, stream_state.is_streaming())

        if current_stream_type != new_stream_type or not stream_state.is_streaming():
            # 完成之前的流
            if stream_state.is_streaming():
                self._logger.debug("[_handle_stream_message] 完成之前的流: type=%s", current_stream_type)
                stream_state.complete_stream()

            # 开始新的流
            self._logger.debug("[_handle_stream_message] 开始新流: type=%s", new_stream_type)
            stream_state.start_stream(conversation_id, new_stream_type, message)
        else:
            # 追加到现有流
            self._logger.debug("[_handle_stream_message] 追加到现有流: type=%s", new_stream_type)
            stream_state.append_to_stream(message)

    def _handle_token_usage(self, token_usage_json: str, conversation_id: str) -> None:
        """处理 Token 使用信息"""
        try:
            import json
            token_usage = json.loads(token_usage_json)

            # 完成流并附带 token 信息
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream(token_usage)

        except Exception as e:
            self._logger.exception(f"处理 Token 使用信息失败: {e}")

    def _is_awaiting_user_reply(self) -> bool:
        """检查当前是否处于等待用户回复状态"""
        return self._await_user_card is not None and self._await_user_card.has_active_prompt()

    def _handle_await_user(self, spec_json: str, conversation_id: str) -> None:
        """处理等待用户回复"""
        try:
            import json
            spec = json.loads(spec_json)

            # 完成当前的流
            stream_state = self._app_state.stream
            if stream_state.is_streaming():
                stream_state.complete_stream()

            # 显示等待用户回复卡片
            current_cid = self._app_state.session.get_current_conversation()
            if current_cid == conversation_id and self._await_user_card:
                self._await_user_card.show_prompt(
                    spec,
                    on_confirm_send=lambda text: self._on_message_send(text, []),
                )

            self._logger.info(f"等待用户回复: {spec.get('question', '')}")

        except Exception as e:
            self._logger.exception(f"处理等待用户回复失败: {e}")

    def request_stop_worker(self) -> None:
        """请求停止工作线程"""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            if self.skill_agent:
                self.skill_agent.request_stop()
            self._logger.info("请求停止工作线程")

    # ==================== 悬浮球公共接口 ====================

    def show_main_window(self) -> None:
        """显示并激活主窗口（供桌面悬浮球调用）"""
        try:
            self._page.window.minimized = False
            self._page.window.visible = True
            self._page.window.focused = True
            self._page.update()
            self._logger.info("悬浮球请求：显示主窗口")
        except Exception as e:
            self._logger.warning(f"显示主窗口失败: {e}")

    async def quit_application(self) -> None:
        """退出应用（供桌面悬浮球调用）"""
        self._logger.info("悬浮球请求：退出应用")
        try:
            self._save_window_state()
            self._page.window.prevent_close = False
            await self._page.window.close()
        except Exception as e:
            self._logger.exception(f"退出应用失败: {e}")

    def toggle_floating_chat(self) -> None:
        """切换悬浮聊天窗口显示状态（供桌面悬浮球调用）"""
        if self._floating_chat_window:
            self._floating_chat_window.toggle()
            self._logger.info("悬浮球请求：切换悬浮聊天窗口")
        else:
            self._logger.warning("悬浮聊天窗口未初始化")

    def start_recording(self) -> None:
        """开始录音（供桌面悬浮球调用）"""
        try:
            from recorder import get_recorder, is_online_model_loaded

            if not is_online_model_loaded():
                self._logger.warning("流式 ASR 模型未加载，无法实时识别")
                return

            recorder = get_recorder()
            self._recording_text = ""
            recorder.start_recording(
                realtime_callback=self._on_recording_realtime_result
            )
            self._logger.info("悬浮球请求：开始录音")
        except Exception as e:
            self._logger.exception(f"开始录音失败: {e}")

    def stop_recording(self) -> None:
        """停止录音并发送识别结果（供桌面悬浮球调用）"""
        try:
            from recorder import get_recorder

            recorder = get_recorder()
            audio_path = recorder.stop_recording()
            self._logger.info(f"悬浮球请求：停止录音，音频路径={audio_path}")

            text = getattr(self, "_recording_text", "")
            if not text and audio_path:
                # 实时识别无结果，尝试离线转录
                try:
                    text = recorder.transcribe_audio(audio_path)
                    self._logger.info(f"离线转录结果: {text}")
                except Exception as te:
                    self._logger.warning(f"离线转录失败: {te}")

            self._recording_text = ""
            if text:
                self._on_message_send(text, [])
        except Exception as e:
            self._logger.exception(f"停止录音失败: {e}")

    def _on_recording_realtime_result(self, text: str, is_final: bool) -> None:
        """实时识别结果回调"""
        if text:
            self._recording_text = text
            self._logger.debug(f"实时识别: {text}, is_final={is_final}")
