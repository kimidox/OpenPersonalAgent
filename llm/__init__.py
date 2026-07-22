from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import config
from openai import APIError, APIConnectionError, AuthenticationError, RateLimitError

from .llm_config_manager import (
    LLMConfig,
    LLMConfigItem,
    clear_failed_configs,
    get_active_config_item,
    get_all_failed_info,
    get_current_config,
    get_failed_config_ids,
    get_next_config,
    has_available_config,
    is_auto_switch_enabled,
    list_configs,
    mark_config_failed,
    record_switch_event,
    switch_to_next_config,
)

from .BaseChatModel import BaseChatModel, StreamResult, StreamResultType
from .gemma_chat_model import GemmaChatModel
from .glm_chat_model import GLMChatModel
from .qwen_chat_model import QwenChatModel


SwitchCallback = Callable[[str, str, str], None]


def get_chat_model(
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    enable_thinking: Optional[bool] = None,
    enable_vision: Optional[bool] = None,
    enable_deep_thinking: Optional[bool] = None,
    enable_tool_call: Optional[bool] = None,
) -> BaseChatModel:
    """
    根据配置获取具体的模型实现。
    优先使用传入的参数，若无则从配置管理器获取，最后使用 env 默认值。
    """
    current_config = get_current_config()
    
    model = model_name or current_config.model_name or config.MODEL_NAME
    key = api_key or current_config.api_key or config.OPENAI_API_KEY
    url = base_url or current_config.base_url or config.OPENAI_BASE_URL
    temp = temperature if temperature is not None else current_config.temperature
    tp = top_p if top_p is not None else current_config.top_p
    fp = frequency_penalty if frequency_penalty is not None else current_config.frequency_penalty
    et = enable_thinking if enable_thinking is not None else current_config.enable_thinking
    ev = enable_vision if enable_vision is not None else current_config.enable_vision
    edt = enable_deep_thinking if enable_deep_thinking is not None else current_config.enable_deep_thinking
    etc = enable_tool_call if enable_tool_call is not None else current_config.enable_tool_call

    # 同时传两个兼容字段：
    # - enable_thinking (顶层): 阿里云 DashScope 私有字段
    # - chat_template_kwargs.enable_thinking: llama.cpp 通过 gguf chat template 控制思考模式
    # llama.cpp 不识别顶层 enable_thinking，会忽略；DashScope 通常忽略 chat_template_kwargs。
    # 这样无论后端是云端还是本地 llama.cpp，关闭思考的意图都能真正生效。
    extra_body = {
        "enable_thinking": edt,
        "chat_template_kwargs": {"enable_thinking": edt},
    }

    if not model:
        return QwenChatModel(
            model_name=model,
            api_key=key,
            base_url=url,
            temperature=temp,
            top_p=tp,
            frequency_penalty=fp,
            extra_body=extra_body,
            enable_vision=ev,
            enable_deep_thinking=edt,
            enable_tool_call=etc,
        )

    if model == "glm-5" or model.startswith("glm"):
        return GLMChatModel(
            model_name=model,
            api_key=key,
            base_url=url,
            temperature=temp,
            top_p=tp,
            frequency_penalty=fp,
            extra_body=extra_body,
            enable_vision=ev,
            enable_deep_thinking=edt,
            enable_tool_call=etc,
        )
    if model.startswith("qwen3.5") or model.startswith("qwen") or model.startswith("Qwen"):
        return QwenChatModel(
            model_name=model,
            api_key=key,
            base_url=url,
            temperature=temp,
            top_p=tp,
            frequency_penalty=fp,
            extra_body=extra_body,
            enable_vision=ev,
            enable_deep_thinking=edt,
            enable_tool_call=etc,
        )
    if model.startswith("gemma"):
        return GemmaChatModel(
            model_name=model,
            api_key=key,
            base_url=url,
            temperature=temp,
            top_p=tp,
            frequency_penalty=fp,
            extra_body=extra_body,
            enable_vision=ev,
            enable_deep_thinking=edt,
            enable_tool_call=etc,
        )

    return QwenChatModel(
        model_name=model,
        api_key=key,
        base_url=url,
        temperature=temp,
        top_p=tp,
        frequency_penalty=fp,
        extra_body=extra_body,
        enable_vision=ev,
        enable_deep_thinking=edt,
        enable_tool_call=etc,
    )


