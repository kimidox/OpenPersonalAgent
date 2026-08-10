"""连接管理模块。

从 BaseChatModel.py 中提取的客户端管理、错误处理、超时检测相关功能，包括：
- ClientManager: 客户端管理混入类（get_client）
- TimeoutManager: 超时检测混入类（定时器管理、超时告警）
- ErrorHandlingMixin: API 错误处理混入类（_handle_api_error）
- StateTransitionMixin: LLM 通信状态转换混入类

这些混入类被 BaseChatModel 继承使用，将连接管理职责从核心抽象基类中分离出来。
"""
from __future__ import annotations

import threading
import time as _time
from typing import Any, Callable, Optional

from openai import OpenAI, APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

from logger import get_module_logger
from llm.communication_state import LLMCommunicationContext, LLMCommunicationState, transition_state, create_initial_context
from llm.stream_parser import StreamResult

logger = get_module_logger("BaseChatModel")


class ClientManager:
    """客户端管理混入类。

    提供 OpenAI 客户端的懒初始化和缓存功能。
    """

    def __init__(self, **kwargs: Any) -> None:
        self._client: Optional[OpenAI] = None

    def get_client(self) -> OpenAI:
        """获取或懒初始化 OpenAI 客户端实例。

        首次调用时使用实例的 api_key 和 base_url 创建客户端，
        后续调用直接返回已创建的实例。

        Returns:
            OpenAI: 已初始化的 OpenAI 客户端。
        """
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client


class TimeoutManager:
    """超时检测混入类。

    提供超时定时器管理和超时告警功能。
    """

    # 超时阈值（秒）—— 子类/实例可覆盖
    WAITING_FOR_RESPONSE_TIMEOUT = 30  # 等待响应超时30秒
    RECEIVING_STREAM_STALL_TIMEOUT = 60  # 流数据停滞超时60秒

    def __init__(self, **kwargs: Any) -> None:
        self._timeout_timer: Optional[threading.Timer] = None
        self._timeout_timer_lock: threading.Lock = threading.Lock()

    def _start_timeout_timer(self, timeout_seconds: float, timeout_type: str) -> None:
        """启动超时定时器。

        Args:
            timeout_seconds: 超时时间（秒）。
            timeout_type: 超时类型（用于日志和告警）。
        """
        with self._timeout_timer_lock:
            # 先取消现有的定时器
            if self._timeout_timer is not None:
                self._timeout_timer.cancel()

            # 创建新定时器
            self._timeout_timer = threading.Timer(
                timeout_seconds,
                self._check_and_emit_timeout,
                args=[timeout_type]
            )
            self._timeout_timer.daemon = True
            self._timeout_timer.start()
            # 移除高频DEBUG日志：定时器启动

    def _cancel_timeout_timer(self) -> None:
        """取消超时定时器。"""
        with self._timeout_timer_lock:
            if self._timeout_timer is not None:
                self._timeout_timer.cancel()
                self._timeout_timer = None
                # 移除高频DEBUG日志：定时器取消

    def _check_and_emit_timeout(self, timeout_type: str) -> None:
        """检查并发出超时告警。

        Args:
            timeout_type: 超时类型。
        """
        # 获取当前状态快照
        current_state = self._llm_communication_context.state

        # 检查是否仍处于需要检测超时的状态
        if not self._llm_communication_context.is_active():
            # 移除高频DEBUG日志：状态已变为非活跃
            return

        # 根据超时类型构造告警消息
        if timeout_type == "waiting_for_response":
            duration_ms = self._llm_communication_context.duration_ms()
            self._emit_timeout_warning(
                warning_type="timeout",
                message=f"等待LLM响应超时（{self.WAITING_FOR_RESPONSE_TIMEOUT}秒）"
            )
        elif timeout_type == "stream_stall":
            time_since_last_data = self._llm_communication_context.time_since_last_data_ms()
            # 只有当确实存在停滞时才发出告警
            if time_since_last_data >= self.RECEIVING_STREAM_STALL_TIMEOUT * 1000:
                self._emit_timeout_warning(
                    warning_type="stream_stall",
                    message=f"LLM流数据停滞超时（{self.RECEIVING_STREAM_STALL_TIMEOUT}秒未收到数据）"
                )
            # 移除高频DEBUG日志：未达阈值

    def _emit_timeout_warning(self, warning_type: str, message: str) -> None:
        """发出超时告警。

        Args:
            warning_type: 告警类型。
            message: 告警描述消息。
        """
        # 记录WARNING日志
        logger.warning(
            "[LLM通信] 超时告警: type=%s, state=%s, message=%s",
            warning_type,
            self._llm_communication_context.state.value,
            message
        )

        # 发送IPC告警通知
        if self._state_update_callback:
            try:
                # 通过EventBus 发布 LLM 状态告警事件，避免 llm→ui_flet 反向依赖
                # UI 层通过订阅 EventType.LLM_ERROR 事件来构造和发送 IPC 告警消息
                try:
                    from events.event_bus import EventBus
                    from events.event_types import EventType, EventData, EventPriority
                    bus = EventBus.get_instance()
                    bus.emit(
                        EventType.LLM_ERROR,
                        data={
                            "warning_type": warning_type,
                            "state": self._llm_communication_context.state.value,
                            "duration_ms": self._llm_communication_context.duration_ms(),
                            "model": self._llm_communication_context.model_name,
                            "session_id": self._llm_communication_context.session_id,
                            "message": message,
                            "timestamp": _time.time(),
                        },
                        source="BaseChatModel",
                        priority=EventPriority.HIGH,
                    )
                except ImportError:
                    # EventBus 不可用时，回退到直接通过 callback 传递原始告警数据
                    # UI 层负责将原始数据转换为 IPC 消息格式
                    warning_data = {
                        "type": "llm_state_warning",
                        "warning_type": warning_type,
                        "timestamp": _time.time(),
                        "state": self._llm_communication_context.state.value,
                        "duration_ms": self._llm_communication_context.duration_ms(),
                        "model": self._llm_communication_context.model_name,
                        "session_id": self._llm_communication_context.session_id,
                        "message": message,
                    }
                    self._state_update_callback(warning_data)
            except Exception as e:
                logger.warning("[LLM通信] 发送超时告警失败: %s", e)


