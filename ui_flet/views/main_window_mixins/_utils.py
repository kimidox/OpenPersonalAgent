"""
MainWindow 共享辅助函数

包含从 main_window.py 拆分出的顶层辅助函数，供 Mixin 模块使用。
"""


def _get_state_display_text(state: str) -> str:
    """将状态枚举转换为友好的中文显示文本

    Args:
        state: LLM通信状态枚举值

    Returns:
        中文显示文本
    """
    state_map = {
        "IDLE": "空闲",
        "SENDING_REQUEST": "正在发送请求",
        "WAITING_FOR_RESPONSE": "等待响应中",
        "RECEIVING_STREAM": "正在接收响应",
        "COMMUNICATION_ENDED": "通信结束"
    }
    return state_map.get(state, state)


def _get_warning_display_text(warning_type: str, state: str, duration_ms: int) -> str:
    """将告警信息转换为友好的中文显示文本

    Args:
        warning_type: 告警类型（timeout, stream_stall等）
        state: LLM通信状态
        duration_ms: 持续时间（毫秒）

    Returns:
        中文显示文本
    """
    duration_sec = duration_ms // 1000

    if warning_type == "timeout":
        return f"等待响应超时 ({duration_sec}秒)"
    elif warning_type == "stream_stall":
        return f"数据流停滞 ({duration_sec}秒未收到数据)"
    elif warning_type == "response_timeout":
        return f"响应超时 ({duration_sec}秒)"
    elif warning_type == "network_error":
        return f"网络通信异常 ({duration_sec}秒)"
    else:
        return f"未知告警: {warning_type} ({duration_sec}秒)"
