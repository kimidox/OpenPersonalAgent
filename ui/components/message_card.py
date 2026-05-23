from __future__ import annotations

from typing import Any, Literal

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QTextEdit, QToolButton, QVBoxLayout, QWidget

from ui.styles.style_manager import StyleManager
from ui.utils.markdown_utils import markdown_to_html_fragment, normalize_newlines


MessageType = Literal["user", "assistant", "tool", "think", "tool_call"]


class MessageCardWidget(QWidget):
    def __init__(
        self,
        msg_type: MessageType,
        content: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._msg_type = msg_type
        self._raw_content = content
        self._is_finalized = False
        self._setup_ui()
        if content:
            self.update_content(content)

    def set_available_width(self, available_width: int) -> None:
        """根据可用宽度设置气泡的最大宽度"""
        if self._msg_type == "user":
            max_width = min(700, int(available_width * 0.5))
            self._bubble_frame.setMaximumWidth(max_width)
            self._bubble_container.setMaximumWidth(max_width)
        else:
            max_width = min(int(available_width * 0.92), 1200)
            self._bubble_frame.setMaximumWidth(max_width)
            self._bubble_container.setMaximumWidth(max_width)
        # 确保布局更新
        self.updateGeometry()

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

        # 内容 - 使用 QLabel 但确保正确的换行行为
        self._content_label = QLabel()
        self._content_label.setWordWrap(False)
        self._content_label.setTextFormat(Qt.RichText)
        self._content_label.setOpenExternalLinks(True)
        self._content_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._apply_content_style()
        self._bubble_layout.addWidget(self._content_label)

        import config
        self._copy_button = None
        if self._msg_type in config.COPY_BUTTON_ENABLED_TYPES:
            self._copy_button = QToolButton()
            self._copy_button.setText("复制")
            self._copy_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self._copy_button.setCursor(Qt.PointingHandCursor)
            self._copy_button.setFixedSize(50, 24)
            self._apply_copy_button_style()
            self._copy_button.clicked.connect(self._on_copy_clicked)
            self._copy_button.hide()

            self._button_layout = QHBoxLayout()
            self._button_layout.setContentsMargins(0, 6, 0, 0)
            self._button_layout.setSpacing(0)
            self._button_layout.addStretch()
            self._button_layout.addWidget(self._copy_button)
            self._bubble_layout.addLayout(self._button_layout)

        self._container_layout.addWidget(self._bubble_frame)

        if self._copy_button:
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

    def _apply_bubble_style(self) -> None:
        style_map = {
            "user": """
                QFrame {
                    background-color: #eff6ff;
                    border-radius: 12px;
                }
            """,
            "assistant": """
                QFrame {
                    background-color: #ffffff;
                    border-radius: 12px;
                }
            """,
            "think": """
                QFrame {
                    background-color: #f9fafb;
                    border-radius: 12px;
                }
            """,
            "tool": """
                QFrame {
                    background-color: #f3f4f6;
                    border-radius: 10px;
                }
            """,
            "tool_call": """
                QFrame {
                    background-color: #fff7ed;
                    border-radius: 10px;
                }
            """,
        }
        self._bubble_frame.setStyleSheet(style_map.get(self._msg_type, style_map["assistant"]))

    def _apply_caption_style(self) -> None:
        style_map = {
            "user": "font-size: 11px; color: #2563eb; font-weight: 600; padding: 2px 4px; margin: 0px;",
            "assistant": "font-size: 11px; color: #2563eb; font-weight: 600; padding: 2px 4px; margin: 0px;",
            "think": "font-size: 11px; color: #6b7280; font-weight: 600; padding: 2px 4px; margin: 0px;",
            "tool": "font-size: 11px; font-weight: 600; color: #374151; padding: 2px 4px; margin: 0px;",
            "tool_call": "font-size: 11px; font-weight: 600; color: #c05621; padding: 2px 4px; margin: 0px;",
        }
        self._caption_label.setStyleSheet(style_map.get(self._msg_type, style_map["assistant"]))
        
        # 对齐方式：用户消息右对齐，其他左对齐
        if self._msg_type == "user":
            self._caption_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        else:
            self._caption_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

    def _apply_content_style(self) -> None:
        style_map = {
            "user": "color: #374151; font-size: 10pt; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;",
            "assistant": "color: #374151; font-size: 10pt; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;",
            "think": "color: #4b5563; font-size: 10pt; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;",
            "tool": "font-size: 11px; color: #6b7280; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;",
            "tool_call": "font-size: 11px; color: #7b341e; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif;",
        }
        self._content_label.setStyleSheet(style_map.get(self._msg_type, style_map["assistant"]))

    def update_content(self, text: str) -> None:
        # 去除文本前后的空白行和空格
        trimmed_text = text.strip() if text else ""
        self._raw_content = trimmed_text
        if self._is_finalized:
            html = markdown_to_html_fragment(trimmed_text)
            self._content_label.setText(html)
        else:
            from html import escape
            escaped = escape(trimmed_text)
            escaped = escaped.replace("\n", "<br>")
            self._content_label.setText(escaped)

    def append_content(self, text: str) -> None:
        self._raw_content += text
        self.update_content(self._raw_content)

    def finalize_content(self, token_usage: dict[str, Any] | None = None) -> None:
        if self._is_finalized:
            return
        self._is_finalized = True
        
        html = markdown_to_html_fragment(self._raw_content)
        
        if token_usage:
            import config
            if config.TOKEN_USAGE_SHOW_IN_UI:
                total = token_usage.get("total_tokens")
                if total is not None:
                    html += f'<div style="color:#9ca3af;font-size:9pt;margin-top:8px;">Token: {total}</div>'
        
        self._content_label.setText(html)

    def get_content(self) -> str:
        return self._raw_content

    def get_message_type(self) -> MessageType:
        return self._msg_type

    def is_finalized(self) -> bool:
        return self._is_finalized

    def sizeHint(self):
        return super().sizeHint()

    def minimumSizeHint(self):
        return super().minimumSizeHint()

    def _apply_copy_button_style(self) -> None:
        self._copy_button.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                color: #6b7280;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                font-size: 11px;
                padding: 2px 8px;
            }
            QToolButton:hover {
                background-color: #f3f4f6;
                color: #374151;
                border-color: #d1d5db;
            }
            QToolButton:pressed {
                background-color: #e5e7eb;
            }
        """)

    def _on_copy_clicked(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self._raw_content)
        self._copy_button.setText("已复制")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self._copy_button.setText("复制"))

    def enterEvent(self, event) -> None:
        if self._copy_button:
            self._copy_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._copy_button:
            self._copy_button.hide()
        super().leaveEvent(event)
