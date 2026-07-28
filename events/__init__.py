"""
事件驱动架构核心模块

提供事件总线、事件类型定义、发布者/订阅者基类。

使用示例：
    from events import EventBus, EventType

    # 订阅事件
    def on_llm_response(event):
        print(f"收到LLM响应: {event.data}")

    EventBus.subscribe(EventType.LLM_RESPONSE, on_llm_response)

    # 发布事件
    EventBus.emit(EventType.LLM_RESPONSE, {"content": "Hello"})
"""
from events.event_types import EventType, EventPriority, EventData
from events.event_bus import EventBus
from events.event_publisher import EventPublisher
from events.event_subscriber import EventSubscriber

__all__ = [
    "EventType",
    "EventPriority",
    "EventData",
    "EventBus",
    "EventPublisher",
    "EventSubscriber",
]