class StateTransitionMixin:
    """LLM 通信状态转换混入类。

    提供状态转换、回调设置和状态通知功能。
    """

    def __init__(self, **kwargs: Any) -> None:
        # LLM通信状态追踪
        self._llm_communication_context: LLMCommunicationContext = create_initial_context(
            model_name=self.model_name
        )
        self._state_update_callback: Optional[Callable[[dict], None]] = None

    def set_state_update_callback(self, callback: Callable[[dict], None] | None) -> None:
        """设置状态更新回调函数

        Args:
            callback: 回调函数，接受一个 dict 参数（状态信息）或 None 以清除回调
        """
        self._state_update_callback = callback

    def _transition_communication_state(
        self,
        new_state: LLMCommunicationState,
        **kwargs: Any,
    ) -> None:
        """转换LLM通信状态并发送IPC通知。

        Args:
            new_state: 新的通信状态。
            **kwargs: 可选的关键字参数，用于更新上下文字段。
        """
        old_state = self._llm_communication_context.state
        old_duration = self._llm_communication_context.duration_ms()

        # 状态转换
        self._llm_communication_context = transition_state(
            self._llm_communication_context,
            new_state,
            **kwargs
        )

        # 日志记录
        duration_info = f"耗时: {old_duration}ms" if old_duration > 0 else ""
        logger.info(
            "[LLM通信] 状态转换: %s -> %s (%s)",
            old_state.value,
            new_state.value,
            duration_info
        )

        # 超时检测逻辑
        # 当状态转换为 SENDING_REQUEST 时，取消之前的定时器
        if new_state == LLMCommunicationState.SENDING_REQUEST:
            self._cancel_timeout_timer()
        # 当状态转换为 RECEIVING_STREAM 时，取消等待响应定时器，启动流停滞检测
        elif new_state == LLMCommunicationState.RECEIVING_STREAM:
            self._cancel_timeout_timer()
            # 启动流停滞超时检测
            self._start_timeout_timer(self.RECEIVING_STREAM_STALL_TIMEOUT, "stream_stall")
        # 当状态转换为 COMMUNICATION_ENDED 或 IDLE 时，取消所有定时器
        elif new_state in (LLMCommunicationState.COMMUNICATION_ENDED, LLMCommunicationState.IDLE):
            self._cancel_timeout_timer()

        # 发送IPC通知
        if self._state_update_callback:
            try:
                context_dict = {
                    "state": self._llm_communication_context.state.value,
                    "model_name": self._llm_communication_context.model_name,
                    "session_id": self._llm_communication_context.session_id,
                    "duration_ms": self._llm_communication_context.duration_ms(),
                    "time_since_last_data_ms": self._llm_communication_context.time_since_last_data_ms(),
                }
                self._state_update_callback(context_dict)
            except Exception as e:
                logger.warning("[LLM通信] 状态更新回调失败: %s", e)


class ErrorHandlingMixin:
    """API 错误处理混入类。

    提供统一的 API 错误处理逻辑。
    """

    def _handle_api_error(
        self,
        error: Exception,
        stream_callback: Callable[[str, str], None],
    ) -> StreamResult:
        """处理 API 调用异常，统一返回 StreamResult.from_error。

        将 stream_request_llm_with_tools / stream_complete 中重复的
        except 分支统一为单个方法，减少约 80 行重复代码。

        Args:
            error: 捕获的异常对象
            stream_callback: 流式回调，用于发送错误消息

        Returns:
            StreamResult: 错误类型的 StreamResult
        """
        if isinstance(error, BadRequestError):
            error_msg = f"请求参数错误: {error}"
            if "inappropriate content" in str(error).lower() or "data inspection" in str(error).lower():
                error_msg = "内容审核未通过：输入内容可能包含不适当的内容，请修改后重试。"
        elif isinstance(error, AuthenticationError):
            error_msg = f"API认证失败: {error}"
        elif isinstance(error, RateLimitError):
            error_msg = f"API请求频率超限: {error}"
        elif isinstance(error, APIConnectionError):
            error_msg = f"API连接失败: {error}"
        elif isinstance(error, APIError):
            error_msg = f"API错误: {error}"
        else:
            error_msg = f"未知错误: {error}"

        stream_callback(error_msg, "assistant")
        self._transition_communication_state(
            LLMCommunicationState.COMMUNICATION_ENDED,
            error_message=error_msg
        )
        self._transition_communication_state(LLMCommunicationState.IDLE)
        return StreamResult.from_error(error_msg)
