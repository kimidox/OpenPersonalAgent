from __future__ import annotations

from typing import Any, Literal

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QTextEdit, QToolButton, QVBoxLayout, QWidget

from ui.styles.style_manager import StyleManager
from ui.utils.markdown_utils import markdown_to_html_fragment, normalize_newlines
from ui.components.file_preview_card import FilePreviewList
from ui.utils.file_upload_manager import UploadedFileInfo


MessageType = Literal["user", "assistant", "tool", "think", "tool_call"]


class MessageCardWidget(QWidget):
    def __init__(
        self,
        msg_type: MessageType,
        content: str = "",
        files: list[UploadedFileInfo] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._msg_type = msg_type
        self._raw_content = content
        self._is_finalized = False
        self._token_usage: dict[str, Any] | None = None
        self._files: list[UploadedFileInfo] = files or []
        self._available_width: int = 0
        self._stream_throttle_timer: QTimer | None = None
        self._pending_stream_text: str | None = None
        self._setup_ui()
        if content:
            self.update_content(content)
        if self._files:
            self._add_files_to_ui()

    def set_available_width(self, available_width: int) -> None:
        """根据可用宽度设置气泡的最大宽度"""
        self._available_width = available_width
        if self._msg_type == "user":
            max_width = min(700, int(available_width * 0.6))
        else:
            max_width = min(int(available_width * 0.80), 1200)
        self._bubble_frame.setMaximumWidth(max_width)
        self._bubble_container.setMaximumWidth(max_width)
        # 确保布局更新
        self.updateGeometry()
        # 宽度变化后重新计算内容高度
        QTimer.singleShot(0, self._adjust_content_label_height)

    def _setup_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(8, 4, 8, 4)
        self._main_layout.setSpacing(0)

        # 对齐容器 - 专门用于控制消息气泡的对齐
        self._align_container = QWidget()
        self._align_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._align_layout = QHBoxLayout(self._align_container)
        self._align_layout.setContentsMargins(0, 0, 0, 0)
        self._align_layout.setSpacing(0)

        # 气泡整体容器（包含标题和内容）
        self._bubble_container = QWidget()
        # 所有消息都用 Expanding 来确保内容充分利用可用宽度
        self._bubble_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._container_layout = QVBoxLayout(self._bubble_container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(2)

        # 标题
        self._caption_label = QLabel()
        self._caption_label.setText(self._get_caption())
        self._caption_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._apply_caption_style()
        self._container_layout.addWidget(self._caption_label)

        # 气泡框架
        self._bubble_frame = QFrame()
        self._bubble_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        # 根据消息类型设置样式和布局
        self._apply_bubble_style()

        # 气泡内部布局
        self._bubble_layout = QVBoxLayout(self._bubble_frame)
        self._bubble_layout.setContentsMargins(12, 10, 12, 10)
        self._bubble_layout.setSpacing(0)

        # 内容 - 使用 QLabel，统一开启自动换行
        self._content_label = QLabel()
        self._content_label.setWordWrap(True)
        self._content_label.setTextFormat(Qt.RichText)
        self._content_label.setOpenExternalLinks(True)
        self._content_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._apply_content_style()
        self._bubble_layout.addWidget(self._content_label)

        # Token用量标签 - 仅在助手类型消息上可能显示
        self._token_usage_label = QLabel()
        self._token_usage_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._apply_token_usage_style()
        self._token_usage_label.hide()
        self._bubble_layout.addWidget(self._token_usage_label)

        # 模式徽章 - 显示在左下角
        self._mode_badge = QLabel()
        self._mode_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._mode_badge.setWordWrap(False)
        self._mode_badge.hide()
        self._bubble_layout.addWidget(self._mode_badge)

        import config
        self._copy_button = None
        self._speak_button = None
        if self._msg_type in config.COPY_BUTTON_ENABLED_TYPES:
            self._copy_button = QToolButton()
            self._copy_button.setText("复制")
            self._copy_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self._copy_button.setCursor(Qt.PointingHandCursor)
            self._copy_button.setFixedSize(50, 24)
            self._apply_copy_button_style()
            self._copy_button.clicked.connect(self._on_copy_clicked)
            self._copy_button.hide()
            
            # 仅对助手消息添加语音播放按钮
            if self._msg_type == "assistant":
                self._speak_button = QToolButton()
                self._speak_button.setText("朗读")
                self._speak_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
                self._speak_button.setCursor(Qt.PointingHandCursor)
                self._speak_button.setFixedSize(50, 24)
                self._apply_speak_button_style()
                self._speak_button.clicked.connect(self._on_speak_clicked)
                self._speak_button.hide()

            self._button_layout = QHBoxLayout()
            self._button_layout.setContentsMargins(0, 6, 0, 0)
            self._button_layout.setSpacing(8)
            self._button_layout.addStretch()
            if self._speak_button:
                self._button_layout.addWidget(self._speak_button)
            self._button_layout.addWidget(self._copy_button)
            self._bubble_layout.addLayout(self._button_layout)

        self._container_layout.addWidget(self._bubble_frame)
        
        # File preview list (read only for messages)
        self._file_preview_list = FilePreviewList(is_read_only=True)
        self._file_preview_list.hide()
        self._container_layout.addWidget(self._file_preview_list)

        if self._copy_button or self._speak_button:
            self.setMouseTracking(True)

        # 排列气泡 - 使用专门的对齐容器来确保正确的布局
        if self._msg_type == "user":
            # 对齐容器：左边是弹性空间，右边是气泡
            self._align_layout.addStretch()
            self._align_layout.addWidget(self._bubble_container, 0, Qt.AlignmentFlag.AlignRight)
            self._bubble_frame.setMaximumWidth(700)
            self._bubble_container.setMaximumWidth(700)
        else:
            # 对齐容器：左边是气泡，右边是弹性空间
            self._align_layout.addWidget(self._bubble_container, 0, Qt.AlignmentFlag.AlignLeft)
            self._align_layout.addStretch()
            self._bubble_frame.setMaximumWidth(1200)
            self._bubble_container.setMaximumWidth(1200)

        # 将对齐容器添加到主布局
        self._main_layout.addWidget(self._align_container)

    def _get_caption(self) -> str:
        captions = {
            "user": "用户",
            "assistant": "助手",
            "tool": "工具",
            "think": "助手-think",
            "tool_call": "调用工具",
        }
        return captions.get(self._msg_type, "消息")

    def _get_object_name_suffix(self) -> str:
        """将消息类型转换为 objectName 后缀（驼峰命名）"""
        if self._msg_type == "tool_call":
            return "ToolCall"
        return self._msg_type.capitalize()

    def _apply_bubble_style(self) -> None:
        style_map = {
            "user": "message_card_bubble_user",
            "assistant": "message_card_bubble_assistant",
            "think": "message_card_bubble_think",
            "tool": "message_card_bubble_tool",
            "tool_call": "message_card_bubble_tool_call",
        }
        style_name = style_map.get(self._msg_type, style_map["assistant"])
        style = StyleManager.get_style(style_name)
        self._bubble_frame.setObjectName(f"skillAgentMessageBubble{self._get_object_name_suffix()}")
        if style:
            self._bubble_frame.setStyleSheet(style)

    def _apply_caption_style(self) -> None:
        style_map = {
            "user": "message_card_caption_user",
            "assistant": "message_card_caption_assistant",
            "think": "message_card_caption_think",
            "tool": "message_card_caption_tool",
            "tool_call": "message_card_caption_tool_call",
        }
        style_name = style_map.get(self._msg_type, style_map["assistant"])
        style = StyleManager.get_style(style_name)
        self._caption_label.setObjectName(f"skillAgentMessageCaption{self._get_object_name_suffix()}")
        if style:
            self._caption_label.setStyleSheet(style)
        
        # 对齐方式：用户消息右对齐，其他左对齐
        if self._msg_type == "user":
            self._caption_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        else:
            self._caption_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

    def _apply_content_style(self) -> None:
        style_map = {
            "user": "message_card_content_user",
            "assistant": "message_card_content_assistant",
            "think": "message_card_content_think",
            "tool": "message_card_content_tool",
            "tool_call": "message_card_content_tool_call",
        }
        style_name = style_map.get(self._msg_type, style_map["assistant"])
        style = StyleManager.get_style(style_name)
        self._content_label.setObjectName(f"skillAgentMessageContent{self._get_object_name_suffix()}")
        if style:
            self._content_label.setStyleSheet(style)

    def _apply_token_usage_style(self) -> None:
        self._token_usage_label.setObjectName("skillAgentTokenUsageLabel")
        style = StyleManager.get_style("message_card_token_usage")
        if style:
            self._token_usage_label.setStyleSheet(style)
        else:
            self._token_usage_label.setStyleSheet("QLabel#skillAgentTokenUsageLabel { color: #9ca3af; font-size: 9pt; padding-top: 6px; }")

    def update_content(self, text: str) -> None:
        # 去除文本前后的空白行和空格
        trimmed_text = text.strip() if text else ""
        self._raw_content = trimmed_text
        if self._is_finalized:
            self._render_content(trimmed_text)
        else:
            # 流式输出时节流渲染，避免高频 chunk 导致卡顿
            self._pending_stream_text = trimmed_text
            if self._stream_throttle_timer is None:
                self._stream_throttle_timer = QTimer(self)
                self._stream_throttle_timer.setSingleShot(True)
                self._stream_throttle_timer.timeout.connect(self._flush_pending_stream)
            self._stream_throttle_timer.start(60)

    def _flush_pending_stream(self) -> None:
        """节流定时器触发：渲染最新的待处理流式文本"""
        if self._pending_stream_text is None:
            return
        text = self._pending_stream_text
        self._pending_stream_text = None
        self._render_content(text)

    def _render_content(self, text: str) -> None:
        """将文本渲染为 HTML 并更新内容标签与高度"""
        html = markdown_to_html_fragment(text)
        self._content_label.setText(html)
        QTimer.singleShot(0, self._adjust_content_label_height)

    def append_content(self, text: str) -> None:
        self._raw_content += text
        self.update_content(self._raw_content)

    def finalize_content(self, token_usage: dict[str, Any] | None = None) -> None:
        if self._is_finalized:
            return
        self._is_finalized = True
        # 停止节流定时器，丢弃待渲染文本，确保用最终完整文本渲染
        if self._stream_throttle_timer is not None:
            self._stream_throttle_timer.stop()
        self._pending_stream_text = None
        if token_usage is not None:
            self._token_usage = token_usage

        html = markdown_to_html_fragment(self._raw_content)
        self._content_label.setText(html)
        QTimer.singleShot(0, self._adjust_content_label_height)

        if self._token_usage and self._msg_type == "assistant":
            import config
            if config.TOKEN_USAGE_SHOW_IN_UI:
                prompt_tokens = self._token_usage.get("prompt_tokens", 0)
                completion_tokens = self._token_usage.get("completion_tokens", 0)
                total_tokens = self._token_usage.get("total_tokens", prompt_tokens + completion_tokens)
                self._token_usage_label.setText(f"提示词: {prompt_tokens} | 完成: {completion_tokens} | 总计: {total_tokens}")
                self._token_usage_label.show()

    def set_mode_badge(self, mode_text: str) -> None:
        """设置模式徽章，显示在消息卡片左下角"""
        if not mode_text:
            self._mode_badge.hide()
            return
        
        self._mode_badge.setText(mode_text)
        self._mode_badge.setObjectName("skillAgentModeBadge")
        
        # 根据模式文本设置不同样式
        style_text = mode_text.lower()
        if "复杂" in style_text or "complex" in style_text:
            bg_color = "#3b82f6"  # 蓝色
            text_color = "#ffffff"
        elif "简单" in style_text or "simple" in style_text:
            bg_color = "#9ca3af"  # 灰色
            text_color = "#ffffff"
        elif "闲聊" in style_text or "chat" in style_text:
            bg_color = "#10b981"  # 绿色
            text_color = "#ffffff"
        else:
            bg_color = "#6b7280"  # 默认灰色
            text_color = "#ffffff"
        
        self._mode_badge.setStyleSheet(
            f"QLabel#skillAgentModeBadge {{ "
            f"background-color: {bg_color}; "
            f"color: {text_color}; "
            f"border-radius: 8px; "
            f"padding: 2px 8px; "
            f"font-size: 9pt; "
            f"font-weight: 500; "
            f"margin-top: 4px; "
            f"}} "
        )
        self._mode_badge.show()
        self._mode_badge.adjustSize()

    def get_content(self) -> str:
        return self._raw_content

    def get_message_type(self) -> MessageType:
        return self._msg_type
    
    def get_files(self) -> list[dict]:
        from ui.utils.file_upload_manager import UploadedFileInfo
        return [f.to_dict() for f in self._files]
    
    def add_files_from_dict(self, file_dicts: list[dict]) -> None:
        from ui.utils.file_upload_manager import UploadedFileInfo
        for d in file_dicts:
            self._files.append(UploadedFileInfo.from_dict(d))
        self._add_files_to_ui()

    def is_finalized(self) -> bool:
        return self._is_finalized

    def sizeHint(self):
        return super().sizeHint()

    def minimumSizeHint(self):
        return super().minimumSizeHint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 宽度变化后需要按新宽度重新计算内容标签高度
        QTimer.singleShot(0, self._adjust_content_label_height)

    def _adjust_content_label_height(self) -> None:
        """根据内容自动调整气泡宽度与内容标签高度。

        QLabel 在开启 wordWrap + RichText 时，adjustSize/sizeHint 无法正确
        计算富文本换行后的高度。这里用 QTextDocument 按实际宽度计算高度，
        同时根据内容理想宽度自动收缩气泡，避免短内容也占满整宽。
        流式输出期间保持最大宽度，避免气泡宽度随内容增长抖动。
        """
        label = self._content_label
        if label is None:
            return
        html = label.text()
        if not html:
            label.setMaximumHeight(16777215)
            return

        doc = QTextDocument()
        doc.setDocumentMargin(0)  # 移除文档边距，与 QLabel 渲染一致
        doc.setDefaultFont(label.font())  # 使用与 QLabel 相同的字体，确保行高一致
        doc.setHtml(html)

        if self._msg_type == "user":
            max_width = (
                min(700, int(self._available_width * 0.6))
                if self._available_width > 0 else 700
            )
        else:
            max_width = (
                min(int(self._available_width * 0.80), 1200)
                if self._available_width > 0 else 1200
            )
        # 流式输出时保持最大宽度（避免宽度随内容增长抖动），完成后才按内容收缩
        if self._is_finalized:
            ideal_width = int(doc.idealWidth()) + 24  # 24 为 bubble 左右内边距
            bubble_width = max(min(ideal_width, max_width), 150)
        else:
            bubble_width = max(max_width, 150)
        old_max = self._bubble_frame.maximumWidth()
        if old_max != bubble_width:
            self._bubble_frame.setMaximumWidth(bubble_width)
            self._bubble_container.setMaximumWidth(bubble_width)

        # 按气泡宽度计算内容高度
        w = bubble_width - 24
        if w <= 0:
            w = 200
        doc.setTextWidth(w)
        h = int(doc.size().height())
        label.setFixedHeight(h)

    def _apply_copy_button_style(self) -> None:
        self._copy_button.setObjectName("skillAgentCopyButton")
        style = StyleManager.get_style("message_card_copy_button")
        if style:
            self._copy_button.setStyleSheet(style)

    def _apply_speak_button_style(self) -> None:
        self._speak_button.setObjectName("skillAgentSpeakButton")
        style = StyleManager.get_style("message_card_copy_button")
        if style:
            self._speak_button.setStyleSheet(style)

    def _on_copy_clicked(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self._raw_content)
        self._copy_button.setText("已复制")
        QTimer.singleShot(1500, lambda: self._copy_button.setText("复制"))

    def _on_speak_clicked(self) -> None:
        """点击朗读按钮"""
        from tts import is_tts_model_loaded, speak_text
        from PySide6.QtWidgets import QMessageBox
        
        if not is_tts_model_loaded():
            QMessageBox.warning(
                self,
                "提示",
                "TTS 模型未加载，请先在设置中加载语音合成模型"
            )
            return
        
        if not self._raw_content.strip():
            QMessageBox.warning(self, "提示", "消息内容为空，无法朗读")
            return
        
        # 开始朗读
        self._speak_button.setText("朗读中...")
        self._speak_button.setEnabled(False)
        
        import config
        speaker_id = getattr(config, 'TTS_SPEAKER_ID', 0)
        speed = getattr(config, 'TTS_SPEED', 1.0)
        
        try:
            speak_text(
                self._raw_content,
                speaker_id=speaker_id,
                speed=speed
            )
        except Exception as e:
            QMessageBox.warning(self, "警告", f"朗读失败: {str(e)}")
        
        # 恢复按钮状态
        QTimer.singleShot(2000, lambda: self._speak_button.setText("朗读"))
        QTimer.singleShot(2000, lambda: self._speak_button.setEnabled(True))

    def enterEvent(self, event) -> None:
        if self._copy_button:
            self._copy_button.show()
        if self._speak_button:
            self._speak_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._copy_button:
            self._copy_button.hide()
        if self._speak_button:
            self._speak_button.hide()
        super().leaveEvent(event)
        
    def add_files(self, files: list[UploadedFileInfo]) -> None:
        """Add files to the message card"""
        self._files.extend(files)
        self._add_files_to_ui()

    def _add_files_to_ui(self) -> None:
        """Add all stored files to the UI"""
        if not self._files:
            return
        for file_info in self._files:
            self._file_preview_list.add_file(file_info)
        self._file_preview_list.show()
