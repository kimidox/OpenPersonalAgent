"""
悬浮球子进程组件包

此包中的所有组件依赖 PySide6，必须在 run_floating_ball_process() 内部
通过延迟 import 触发加载。模块级直接 import 此包会导致 PySide6 在
multiprocessing spawn 序列化阶段被加载，引发失败。

Business purpose:
    提供悬浮球的所有 UI 组件（Live2D、消息气泡、聊天窗口、悬浮球主窗口）。

Modification notes:
    2026-07-29: 从 run_floating_ball_process 内部类提取为独立模块

Related tests:
    tests/test_floating_ball_widgets.py (待补充)
"""
from __future__ import annotations

from floating_ball.floating_ball_widgets._constants import (
    BALL_SIZE,
    BALL_MARGIN,
    CHAT_WIDTH,
    CHAT_HEIGHT,
    CHAT_MIN_WIDTH,
    CHAT_MIN_HEIGHT,
    DEFAULT_BG_COLOR,
    DEFAULT_TEXT_COLOR,
    DEFAULT_BORDER_COLOR,
    init_qcolor_constants,
)
from floating_ball.floating_ball_widgets.live2d_widget import Live2DWidget
from floating_ball.floating_ball_widgets.message_bubble import MessageBubble
from floating_ball.floating_ball_widgets.floating_chat_window import FloatingChatWindow
from floating_ball.floating_ball_widgets.floating_ball_window import FloatingBallWindow

__all__ = [
    # 初始化
    "init_qcolor_constants",
    # 组件类
    "Live2DWidget",
    "MessageBubble",
    "FloatingChatWindow",
    "FloatingBallWindow",
    # 尺寸常量
    "BALL_SIZE",
    "BALL_MARGIN",
    "CHAT_WIDTH",
    "CHAT_HEIGHT",
    "CHAT_MIN_WIDTH",
    "CHAT_MIN_HEIGHT",
    # 颜色常量（字符串）
    "DEFAULT_BG_COLOR",
    "DEFAULT_TEXT_COLOR",
    "DEFAULT_BORDER_COLOR",
]