@dataclass
class FallbackResult:
    """故障切换结果。"""
    success: bool
    model: Optional[BaseChatModel]
    config_item: Optional[LLMConfigItem]
    error_message: Optional[str]
    all_failed: bool
    failed_configs: dict[str, str]


@dataclass
class ChatModelWithFallback:
    """带故障切换能力的聊天模型包装器。"""
    model: BaseChatModel
    config_item: LLMConfigItem
    switch_callback: Optional[SwitchCallback] = None

    def get_model(self) -> BaseChatModel:
        return self.model

    def get_config(self) -> LLMConfigItem:
        return self.config_item

    def on_failure(self, error: Exception, reason: str) -> Optional[ChatModelWithFallback]:
        """
        当发生错误时调用，尝试切换到下一个配置。
        返回新的 ChatModelWithFallback 或 None（全部失败）。
        """
        mark_config_failed(self.config_item.id)

        if not is_auto_switch_enabled():
            return None

        next_config = switch_to_next_config()
        if next_config is None:
            return None

        if self.switch_callback:
            try:
                self.switch_callback(self.config_item.name, next_config.name, reason)
            except Exception:
                pass

        new_model = get_chat_model(
            model_name=next_config.model_name,
            api_key=next_config.api_key,
            base_url=next_config.base_url,
            temperature=next_config.temperature,
            top_p=next_config.top_p,
            frequency_penalty=next_config.frequency_penalty,
            enable_thinking=next_config.enable_thinking,
            enable_vision=next_config.enable_vision,
            enable_deep_thinking=next_config.enable_deep_thinking,
            enable_tool_call=next_config.enable_tool_call,
        )

        return ChatModelWithFallback(
            model=new_model,
            config_item=next_config,
            switch_callback=self.switch_callback,
        )


def is_recoverable_error(error: Exception) -> bool:
    """
    判断错误是否为可恢复错误（应该触发故障切换）。
    包括：网络错误、认证失败、频率超限、API错误、超时、响应异常。
    """
    if isinstance(error, APIConnectionError):
        return True
    if isinstance(error, AuthenticationError):
        return True
    if isinstance(error, RateLimitError):
        return True
    if isinstance(error, APIError):
        return True
    if isinstance(error, TimeoutError):
        return True
    error_str = str(error).lower()
    timeout_keywords = ["timeout", "timed out", "超时"]
    connection_keywords = ["connection", "connect", "网络", "连接"]
    auth_keywords = ["auth", "unauthorized", "forbidden", "认证", "权限"]
    rate_keywords = ["rate", "limit", "频率", "限制"]
    for kw in timeout_keywords:
        if kw in error_str:
            return True
    for kw in connection_keywords:
        if kw in error_str:
            return True
    for kw in auth_keywords:
        if kw in error_str:
            return True
    for kw in rate_keywords:
        if kw in error_str:
            return True
    return False


def get_error_reason(error: Exception) -> str:
    """根据错误类型返回可读的错误原因。"""
    if isinstance(error, APIConnectionError):
        return "API连接失败"
    if isinstance(error, AuthenticationError):
        return "API认证失败"
    if isinstance(error, RateLimitError):
        return "API请求频率超限"
    if isinstance(error, APIError):
        return f"API错误: {error}"
    if isinstance(error, TimeoutError):
        return "请求超时"
    error_str = str(error).lower()
    if "timeout" in error_str or "timed out" in error_str:
        return "请求超时"
    if "connection" in error_str or "connect" in error_str:
        return "网络连接失败"
    return f"未知错误: {error}"


def get_chat_model_with_fallback(
    switch_callback: Optional[SwitchCallback] = None,
) -> ChatModelWithFallback:
    """
    获取带故障切换能力的聊天模型。
    返回 ChatModelWithFallback 对象，包含模型、配置和切换回调。
    """
    config_item = get_active_config_item()
    if config_item is None:
        raise ValueError("没有可用的配置")

    model = get_chat_model(
        model_name=config_item.model_name,
        api_key=config_item.api_key,
        base_url=config_item.base_url,
        temperature=config_item.temperature,
        top_p=config_item.top_p,
        frequency_penalty=config_item.frequency_penalty,
        enable_thinking=config_item.enable_thinking,
        enable_vision=config_item.enable_vision,
        enable_deep_thinking=config_item.enable_deep_thinking,
        enable_tool_call=config_item.enable_tool_call,
    )

    return ChatModelWithFallback(
        model=model,
        config_item=config_item,
        switch_callback=switch_callback,
    )


