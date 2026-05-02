from __future__ import annotations

from typing import Optional

import config
from .llm_config_manager import get_current_config, LLMConfig

from .BaseChatModel import BaseChatModel
from .gemma_chat_model import GemmaChatModel
from .glm_chat_model import GLMChatModel
from .qwen_chat_model import QwenChatModel


def get_chat_model(
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    enable_thinking: Optional[bool] = None,
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

    extra_body = {"enable_thinking": et}

    if model == "glm-5" or model.startswith("glm"):
        return GLMChatModel(model_name=model, api_key=key, base_url=url, temperature=temp, top_p=tp, frequency_penalty=fp, extra_body=extra_body)
    if model.startswith("qwen3.5") or model.startswith("qwen"):
        return QwenChatModel(model_name=model, api_key=key, base_url=url, temperature=temp, top_p=tp, frequency_penalty=fp, extra_body=extra_body)
    if model.startswith("gemma"):
        return GemmaChatModel(model_name=model, api_key=key, base_url=url, temperature=temp, top_p=tp, frequency_penalty=fp, extra_body=extra_body)

    return QwenChatModel(model_name=model, api_key=key, base_url=url, temperature=temp, top_p=tp, frequency_penalty=fp, extra_body=extra_body)