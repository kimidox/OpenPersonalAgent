# ui_flet - Flet UI implementation for PersonalWindowGLM
#
# 注意：后端服务模式（backend_service）无 flet 依赖，但仍需导入
# ui_flet.floating_ball_ipc / floating_ball_process / ipc_optimizer 等子模块。
# 因此 state 导入用 try/except 兜底，flet 缺失时跳过（不影响悬浮球子模块）。

try:
    from ui_flet.state import (
        AppState,
        SessionState,
        StreamState,
        UIState,
        SessionInfo,
        StreamBuffer,
        ButtonStates,
        StreamType,
        InputState,
    )
except ImportError:
    # flet 未安装（后端服务模式）
    pass

__all__ = [
    "AppState",
    "SessionState",
    "StreamState",
    "UIState",
    "SessionInfo",
    "StreamBuffer",
    "ButtonStates",
    "StreamType",
    "InputState",
]