def try_next_config_on_failure(
    current_config_id: str,
    error: Exception,
    switch_callback: Optional[SwitchCallback] = None,
) -> Optional[ChatModelWithFallback]:
    """
    在失败时尝试切换到下一个配置。
    参数：
        current_config_id: 当前失败的配置ID
        error: 发生的错误
        switch_callback: 切换时的回调函数
    返回：
        新的 ChatModelWithFallback 或 None（全部失败）
    """
    if not is_recoverable_error(error):
        return None

    mark_config_failed(current_config_id)

    if not is_auto_switch_enabled():
        return None

    current_config = None
    for c in list_configs():
        if c.id == current_config_id:
            current_config = c
            break

    next_config = switch_to_next_config()
    if next_config is None:
        return None

    reason = get_error_reason(error)

    if switch_callback and current_config:
        try:
            switch_callback(current_config.name, next_config.name, reason)
        except Exception:
            pass

    new_model = get_chat_model(
        model_name=next_config.model_name,
        api_key=next_config.api_key,
        base_url=next_config.base_url,
        temperature=next_config.temperature,
        top_p=next_config.top_p,
        frequency_penalty=next_config.frequency_penalty,
        enable_thinking=next_config.enable_thinking,
        enable_vision=next_config.enable_vision,
        enable_deep_thinking=next_config.enable_deep_thinking,
        enable_tool_call=next_config.enable_tool_call,
    )

    return ChatModelWithFallback(
        model=new_model,
        config_item=next_config,
        switch_callback=switch_callback,
    )


def execute_with_fallback(
    action: Callable[[BaseChatModel], any],
    switch_callback: Optional[SwitchCallback] = None,
    max_retries: int = 10,
) -> FallbackResult:
    """
    执行带故障切换的操作。
    参数：
        action: 要执行的操作，接收 BaseChatModel 参数
        switch_callback: 切换时的回调函数
        max_retries: 最大重试次数
    返回：
        FallbackResult 对象
    """
    clear_failed_configs()
    failed_configs: dict[str, str] = {}
    attempts = 0

    while attempts < max_retries:
        config_item = get_active_config_item()
        if config_item is None:
            break

        if config_item.id in failed_configs:
            next_config = switch_to_next_config()
            if next_config is None:
                break
            config_item = next_config

        model = get_chat_model(
            model_name=config_item.model_name,
            api_key=config_item.api_key,
            base_url=config_item.base_url,
            temperature=config_item.temperature,
            top_p=config_item.top_p,
            frequency_penalty=config_item.frequency_penalty,
            enable_thinking=config_item.enable_thinking,
            enable_vision=config_item.enable_vision,
            enable_deep_thinking=config_item.enable_deep_thinking,
            enable_tool_call=config_item.enable_tool_call,
        )

        try:
            result = action(model)
            return FallbackResult(
                success=True,
                model=model,
                config_item=config_item,
                error_message=None,
                all_failed=False,
                failed_configs=failed_configs,
            )
        except Exception as e:
            reason = get_error_reason(e)
            failed_configs[config_item.id] = f"{config_item.name}: {reason}"
            mark_config_failed(config_item.id)

            if not is_recoverable_error(e):
                return FallbackResult(
                    success=False,
                    model=model,
                    config_item=config_item,
                    error_message=f"不可恢复的错误: {reason}",
                    all_failed=False,
                    failed_configs=failed_configs,
                )

            next_config = switch_to_next_config()
            if next_config is None:
                break

            if switch_callback:
                try:
                    switch_callback(config_item.name, next_config.name, reason)
                except Exception:
                    pass

        attempts += 1

    all_failed_info = get_all_failed_info()
    error_details = "\n".join(
        [f"  - {name}: {failed_configs.get(cid, '未知错误')}" for cid, name in all_failed_info.items()]
    )
    error_message = f"所有配置组均尝试失败:\n{error_details}" if error_details else "所有配置组均尝试失败"

    return FallbackResult(
        success=False,
        model=None,
        config_item=None,
        error_message=error_message,
        all_failed=True,
        failed_configs=failed_configs,
    )