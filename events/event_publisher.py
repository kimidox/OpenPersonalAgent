"""
事件发布者基类

提供事件发布的便捷封装，简化组件中的事件发布代码。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union
from events.event_types import EventType, EventData, EventPriority
from events.event_bus import EventBus


class EventPublisher:
    """
    事件发布者基类

    为子类提供便捷的事件发布接口，自动处理事件源标识。

    使用示例：
        class MyAgent(EventPublisher):
            def __init__(self):
                super().__init__(source="MyAgent")

            def do_something(self):
                # 发布事件
                self.emit(EventType.TOOL_CALL_START, {"tool": "example"})
    """

    def __init__(self, source: Optional[str] = None):
        """
        初始化事件发布者

        Args:
            source: 事件源标识（None 则使用类名）
        """
        self._source = source or self.__class__.__name__
        self._event_bus = EventBus.get_instance()

    def emit(
        self,
        event_type: EventType,
        data: Union[Dict[str, Any], EventData],
        priority: Optional[EventPriority] = None,
        metadata: Optional[Dict[str, Any]] = None,
        async_mode: bool = False
    ) -> bool:
        """
        发布事件

        Args:
            event_type: 事件类型
            data: 事件数据
            priority: 事件优先级（可选）
            metadata: 额外元数据（可选）
            async_mode: 是否异步处理

        Returns:
            是否成功发布
        """
        return self._event_bus.emit(
            event_type,
            data,
            source=self._source,
            priority=priority,
            metadata=metadata,
            async_mode=async_mode
        )

    def emit_batch(
        self,
        events: list[tuple[EventType, Dict[str, Any]]]
    ) -> bool:
        """
        批量发布事件

        Args:
            events: 事件列表 [(event_type, data), ...]

        Returns:
            是否全部成功发布
        """
        success = True
        for event_type, data in events:
            if not self.emit(event_type, data):
                success = False
        return success

    def get_source(self) -> str:
        """获取事件源标识"""
        return self._source

    def set_source(self, source: str):
        """设置事件源标识"""
        self._source = source