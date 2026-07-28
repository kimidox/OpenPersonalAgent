"""
事件订阅者基类

提供事件订阅的便捷封装，简化组件中的事件订阅代码。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional
from events.event_types import EventType, EventData, EventPriority
from events.event_bus import EventBus


class EventSubscriber:
    """
    事件订阅者基类

    为子类提供便捷的事件订阅接口，自动管理订阅生命周期。

    使用示例：
        class MyUI(EventSubscriber):
            def __init__(self):
                super().__init__(subscriber_id="MyUI")

                # 订阅事件
                self.subscribe(EventType.MESSAGE_APPEND, self._on_message)

            def _on_message(self, event: EventData):
                print(f"收到消息: {event.data}")

            def cleanup(self):
                # 取消所有订阅
                self.unsubscribe_all()
    """

    def __init__(self, subscriber_id: Optional[str] = None):
        """
        初始化事件订阅者

        Args:
            subscriber_id: 订阅者ID（None 则使用类名）
        """
        self._subscriber_id = subscriber_id or self.__class__.__name__
        self._event_bus = EventBus.get_instance()
        self._subscriptions: Dict[EventType, List[str]] = {}
        self._lock = threading.Lock()

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[EventData], None],
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False
    ) -> str:
        """
        订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
            priority: 优先级
            once: 是否只触发一次

        Returns:
            订阅ID
        """
        subscription_id = f"{self._subscriber_id}_{event_type.value}_{len(self._subscriptions.get(event_type, []))}"

        # 订阅事件
        full_id = self._event_bus.subscribe(
            event_type,
            callback,
            priority=priority,
            once=once,
            subscriber_id=subscription_id
        )

        # 记录订阅
        with self._lock:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = []
            self._subscriptions[event_type].append(full_id)

        return full_id

    def unsubscribe(self, event_type: EventType) -> bool:
        """
        取消指定事件类型的所有订阅

        Args:
            event_type: 事件类型

        Returns:
            是否成功取消
        """
        with self._lock:
            if event_type not in self._subscriptions:
                return False

            success = True
            for subscription_id in self._subscriptions[event_type]:
                if not self._event_bus.unsubscribe(event_type, subscription_id):
                    success = False

            del self._subscriptions[event_type]
            return success

    def unsubscribe_all(self):
        """取消所有订阅"""
        with self._lock:
            for event_type, subscription_ids in list(self._subscriptions.items()):
                for subscription_id in subscription_ids:
                    self._event_bus.unsubscribe(event_type, subscription_id)
            self._subscriptions.clear()

    def get_subscriber_id(self) -> str:
        """获取订阅者ID"""
        return self._subscriber_id

    def set_subscriber_id(self, subscriber_id: str):
        """设置订阅者ID"""
        self._subscriber_id = subscriber_id

    def get_active_subscriptions(self) -> Dict[EventType, List[str]]:
        """获取活跃的订阅"""
        with self._lock:
            return dict(self._subscriptions)

    def __del__(self):
        """析构函数：自动清理订阅"""
        try:
            self.unsubscribe_all()
        except Exception:
            pass  # 忽略析构时的错误