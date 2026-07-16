"""Flet 会话侧边栏组件

提供会话列表的显示、创建、删除和切换功能。
右键会话项可弹出编辑菜单（重命名/删除）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

from logger import get_logger
from ui_flet.state import SessionState, SessionInfo
from ui_flet.theme import ThemeManager, get_color

if TYPE_CHECKING:
    from flet import Page


class ConversationListItem(ft.Container):
    """会话列表项组件，右键弹出编辑菜单"""

    def __init__(
        self,
        conversation_id: str,
        title: str,
        page: ft.Page,
        on_click: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_rename: Callable[[str], None] | None = None,
        is_selected: bool = False,
    ) -> None:
        """
        初始化会话列表项

        Args:
            conversation_id: 会话ID
            title: 会话标题
            page: Flet Page 对象
            on_click: 点击回调
            on_delete: 删除回调
            on_rename: 重命名回调
            is_selected: 是否选中
        """
        self._conversation_id = conversation_id
        self._title = title
        self._page = page
        self._on_click = on_click
        self._on_delete = on_delete
        self._on_rename = on_rename
        self._is_selected = is_selected

        # 获取主题颜色
        colors = ThemeManager().get_color_scheme()

        # 创建标题文本（支持截断）
        self._title_text = ft.Text(
            value=self._truncate_title(title),
            size=14,
            color=colors.text,
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
            tooltip=title,  # 悬停显示完整标题
        )

        # 创建内容行
        content_row = ft.Row(
            controls=[
                self._title_text,
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # 用右键上下文菜单包裹内容行
        context_menu = ft.ContextMenu(
            content=content_row,
            secondary_items=[
                ft.PopupMenuItem(
                    content=ft.Text("编辑会话名称"),
                    icon=ft.Icons.EDIT,
                    on_click=self._handle_rename_click,
                ),
                ft.PopupMenuItem(
                    content=ft.Text("删除"),
                    icon=ft.Icons.DELETE_OUTLINE,
                    on_click=self._handle_delete_click,
                ),
            ],
            secondary_trigger=ft.ContextMenuTrigger.DOWN,
        )

        # 初始化容器
        super().__init__(
            content=context_menu,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            border_radius=ft.BorderRadius.all(8),
            height=40,
            on_click=self._handle_click,
            animate=ft.Animation(200, ft.AnimationCurve.EASE),
        )

        # 应用样式
        self._update_style()

    def _truncate_title(self, title: str, max_length: int = 30) -> str:
        """截断标题"""
        if len(title) > max_length:
            return title[:max_length - 3] + "..."
        return title

    def _update_style(self) -> None:
        """更新样式"""
        colors = ThemeManager().get_color_scheme()

        if self._is_selected:
            self.bgcolor = colors.primary_soft
            self._title_text.color = colors.primary
        else:
            self.bgcolor = None
            self._title_text.color = colors.text

    def _handle_click(self, e) -> None:
        """点击事件处理"""
        if self._on_click:
            self._on_click(self._conversation_id)

    def _handle_rename_click(self, e) -> None:
        """编辑会话名称菜单点击事件处理"""
        if self._on_rename:
            self._on_rename(self._conversation_id)

    def _handle_delete_click(self, e) -> None:
        """删除菜单点击事件处理"""
        if self._on_delete:
            self._on_delete(self._conversation_id)

    def _safe_update(self) -> None:
        """安全更新控件（未挂载到页面时忽略）"""
        try:
            if self.page:
                self.update()
        except RuntimeError:
            pass

    def set_selected(self, selected: bool) -> None:
        """设置选中状态"""
        if self._is_selected != selected:
            self._is_selected = selected
            self._update_style()
            self._safe_update()

    def set_title(self, title: str) -> None:
        """设置标题"""
        self._title = title
        self._title_text.value = self._truncate_title(title)
        self._title_text.tooltip = title
        self._safe_update()


class ConversationSidebar(ft.Column):
    """
    会话侧边栏组件

    功能：
    - 显示会话列表
    - 创建新会话
    - 删除会话
    - 重命名会话（右键会话项）
    - 切换会话
    """

    def __init__(
        self,
        page: ft.Page,
        session_state: SessionState,
        on_conversation_changed: Callable[[str], None] | None = None,
        on_new_conversation: Callable[[], None] | None = None,
        on_delete_conversation: Callable[[str], None] | None = None,
        on_rename_conversation: Callable[[str, str], None] | None = None,
        on_settings_click: Callable[[], None] | None = None,
    ) -> None:
        """
        初始化会话侧边栏

        Args:
            page: Flet Page 对象
            session_state: 会话状态管理器
            on_conversation_changed: 会话切换回调
            on_new_conversation: 创建新会话回调
            on_delete_conversation: 删除会话回调
            on_rename_conversation: 重命名会话回调（参数：会话ID, 新标题）
            on_settings_click: 设置按钮点击回调
        """
        super().__init__()
        self._page = page
        self._session_state = session_state
        self._on_conversation_changed = on_conversation_changed
        self._on_new_conversation = on_new_conversation
        self._on_delete_conversation = on_delete_conversation
        self._on_rename_conversation = on_rename_conversation
        self._on_settings_click = on_settings_click
        self._logger = get_logger()

        # UI 组件引用
        self._conversation_items: dict[str, ConversationListItem] = {}
        self._list_container: ft.Column | None = None

        # 加载状态控件
        self._loading_indicator: ft.ProgressRing | None = None

        # 设置状态回调
        self._setup_state_callbacks()

        # 构建UI
        self._build_ui()

    def _setup_state_callbacks(self) -> None:
        """设置状态管理回调"""
        self._session_state.set_callbacks(
            on_conversation_changed=self._handle_conversation_changed,
            on_conversation_added=self._handle_conversation_added,
            on_conversation_removed=self._handle_conversation_removed,
            on_conversations_loaded=self._handle_conversations_loaded,
        )

    def _build_ui(self) -> None:
        """构建UI界面"""
        self._logger.info("ConversationSidebar: 开始构建 UI")
        colors = ThemeManager().get_color_scheme()

        # 顶部按钮区域（与旧版 PySide6 前端一致："新增会话" + "设置" 文本按钮）
        new_conversation_button = ft.ElevatedButton(
            "新增会话",
            on_click=self._handle_new_conversation_click,
            style=ft.ButtonStyle(
                color=colors.text_on_primary,
                bgcolor=colors.primary,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            ),
            expand=True,
        )

        settings_button = ft.ElevatedButton(
            "设置",
            on_click=self._handle_settings_click,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.Padding.symmetric(horizontal=12, vertical=5),
            ),
        )

        top_button_row = ft.Row(
            controls=[
                new_conversation_button,
                settings_button,
            ],
            spacing=12,
        )

        # 会话列表容器
        self._list_container = ft.Column(
            controls=[],
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # 主容器（与旧版 PySide6 一致：整体内边距 12，仅列表区域可滚动）
        self.controls = [
            top_button_row,
            ft.Container(height=12),  # 间隔
            self._list_container,
        ]

        self.spacing = 0
        self.padding = 14
        self.scroll = None
        self._logger.info("ConversationSidebar: UI 构建完成")

    def _handle_new_conversation_click(self, e) -> None:
        """新建会话按钮点击处理"""
        self._logger.info("点击新建会话按钮")
        if self._on_new_conversation:
            self._on_new_conversation()

    def _handle_settings_click(self, e) -> None:
        """设置按钮点击处理"""
        self._logger.info("点击设置按钮")
        if self._on_settings_click:
            self._on_settings_click()

    def _handle_conversation_click(self, conversation_id: str) -> None:
        """会话项点击处理"""
        self._logger.info(f"点击会话: {conversation_id}")
        self._session_state.set_current_conversation(conversation_id)
        if self._on_conversation_changed:
            self._on_conversation_changed(conversation_id)

    def _handle_conversation_delete(self, conversation_id: str) -> None:
        """会话删除处理"""
        self._logger.info(f"请求删除会话: {conversation_id}")
        self._show_delete_confirmation(conversation_id)

    def _handle_conversation_rename(self, conversation_id: str) -> None:
        """会话重命名处理"""
        self._logger.info(f"请求重命名会话: {conversation_id}")
        self._show_rename_dialog(conversation_id)

    def _show_delete_confirmation(self, conversation_id: str) -> None:
        """显示删除确认对话框"""
        colors = ThemeManager().get_color_scheme()

        def on_confirm(e):
            """确认删除"""
            dialog.open = False
            self._page.update()

            # 从状态中移除
            self._session_state.remove_conversation(conversation_id)

            # 调用删除回调
            if self._on_delete_conversation:
                self._on_delete_conversation(conversation_id)

        def on_cancel(e):
            """取消删除"""
            dialog.open = False
            self._page.update()

        # 获取会话信息
        session_info = self._session_state.get_conversation(conversation_id)
        title = session_info.title if session_info else "未命名会话"

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("确认删除"),
            content=ft.Text(f"确定要删除会话 \"{title}\" 吗？"),
            actions=[
                ft.TextButton("取消", on_click=on_cancel),
                ft.TextButton(
                    "删除",
                    on_click=on_confirm,
                    style=ft.ButtonStyle(color=colors.error),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    def _show_rename_dialog(self, conversation_id: str) -> None:
        """显示重命名对话框"""
        # 获取当前标题
        session_info = self._session_state.get_conversation(conversation_id)
        current_title = session_info.title if session_info else ""

        title_field = ft.TextField(
            value=current_title or "",
            label="会话名称",
            hint_text="请输入新的会话名称",
            autofocus=True,
            max_length=60,
            on_submit=lambda e: _on_confirm(e),
        )

        def _on_confirm(e):
            """确认重命名"""
            new_title = (title_field.value or "").strip()
            if not new_title:
                new_title = "新会话"

            dialog.open = False
            self._page.update()

            # 更新本地状态
            self._session_state.update_conversation_title(conversation_id, new_title)

            # 同步更新 UI
            item = self._conversation_items.get(conversation_id)
            if item:
                item.set_title(new_title)

            # 调用外部回调（用于持久化到数据库）
            if self._on_rename_conversation:
                self._on_rename_conversation(conversation_id, new_title)

        def _on_cancel(e):
            """取消重命名"""
            dialog.open = False
            self._page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("编辑会话名称"),
            content=title_field,
            actions=[
                ft.TextButton("取消", on_click=_on_cancel),
                ft.TextButton("确定", on_click=_on_confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self._page.overlay.append(dialog)
        dialog.open = True
        self._page.update()

    # ==================== 状态回调处理 ====================

    def _handle_conversation_changed(self, conversation_id: str) -> None:
        """会话切换回调处理"""
        self._update_selection(conversation_id)

    def _handle_conversation_added(self, conversation_id: str) -> None:
        """会话添加回调处理"""
        session_info = self._session_state.get_conversation(conversation_id)
        if session_info:
            self._add_conversation_item(session_info)

    def _handle_conversation_removed(self, conversation_id: str) -> None:
        """会话移除回调处理"""
        self._remove_conversation_item(conversation_id)

    def _handle_conversations_loaded(self) -> None:
        """会话加载完成回调处理"""
        self._refresh_conversation_list()

    # ==================== UI 更新方法 ====================

    def _add_conversation_item(self, session_info: SessionInfo) -> None:
        """添加会话项"""
        conversation_id = session_info.conversation_id
        title = session_info.title or "新会话"

        # 创建会话项
        item = ConversationListItem(
            conversation_id=conversation_id,
            title=title,
            page=self._page,
            on_click=self._handle_conversation_click,
            on_delete=self._handle_conversation_delete,
            on_rename=self._handle_conversation_rename,
            is_selected=(self._session_state.get_current_conversation() == conversation_id),
        )

        # 添加到列表（与旧版 PySide6 一致：追加到底部）
        if self._list_container:
            self._list_container.controls.append(item)
            self._conversation_items[conversation_id] = item
            self._page.update()

    def _remove_conversation_item(self, conversation_id: str) -> None:
        """移除会话项"""
        if conversation_id in self._conversation_items:
            item = self._conversation_items[conversation_id]
            if self._list_container:
                self._list_container.controls.remove(item)
            del self._conversation_items[conversation_id]
            self._page.update()

    def _update_selection(self, conversation_id: str) -> None:
        """更新选中状态"""
        for cid, item in self._conversation_items.items():
            item.set_selected(cid == conversation_id)
        self._page.update()

    def _refresh_conversation_list(self) -> None:
        """刷新会话列表"""
        if not self._list_container:
            return

        # 清空现有列表
        self._list_container.controls.clear()
        self._conversation_items.clear()

        # 添加所有会话
        for session_info in self._session_state.get_all_conversations():
            item = ConversationListItem(
                conversation_id=session_info.conversation_id,
                title=session_info.title or "新会话",
                page=self._page,
                on_click=self._handle_conversation_click,
                on_delete=self._handle_conversation_delete,
                on_rename=self._handle_conversation_rename,
                is_selected=(self._session_state.get_current_conversation() == session_info.conversation_id),
            )
            self._list_container.controls.append(item)
            self._conversation_items[session_info.conversation_id] = item

        self._page.update()

    def load_conversations(self, conversations: list) -> None:
        """
        加载会话列表

        Args:
            conversations: 会话列表（Conversation 对象列表）
        """
        self._session_state.load_from_conversations(conversations)

    def add_conversation(self, conversation) -> None:
        """
        添加会话到侧边栏

        Args:
            conversation: Conversation 对象
        """
        # 将 Conversation 对象转换为 SessionInfo 并添加
        session_info = SessionInfo(
            conversation_id=conversation.conversation_id,
            title=conversation.title or "新会话",
        )
        self._add_conversation_item(session_info)

    def set_selected_conversation(self, conversation_id: str) -> None:
        """
        设置选中的会话

        Args:
            conversation_id: 会话ID
        """
        self._update_selection(conversation_id)

    def remove_conversation(self, conversation_id: str) -> None:
        """
        从侧边栏移除会话项（仅 UI 层，不操作 SessionState）

        Args:
            conversation_id: 会话ID
        """
        self._remove_conversation_item(conversation_id)

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """
        更新会话项标题

        Args:
            conversation_id: 会话ID
            title: 新标题
        """
        item = self._conversation_items.get(conversation_id)
        if item:
            item.set_title(title)

    def show_loading(self) -> None:
        """显示加载状态"""
        if self._loading_indicator is None:
            self._loading_indicator = ft.ProgressRing(
                width=24,
                height=24,
                stroke_width=2,
            )

        # 清空现有会话列表
        if self._list_container:
            self._list_container.controls.clear()

        # 显示加载指示器
        if self._list_container:
            self._list_container.controls.append(
                ft.Container(
                    content=self._loading_indicator,
                    alignment=ft.Alignment(0.5, 0.5),  # 中心对齐 (x=0.5, y=0.5)
                    padding=20,
                )
            )

        self._page.update()

    def hide_loading(self) -> None:
        """隐藏加载状态"""
        if self._loading_indicator and self._list_container:
            # 移除包含 ProgressRing 的所有容器（更可靠的方式）
            self._list_container.controls = [
                c for c in self._list_container.controls
                if not (isinstance(c, ft.Container) and 
                       isinstance(c.content, ft.ProgressRing))
            ]

        self._page.update()
