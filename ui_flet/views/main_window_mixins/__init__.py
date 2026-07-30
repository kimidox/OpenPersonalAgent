"""
MainWindow Mixin 模块

将 MainWindow 的大类拆分为多个 Mixin，每个 Mixin 负责一个独立的功能领域。
"""

from ui_flet.views.main_window_mixins.window_events_mixin import WindowEventsMixin
from ui_flet.views.main_window_mixins.conversation_mixin import ConversationManagerMixin
from ui_flet.views.main_window_mixins.stream_typing_mixin import StreamTypingMixin
from ui_flet.views.main_window_mixins.worker_thread_mixin import WorkerThreadMixin
from ui_flet.views.main_window_mixins.scheduled_task_mixin import ScheduledTaskMixin
from ui_flet.views.main_window_mixins.floating_ball_mixin import FloatingBallMixin

__all__ = [
    "WindowEventsMixin",
    "ConversationManagerMixin",
    "StreamTypingMixin",
    "WorkerThreadMixin",
    "ScheduledTaskMixin",
    "FloatingBallMixin",
]
