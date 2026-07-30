"""
悬浮球组件常量定义

包含两类常量：
1. 纯字符串/数值常量：不依赖 PySide6，模块级可用
2. QColor 常量：依赖 PySide6，需在 init_qcolor_constants() 调用后才能访问

Business purpose:
    集中管理悬浮球组件的尺寸、颜色等配置常量，避免分散在各模块中。

Modification notes:
    2026-07-29: 从 floating_ball_process.py 模块级常量迁移至此

Related tests:
    tests/test_floating_ball_widgets.py (待补充)
"""
from __future__ import annotations

from typing import Optional

# ============================================================
# 悬浮球尺寸常量（不依赖 PySide6）
# ============================================================
BALL_SIZE = 50
BALL_MARGIN = 20

# ============================================================
# 聊天窗口尺寸常量（不依赖 PySide6）
# ============================================================
CHAT_WIDTH = 400
CHAT_HEIGHT = 500
CHAT_MIN_WIDTH = 300
CHAT_MIN_HEIGHT = 400

# ============================================================
# 颜色常量 - 字符串形式（不依赖 PySide6）
# ============================================================
DEFAULT_BG_COLOR = "#ffffff"
DEFAULT_TEXT_COLOR = "#1f2937"
DEFAULT_BORDER_COLOR = "#e5e7eb"

# ============================================================
# 颜色常量 - QColor 形式（依赖 PySide6，延迟初始化）
# ============================================================
DEFAULT_PRIMARY_COLOR: Optional[object] = None  # 初始化后为 QColor 实例
DEFAULT_HOVER_COLOR: Optional[object] = None    # 初始化后为 QColor 实例


def init_qcolor_constants() -> None:
    """初始化 QColor 颜色常量。

    必须在 PySide6 导入完成后调用（即 run_floating_ball_process 函数内部）。
    多次调用是安全的（幂等）。

    Side effects:
        修改模块级 DEFAULT_PRIMARY_COLOR 和 DEFAULT_HOVER_COLOR

    Related tests:
        tests/test_floating_ball_widgets.py (待补充)
    """
    global DEFAULT_PRIMARY_COLOR, DEFAULT_HOVER_COLOR
    from PySide6.QtGui import QColor
    DEFAULT_PRIMARY_COLOR = QColor("#3B82F6")
    DEFAULT_HOVER_COLOR = QColor("#2563EB")
