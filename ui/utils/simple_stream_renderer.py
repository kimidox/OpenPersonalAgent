from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject

from ui.components.message_list import MessageListWidget


class SimpleStreamRenderer(QObject):
    """简化的流式渲染器，不使用动画，直接追加内容"""
    
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state: dict[str, Any] | None = None
        self._has_completed_with_token_usage: bool = False
        
    def start(
        self, 
        message_list: MessageListWidget, 
        initial_text: str, 
        stream_type: str, 
        conversation_id: str
    ) -> None:
        """开始流式渲染"""
        self._has_completed_with_token_usage = False
        
        # 检查是否已经有同类型同会话的渲染
        if self._state is not None:
            # 只有三个条件全部匹配才追加：同会话、同类型、同 message_list
            if (self._state["conversation_id"] == conversation_id and 
                self._state["stream_type"] == stream_type and
                self._state["message_list"] == message_list):
                # 直接追加到现有消息
                self._state["full_text"] += initial_text
                self._update_display()
                return
            else:
                # 类型不同或会话不同或 message_list 不同，强制完成之前的流
                self.complete()
        
        # 直接创建带有内容的消息，而不是空消息
        msg_type = "think" if stream_type == "think" else "assistant"
        card = message_list.add_message(msg_type, initial_text)
        if card is None:
            # 如果消息没有被添加（例如空文本），直接返回
            self._state = None
            return
        
        self._state = {
            "message_list": message_list,
            "conversation_id": conversation_id,
            "stream_type": stream_type,
            "full_text": initial_text
        }
        
    def append(self, text: str) -> None:
        """追加文本到当前流"""
        if self._state is None:
            return
        self._state["full_text"] += text
        self._update_display()
        
    def complete(self, token_usage: dict[str, Any] | None = None) -> str | None:
        """完成流式渲染，返回完整内容"""
        if self._state is None:
            return None
        message_list = self._state["message_list"]
        full_text = self._state["full_text"]
        message_list.finalize_last_message(token_usage)
        if token_usage:
            self._has_completed_with_token_usage = True
        self._state = None
        return full_text
    
    def has_completed_with_token_usage(self) -> bool:
        """检查是否已通过token_usage完成了流式渲染"""
        return self._has_completed_with_token_usage
        
    def _update_display(self) -> None:
        """更新显示"""
        if self._state is None:
            return
        message_list = self._state["message_list"]
        message_list.update_last_message(self._state["full_text"])
        
    def is_active(self) -> bool:
        """检查是否有活跃的流"""
        return self._state is not None
        
    def get_conversation_id(self) -> str | None:
        """获取当前流的会话ID"""
        if self._state is None:
            return None
        return self._state.get("conversation_id")
        
    def get_stream_type(self) -> str:
        """获取当前流的类型"""
        if self._state is None:
            return ""
        return self._state.get("stream_type", "")
        
    def get_current_text(self) -> str:
        """获取当前流的文本"""
        if self._state is None:
            return ""
        return self._state.get("full_text", "")
        
    def cancel(self) -> None:
        """取消当前流"""
        self._state = None
