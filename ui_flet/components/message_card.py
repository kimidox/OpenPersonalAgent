"""
消息卡片组件

提供各类消息的可视化卡片，支持用户、助手、工具、思考等类型。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager, get_color
from ui_flet.utils.markdown_utils import create_markdown_content
from ui_flet.utils.message_utils import extract_display_content, is_multimodal_content

if TYPE_CHECKING:
    from ui_flet.utils.file_upload_manager import UploadedFileInfo

# 消息类型
MessageType = Literal["user", "assistant", "tool", "think", "tool_call"]


@dataclass
class MessageData:
    """消息数据结构"""
    id: str
    msg_type: MessageType
    content: str
    timestamp: datetime
    token_usage: dict[str, Any] | None = None
    is_finalized: bool = False


class MessageCard(ft.Container):
    """
    消息卡片组件

    支持不同类型消息的显示：
    - 用户消息：右对齐，蓝色背景
    - 助手消息：左对齐，灰色背景
    - 工具消息：居中，带边框
    - 思考消息：折叠显示，斜体样式
    """

    def __init__(
        self,
        msg_type: MessageType,
        content: str = "",
        message_id: str = "",
        timestamp: datetime | None = None,
        token_usage: dict[str, Any] | None = None,
        files: list[UploadedFileInfo] | None = None,
        on_copy: callable = None,
        on_speak: callable = None,
    ):
        """
        初始化消息卡片

        Args:
            msg_type: 消息类型
            content: 消息内容
            message_id: 消息ID
            timestamp: 时间戳
            token_usage: Token用量信息
            files: 附件文件列表（仅用户消息显示）
            on_copy: 复制按钮回调
            on_speak: 朗读按钮回调
        """
        super().__init__()

        self._logger = get_logger()
        self._msg_type = msg_type
        self._raw_content = content
        self._message_id = message_id or f"msg_{datetime.now().timestamp()}"
        self._timestamp = timestamp or datetime.now()
        self._token_usage = token_usage
        self._is_finalized = False
        self._on_copy = on_copy
        self._on_speak = on_speak
        self._files = files or []
        self._mode_badge_text: str | None = None

        # 主题管理器
        self._theme_manager = ThemeManager()
        self._colors = self._theme_manager.get_color_scheme()

        # 构建UI
        self._build_ui()

        # 如果有内容，立即渲染
        if content:
            self.update_content(content)

        self._logger.debug(f"MessageCard: 创建消息卡片 {self._msg_type}")

    def _build_ui(self) -> None:
        """构建卡片UI（与旧版 PySide6 前端布局一致）"""
        # 创建气泡容器
        self._bubble = self._create_bubble()

        # 标题行：用户消息右对齐，其他左对齐；旧版只显示角色标题
        title_alignment = (
            ft.MainAxisAlignment.END if self._msg_type == "user" else ft.MainAxisAlignment.START
        )
        caption_text_align = (
            ft.TextAlign.RIGHT if self._msg_type == "user" else ft.TextAlign.LEFT
        )
        self._title_row = ft.Row(
            [
                ft.Text(
                    self._get_caption(),
                    size=11,
                    color=self._get_caption_color(),
                    weight=ft.FontWeight.W_600,
                    text_align=caption_text_align,
                ),
            ],
            alignment=title_alignment,
            spacing=0,
        )

        # 设置容器属性
        # 注意：
        # 1. 不能使用 tight=True，否则会与气泡宽度形成循环依赖
        # 2. Flet 的 Container.width 只接受 Number（int/float），
        #    不支持百分比字符串 "88%" —— 旧代码传入 "88%" 会被 Flutter
        #    端忽略，导致气泡宽度变成 None 并塌缩成不可见。
        # 3. 之前用 Row + expand=88/92 实现的是"强制占 88% 宽度"，
        #    不是 max-width，导致气泡永远填满 88%，对短内容观感很差。
        #    现在的方案：让气泡按内容自适应宽度（外层 Column 的
        #    horizontal_alignment 仍控制左右对齐）。Markdown widget
        #    内部会按可用宽度自动换行，对超长单词由 webview 自然处理。
        self.content = ft.Column(
            [
                self._title_row,
                self._bubble,  # 直接放气泡，按内容自适应宽度
            ]
            + (
                [self._create_file_info_row()] if self._files else []
            ),
            horizontal_alignment=self._get_alignment(),
            spacing=4,
            # tight=True,  # 移除以修复"消息卡片不渲染"问题
        )

        # 设置容器样式（旧版消息间距底部 14px）
        self.padding = ft.Padding(left=16, top=4, right=16, bottom=14)
        self.expand = True
        self.on_hover = self._handle_hover

    def _get_alignment(self) -> ft.CrossAxisAlignment:
        """获取对齐方式"""
        if self._msg_type == "user":
            return ft.CrossAxisAlignment.END
        else:
            return ft.CrossAxisAlignment.START

    def _create_file_info_row(self) -> ft.Container:
        """创建文件信息行（显示在用户消息气泡下方）"""
        chips = []
        for f in self._files:
            chip = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ATTACH_FILE, size=12, color=self._colors.text_muted),
                        ft.Text(f.original_name, size=10, color=self._colors.text_muted),
                        ft.Text(
                            f.get_file_size_display(),
                            size=9,
                            color=self._colors.text_muted,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
                bgcolor=self._colors.bg_page,
                border_radius=6,
                padding=ft.Padding(left=8, top=3, right=8, bottom=3),
                border=ft.Border(
                    left=ft.BorderSide(0.5, self._colors.border),
                    top=ft.BorderSide(0.5, self._colors.border),
                    right=ft.BorderSide(0.5, self._colors.border),
                    bottom=ft.BorderSide(0.5, self._colors.border),
                ),
            )
            chips.append(chip)

        return ft.Container(
            content=ft.Row(
                chips,
                alignment=ft.MainAxisAlignment.END,
                spacing=4,
                wrap=True,
            ),
            margin=ft.Margin(top=2, left=0, right=0, bottom=0),
        )

    def _get_caption(self) -> str:
        """获取消息标题（与旧版 PySide6 一致）"""
        captions = {
            "user": "用户",
            "assistant": "助手",
            "tool": "工具",
            "think": "助手-think",
            "tool_call": "调用工具",
        }
        return captions.get(self._msg_type, "消息")

    def _get_caption_color(self) -> str:
        """获取标题颜色（与旧版 PySide6 一致）"""
        if self._msg_type in ("user", "assistant"):
            return self._colors.primary
        elif self._msg_type == "think":
            return self._colors.text_muted
        else:
            return self._colors.text

    def _format_timestamp(self) -> str:
        """格式化时间戳"""
        return self._timestamp.strftime("%H:%M")

    def _create_bubble(self) -> ft.Container:
        """创建消息气泡（宽度、padding、圆角、阴影均与旧版 PySide6 一致）"""
        # 内容区域
        # 注意：使用 ft.Column 作为容器，可以容纳文本和图片
        # 对于纯文本消息，内部使用 ft.Text 组件（有固有宽度）
        # 对于多模态消息，会同时显示文本和图片组件
        self._text_content = ft.Text(
            value="",
            selectable=True,
            size=13,
            color=self._colors.text,
            expand=False,  # 不撑满父容器，按内容自适应
        )

        # 多模态内容容器（包含文本和图片）
        self._content_markdown = ft.Column(
            [self._text_content],
            spacing=8,
            tight=True,  # 按内容自适应宽度
        )

        # Token 用量标签（旧版仅显示总计，字号 9pt）
        self._token_label = ft.Text(
            "",
            size=9,
            color=self._colors.text_muted,
            visible=False,
        )

        # 模式徽章
        self._mode_badge = ft.Container(
            content=ft.Text(
                "",
                size=9,
                color="white",
                weight=ft.FontWeight.W_500,
            ),
            bgcolor=self._get_mode_badge_color(),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            margin=ft.Margin(top=4, left=0, right=0, bottom=0),
            visible=False,
        )

        # 操作按钮
        self._button_row = self._create_buttons()

        # 气泡内部列（旧版无内部间距，通过各元素 margin 控制）
        # 注意：必须使用 tight=True，让 Column 按内容自适应宽度。
        # 否则 Column 会撑满气泡的可用宽度，Markdown widget 渲染 HTML
        # 时会按父容器宽度展开，导致"短内容也占满整行"（用户消息
        # "CCC" 这种短文本气泡也会拉成与消息区同宽）。
        # tight=True 时，Column 尺寸由最宽子控件决定，Markdown 按
        # 内容（如 "CCC" 三个字符）渲染，气泡自然变窄。
        # 对超长单词/URL，Markdown 内部 webview 会按 CSS 自然换行
        # （如果超出 ListView 宽度，可后续加 word-break 优化）。
        bubble_content = ft.Column(
            [
                self._content_markdown,
                self._token_label,
                self._mode_badge,
                self._button_row,
            ],
            spacing=0,
            tight=True,  # 恢复：让气泡按内容自适应宽度
        )

        # 气泡容器
        # 注意：
        # 1. Flet 的 Container.width 不支持百分比字符串，已移除 width="88%" 等。
        # 2. 不要设置 expand=True，让气泡按内容自适应宽度。
        # 3. 不要设置 alignment。没有固定宽度时，Container 的 alignment
        #    会让它自动撑满父容器，导致短文本气泡也填满整行。
        #    左右对齐由外层 Column 的 horizontal_alignment 控制。
        return ft.Container(
            content=bubble_content,
            bgcolor=self._get_bubble_bgcolor(),
            border=self._get_bubble_border(),
            border_radius=self._get_bubble_radius(),
            padding=self._get_bubble_padding(),
            # width=self._get_bubble_width(),  # 移除：Flet 不支持百分比字符串
            # alignment=self._get_bubble_alignment(),  # 移除：会导致气泡撑满父容器
            shadow=self._get_bubble_shadow(),
            # expand=True,  # 移除：让气泡按内容自适应宽度
        )

    def _get_bubble_bgcolor(self) -> str:
        """获取气泡背景色（与旧版 PySide6 CSS 一致）"""
        if self._msg_type == "user":
            return "#eff6ff"
        elif self._msg_type == "think":
            return "#f9fafb"
        elif self._msg_type == "tool":
            return "#f3f4f6"
        elif self._msg_type == "tool_call":
            return "#fff7ed"
        else:
            return self._colors.surface

    def _get_bubble_border(self) -> ft.Border | None:
        """获取气泡边框（旧版 tool/tool_call 均无边框）"""
        return None

    def _get_bubble_radius(self) -> float:
        """获取气泡圆角（旧版用户/助手/思考 12px，工具 10px）"""
        if self._msg_type in ("user", "assistant", "think"):
            return 12
        else:
            return 10

    def _get_bubble_padding(self) -> ft.Padding:
        """获取气泡内边距（旧版用户/助手/思考 10px 14px，工具 8px 12px）"""
        if self._msg_type in ("user", "assistant", "think"):
            return ft.Padding(left=14, top=10, right=14, bottom=10)
        else:
            return ft.Padding(left=12, top=8, right=12, bottom=8)

    def _get_bubble_width(self) -> float | str | None:
        """获取气泡宽度（按百分比，与旧版 PySide6 一致）"""
        if self._msg_type == "user":
            return "88%"
        else:
            return "92%"

    def _get_bubble_alignment(self) -> ft.Alignment | None:
        """获取气泡容器内部对齐"""
        if self._msg_type == "user":
            return ft.Alignment(1, 0)  # 右中对齐
        return ft.Alignment(-1, 0)  # 左中对齐

    def _get_bubble_shadow(self) -> ft.BoxShadow | None:
        """获取气泡阴影（与旧版 PySide6 CSS 一致）"""
        if self._msg_type == "user":
            return ft.BoxShadow(
                spread_radius=0,
                blur_radius=3,
                color="#1d4ed81f",  # rgba(37,99,235,0.12) 近似
                offset=ft.Offset(0, 1),
            )
        elif self._msg_type == "assistant":
            return ft.BoxShadow(
                spread_radius=0,
                blur_radius=3,
                color="#00000014",  # rgba(0,0,0,0.08)
                offset=ft.Offset(0, 1),
            )
        elif self._msg_type == "think":
            return ft.BoxShadow(
                spread_radius=0,
                blur_radius=3,
                color="#0000000f",  # rgba(0,0,0,0.06)
                offset=ft.Offset(0, 1),
            )
        elif self._msg_type in ("tool", "tool_call"):
            return ft.BoxShadow(
                spread_radius=0,
                blur_radius=2,
                color="#0000000d",  # rgba(0,0,0,0.05)
                offset=ft.Offset(0, 1),
            )
        return None

    def _create_buttons(self) -> ft.Row:
        """创建操作按钮（默认隐藏，悬停显示，与旧版一致）"""
        buttons = []

        # 朗读按钮（仅助手消息）
        if self._on_speak and self._msg_type == "assistant":
            self._speak_btn = ft.IconButton(
                icon=ft.Icons.VOLUME_UP,
                icon_size=16,
                icon_color=self._colors.text_muted,
                on_click=self._handle_speak,
                tooltip="朗读",
            )
            buttons.append(self._speak_btn)

        # 复制按钮
        if self._on_copy:
            self._copy_btn = ft.IconButton(
                icon=ft.Icons.CONTENT_COPY,
                icon_size=16,
                icon_color=self._colors.text_muted,
                on_click=self._handle_copy,
                tooltip="复制",
            )
            buttons.append(self._copy_btn)

        return ft.Row(
            buttons,
            alignment=ft.MainAxisAlignment.END,
            spacing=4,
            visible=False,
        )

    def _handle_copy(self, e) -> None:
        """处理复制"""
        self._logger.debug("MessageCard: 复制消息")
        if self._on_copy:
            self._on_copy(self._raw_content)

    def _handle_speak(self, e) -> None:
        """处理朗读"""
        self._logger.debug("MessageCard: 朗读消息")
        if self._on_speak:
            self._on_speak(self._raw_content)

    def _handle_hover(self, e: ft.ControlEvent) -> None:
        """悬停时显示/隐藏操作按钮（与旧版一致）"""
        if not self._button_row.controls:
            return
        is_hover = e.data == "true"
        # 未 final 时不在悬停时显示按钮，避免干扰流式输出
        if is_hover and not self._is_finalized:
            return
        self._button_row.visible = is_hover
        # 优先只更新按钮行本身，避免 page.update() 整页重渲染打断文本选择
        try:
            self._button_row.update()
        except Exception:
            try:
                if self.page is not None:
                    self.page.update()
            except Exception:
                pass

    def _get_mode_badge_color(self) -> str:
        """根据模式文本获取徽章颜色"""
        style_text = (self._mode_badge_text or "").lower()
        if "复杂" in style_text or "complex" in style_text:
            return "#3b82f6"
        elif "简单" in style_text or "simple" in style_text:
            return "#9ca3af"
        elif "闲聊" in style_text or "chat" in style_text:
            return "#10b981"
        return "#6b7280"

    def set_mode_badge(self, mode_text: str) -> None:
        """设置模式徽章"""
        self._mode_badge_text = mode_text
        if not mode_text:
            self._mode_badge.visible = False
        else:
            self._mode_badge.content.value = mode_text
            self._mode_badge.bgcolor = self._get_mode_badge_color()
            self._mode_badge.visible = True
        self._safe_update(self._mode_badge)

    def _safe_update(self, control: ft.Control) -> None:
        """安全更新控件（未挂载到页面时忽略）

        与 MessageList 保持一致：优先 `self.page.update()` 触发整页重渲染，
        避免 Flet 0.85.3 中 `control.page` 在嵌套容器场景下不可靠，
        导致 hover/复制按钮可见性切换、Markdown 更新等"静默失败"。
        """
        try:
            page = self.page
            if page is not None:
                page.update()
                return
            if getattr(control, "page", None) is not None:
                control.update()
                return
            self._logger.debug(
                "MessageCard: _safe_update 跳过（控件未挂载到页面）"
            )
        except RuntimeError:
            pass

    def update_content(self, content: str | list[Any]) -> None:
        """
        更新消息内容

        Args:
            content: 新的消息内容，可以是：
                - 字符串：纯文本消息
                - 列表：多模态消息（包含文本和图片）
        """
        self._raw_content = content

        # 提取显示内容（处理字符串和列表两种格式）
        display_data = extract_display_content(content)
        text = display_data["text"]
        images = display_data["images"]
        has_images = display_data["has_images"]

        self._logger.debug(
            f"MessageCard: 更新内容 - 文本长度: {len(text)}, "
            f"图片数量: {len(images)}, 多模态: {has_images}"
        )

        # 清空现有的内容控件（保留第一个文本控件）
        while len(self._content_markdown.controls) > 1:
            self._content_markdown.controls.pop()

        # 更新文本内容
        self._text_content.value = text

        # 如果包含图片，添加图片组件
        if has_images:
            self._logger.debug(f"MessageCard: 添加 {len(images)} 张图片")
            for idx, img_data in enumerate(images):
                try:
                    img_url = img_data.get("url", "")
                    if not img_url:
                        self._logger.warning(f"图片 {idx} 的 URL 为空，跳过")
                        continue

                    # 创建图片组件
                    img_component = self._create_image_component(img_url, idx)
                    self._content_markdown.controls.append(img_component)
                    self._logger.debug(f"MessageCard: 添加图片 {idx + 1}")

                except Exception as e:
                    self._logger.error(f"创建图片组件 {idx} 时发生错误: {e}", exc_info=True)
                    # 添加降级提示
                    fallback_text = ft.Text(
                        "[图片加载失败]",
                        size=12,
                        color=self._colors.text_muted,
                        italic=True,
                    )
                    self._content_markdown.controls.append(fallback_text)

        # 更新显示
        self._safe_update(self._content_markdown)

    def _create_image_component(self, url: str, index: int) -> ft.Container:
        """
        创建图片显示组件

        Args:
            url: 图片 URL（可以是 base64 data URL 或普通 URL）
            index: 图片索引（用于错误处理）

        Returns:
            ft.Container: 包含图片的容器组件
        """
        # 创建图片控件
        # 注意：ft.Image 的 src 支持 data URL（data:image/png;base64,...）
        image = ft.Image(
            src=url,
            width=200,  # 限制宽度为 200px
            height=None,  # 高度自适应
            fit=ft.ImageFit.CONTAIN,
            border_radius=ft.BorderRadius(top=8, bottom=8, left=8, right=8),
            error_content=ft.Text(
                "[图片加载失败]",
                size=12,
                color=self._colors.text_muted,
                italic=True,
            ),
        )

        # 包裹在容器中，添加样式
        container = ft.Container(
            content=image,
            margin=ft.Margin(top=4, left=0, right=0, bottom=0),
            # 添加边框和阴影效果
            border=ft.Border(
                left=ft.BorderSide(0.5, self._colors.border),
                top=ft.BorderSide(0.5, self._colors.border),
                right=ft.BorderSide(0.5, self._colors.border),
                bottom=ft.BorderSide(0.5, self._colors.border),
            ),
            border_radius=8,
            padding=4,
            # 添加轻微阴影
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=2,
                color="#00000014",
                offset=ft.Offset(0, 1),
            ),
        )

        return container

    def append_content(self, text: str) -> None:
        """
        追加内容（用于流式更新）

        Args:
            text: 要追加的文本
        """
        # 流式更新只支持字符串内容的追加
        # 如果当前内容是列表（多模态），转换为字符串后再追加
        if isinstance(self._raw_content, list):
            self._logger.warning(
                "append_content 不支持多模态消息，将转换为纯文本"
            )
            # 提取当前文本内容
            display_data = extract_display_content(self._raw_content)
            self._raw_content = display_data["text"]

        self._raw_content += text
        self.update_content(self._raw_content)

    def finalize_content(self, token_usage: dict[str, Any] | None = None) -> None:
        """
        完成内容渲染

        Args:
            token_usage: Token用量信息
        """
        self._is_finalized = True
        self._logger.debug(f"MessageCard: 完成渲染 {self._msg_type}")

        if token_usage:
            self._token_usage = token_usage

            # 显示Token用量（旧版仅显示总计）
            if self._msg_type == "assistant":
                prompt_tokens = token_usage.get("prompt_tokens", 0)
                completion_tokens = token_usage.get("completion_tokens", 0)
                total_tokens = token_usage.get("total_tokens", prompt_tokens + completion_tokens)

                self._token_label.value = f"Token: {total_tokens}"
                self._token_label.visible = True
                self._safe_update(self._token_label)

    def get_content(self) -> str:
        """获取消息内容"""
        return self._raw_content

    def get_message_type(self) -> MessageType:
        """获取消息类型"""
        return self._msg_type

    def is_finalized(self) -> bool:
        """是否已完成渲染"""
        return self._is_finalized

    def show_buttons(self) -> None:
        """显示操作按钮"""
        if self._button_row.controls:
            self._button_row.visible = True
            self._button_row.update()

    def hide_buttons(self) -> None:
        """隐藏操作按钮"""
        if self._button_row.controls:
            self._button_row.visible = False
            self._button_row.update()