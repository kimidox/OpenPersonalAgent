"""
Flet 主窗口视图

提供应用程序的主窗口布局，包括侧边栏和主内容区。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

import flet as ft

import config
from logger import get_logger
from executor import Executor
from memory import SqliteMemory
from scheduler import TaskScheduler
from skill_agent import SkillAgent
from ui_flet.state import AppState
from ui_flet.theme import ThemeManager
from ui_flet.components.message_list import MessageList
from ui_flet.components.input_area import InputArea
from ui_flet.components.llm_status_indicator import LLMStatusIndicator
from ui_flet.utils.file_upload_manager import UploadedFileInfo
from ui_flet.components.await_user_card import AwaitUserCard
from ui_flet.components.conversation_sidebar import ConversationSidebar
from ui_flet.views.floating_chat_window import FloatingChatWindow
from ui_flet.views.settings_dialog import SettingsDialog
from ui_flet.views.main_window_mixins import (
    WindowEventsMixin,
    ConversationManagerMixin,
    StreamTypingMixin,
    WorkerThreadMixin,
    ScheduledTaskMixin,
    FloatingBallMixin,
)

# 向后兼容：从 _utils 重新导出辅助函数，供外部模块使用
from ui_flet.views.main_window_mixins._utils import _get_state_display_text, _get_warning_display_text  # noqa: F401


class MainWindow(
    WindowEventsMixin,
    ConversationManagerMixin,
    StreamTypingMixin,
    WorkerThreadMixin,
    ScheduledTaskMixin,
    FloatingBallMixin,
):
    """
    主窗口视图类

    管理主窗口的布局和交互，包括：
    - 左侧会话侧边栏
    - 右侧主内容区（消息列表 + 输入区域）
    - 悬浮聊天窗口
    - 窗口控制（最小化/关闭）
    """

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
        self._setup_ui_state_callbacks()

        # 主题管理
        self._theme_manager = ThemeManager()

        # 定时任务调度器（在 _init_backend_components 中实例化）
        self._scheduler: TaskScheduler | None = None

        # 初始化后端组件
        self._init_backend_components()

        # UI 组件引用
        self._conversation_sidebar: ConversationSidebar | None = None
        self._sidebar_container: ft.Container | None = None
        self._sidebar_toggle_btn: ft.IconButton | None = None
        self._message_list: MessageList | None = None
        self._input_area: InputArea | None = None
        self._floating_chat_window: FloatingChatWindow | None = None
        self._llm_status_indicator: LLMStatusIndicator | None = None

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

    # ==================================================================
    # 窗口初始化和配置
    # ==================================================================

    def _setup_window(self) -> None:
        """设置窗口基础配置"""
        self._page.title = "PersonalWindowGLM"

        # 设置初始窗口大小（从 env 文件读取，允许用户调整但不保存）
        self._page.window.width = config.WINDOW_WIDTH
        self._page.window.height = config.WINDOW_HEIGHT

        # 窗口初始位置在屏幕正中间
        self._center_window()

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

            # 初始化定时任务调度器（依赖主窗口引用，需在最后实例化）
            self._scheduler = TaskScheduler(tray_icon=None, main_window=self)
            self._scheduler.start()
            self._logger.info("TaskScheduler 初始化完成")

        except Exception:
            self._logger.exception("后端组件初始化失败")
            # 即使初始化失败，也要创建基本组件以避免程序崩溃
            self.work_dir = config.WORKER_DIR
            self.executor = None
            self._memory = None
            self.skill_agent = None
            self._scheduler = None

    def _setup_window_events(self) -> None:
        """设置窗口事件处理"""
        self._page.window.on_event = self._on_window_event
        # 全局键盘事件：处理快捷键
        self._page.on_keyboard_event = self._on_keyboard_event

    # ==================================================================
    # 布局构建
    # ==================================================================

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
            on_load_more=self._load_more_messages,
        )

        # 创建等待用户回复卡片
        self._await_user_card = AwaitUserCard()

        # 创建输入区域
        self._input_area = InputArea(self._page)
        self._input_area.set_on_send(self._on_message_send)
        self._input_area.set_on_stop(self.request_stop_worker)

        # 创建LLM状态指示器
        self._llm_status_indicator = LLMStatusIndicator()

        # 右侧聊天区域（消息列表 + 等待用户卡片 + 输入区域 + 状态指示器，与旧版 PySide6 一致：内边距 10，间距 8）
        chat_content = ft.Column(
            [
                self._message_list,
                self._await_user_card,
                self._input_area.get_control(),
                self._llm_status_indicator.get_control(),
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

    # ==================================================================
    # 消息发送
    # ==================================================================

    def _on_message_send(self, text: str, files: list[UploadedFileInfo]) -> None:
        """
        消息发送回调

        Args:
            text: 消息文本
            files: 上传的文件列表
        """
        self._logger.info(f"发送消息: {text[:50] if text else ''}...")
        if files:
            self._logger.info(f"附带文件: {[f.original_name for f in files]}")

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

        # 将文件内容嵌入系统提示词
        if self.skill_agent:
            from ui_flet.utils.file_upload_controller import FileUploadController
            files_content = FileUploadController.generate_full_content_from_list(files)

            # 记录文件内容传递的日志
            if files_content:
                text_content = files_content.get("text_content", "")
                images = files_content.get("images", [])
                self._logger.info(
                    f"文件内容已传递给 SkillAgent: "
                    f"文本内容长度={len(text_content)}, 图片数量={len(images)}"
                )
                if images:
                    self._logger.info(
                        f"图片文件: {[img.get('file_name') for img in images]}"
                    )
            else:
                self._logger.info("无文件内容传递给 SkillAgent")

            self.skill_agent.set_uploaded_files_content(files_content)

        # 添加用户消息到消息列表
        if self._message_list:
            self._message_list.add_message("user", text, files=files)

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
            self._settings_dialog = SettingsDialog(
                self._page,
                on_close=self._on_settings_dialog_close,
            )

        # 打开设置对话框
        self._settings_dialog.open()

    def _on_settings_dialog_close(self) -> None:
        """设置对话框关闭回调"""
        self._logger.info("SettingsDialog 已关闭，同步配置状态")
        # 同步激活配置的 enable_vision 状态
        self._sync_enable_vision_from_active_config()

    def _sync_enable_vision_from_active_config(self) -> None:
        """从激活配置同步 enable_vision 状态到 UIState"""
        try:
            from llm.llm_config_manager import get_active_config_item

            active_config = get_active_config_item()
            if active_config:
                enable_vision = getattr(active_config, "enable_vision", True)
                self._logger.info(f"激活配置 enable_vision={enable_vision}")
                # 通过 UIState 设置，会触发回调
                self._app_state.ui.set_enable_vision(enable_vision)
        except Exception as e:
            self._logger.exception(f"同步 enable_vision 状态失败: {e}")
