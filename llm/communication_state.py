"""LLM通信状态管理模块。

此模块定义了用于跟踪LLM通信生命周期的状态枚举和上下文数据结构。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMCommunicationState(str, Enum):
    """LLM通信状态枚举。

    用于表示与LLM通信的不同阶段，从开始到结束的完整生命周期。

    Attributes:
        IDLE: 空闲状态，未与LLM建立通信。
        SENDING_REQUEST: 正在发送请求到LLM。
        WAITING_FOR_RESPONSE: 请求已发送，等待LLM开始响应。
        RECEIVING_STREAM: 正在接收LLM的流式数据。
        COMMUNICATION_ENDED: 通信已结束（正常或异常）。
    """

    IDLE = "idle"
    SENDING_REQUEST = "sending_request"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    RECEIVING_STREAM = "receiving_stream"
    COMMUNICATION_ENDED = "communication_ended"


@dataclass
class LLMCommunicationContext:
    """LLM通信上下文数据类。

    用于存储和管理LLM通信过程中的所有相关状态信息。

    Attributes:
        state: 当前通信状态。
        start_timestamp: 通信开始的时间戳（秒），None表示未开始。
        last_data_timestamp: 最后一次收到数据的时间戳（秒），None表示未收到数据。
        model_name: 当前使用的模型名称，None表示未指定。
        session_id: 当前会话的唯一标识符，None表示未分配。
        error_message: 错误信息字符串，None表示无错误。
    """

    state: LLMCommunicationState = LLMCommunicationState.IDLE
    start_timestamp: float | None = None
    last_data_timestamp: float | None = None
    model_name: str | None = None
    session_id: str | None = None
    error_message: str | None = None

    def is_active(self) -> bool:
        """检查通信是否处于活跃状态。

        Returns:
            如果通信正在进行中（非IDLE且非COMMUNICATION_ENDED），返回True。
        """
        return self.state not in (
            LLMCommunicationState.IDLE,
            LLMCommunicationState.COMMUNICATION_ENDED,
        )

    def duration_ms(self) -> int:
        """计算从通信开始到现在的毫秒数。

        Returns:
            从start_timestamp到现在的毫秒数。如果start_timestamp为None，返回0。
        """
        if self.start_timestamp is None:
            return 0
        return format_duration_ms(self.start_timestamp)

    def time_since_last_data_ms(self) -> int:
        """计算从最后一次收到数据到现在的毫秒数。

        Returns:
            从last_data_timestamp到现在的毫秒数。如果last_data_timestamp为None，返回-1。
        """
        if self.last_data_timestamp is None:
            return -1
        return format_duration_ms(self.last_data_timestamp)

    def __repr__(self) -> str:
        return (
            f"LLMCommunicationContext("
            f"state={self.state.value}, "
            f"model={self.model_name}, "
            f"session={self.session_id}, "
            f"duration={self.duration_ms()}ms"
            f")"
        )


def format_duration_ms(timestamp: float) -> int:
    """计算从给定时间戳到现在的毫秒数。

    Args:
        timestamp: 起始时间戳（秒，由time.time()返回）。

    Returns:
        从给定时间戳到当前时间的毫秒数（整数）。
    """
    return int((time.time() - timestamp) * 1000)


def transition_state(
    context: LLMCommunicationContext,
    new_state: LLMCommunicationState,
    **kwargs: Any,
) -> LLMCommunicationContext:
    """创建新的通信上下文实例，更新状态和可选字段。

    此函数遵循不可变数据原则，不修改原始上下文，而是创建并返回新实例。

    Args:
        context: 原始通信上下文。
        new_state: 新的通信状态。
        **kwargs: 可选的关键字参数，用于更新上下文字段。支持的字段包括：
            - start_timestamp: float | None
            - last_data_timestamp: float | None
            - model_name: str | None
            - session_id: str | None
            - error_message: str | None

    Returns:
        新的LLMCommunicationContext实例，包含更新后的状态和字段。

    Examples:
        >>> ctx = LLMCommunicationContext()
        >>> ctx = transition_state(ctx, LLMCommunicationState.SENDING_REQUEST)
        >>> ctx.state
        <LLMCommunicationState.SENDING_REQUEST: 'sending_request'>
    """
    # 准备新字段值
    new_fields = {
        "state": new_state,
        "start_timestamp": kwargs.get("start_timestamp", context.start_timestamp),
        "last_data_timestamp": kwargs.get("last_data_timestamp", context.last_data_timestamp),
        "model_name": kwargs.get("model_name", context.model_name),
        "session_id": kwargs.get("session_id", context.session_id),
        "error_message": kwargs.get("error_message", context.error_message),
    }

    return LLMCommunicationContext(**new_fields)


def create_initial_context(
    model_name: str | None = None,
    session_id: str | None = None,
) -> LLMCommunicationContext:
    """创建初始通信上下文。

    Args:
        model_name: 可选的模型名称。
        session_id: 可选的会话ID。

    Returns:
        初始状态的LLMCommunicationContext实例。
    """
    return LLMCommunicationContext(
        state=LLMCommunicationState.IDLE,
        model_name=model_name,
        session_id=session_id,
    )