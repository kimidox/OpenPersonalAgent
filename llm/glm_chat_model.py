from __future__ import annotations

from typing import Any, Optional

from openai import APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

from .BaseChatModel import BaseChatModel


class GLMChatModel(BaseChatModel):
    """
    GLM 系列实现：
    - 使用新格式（tools + tool_calls）
    - 支持 reasoning_content
    - 内置智能缓冲机制
    """

    def build_tools(self) -> list[dict]:
        """返回新格式工具 schema。"""
        return self.build_skill_agent_tools()

    def extract_tool_call(self, message: Any) -> Optional[dict[str, str]]:
        """
        尝试从模型输出中提取工具调用信息。
        GLM优先使用旧格式 function_call，同时兼容新格式 tool_calls。
        返回格式：{"name": ..., "arguments": "...json...", "reasoning_content": ...} 或 None
        """
        reasoning_content = getattr(message, "reasoning_content", None) or ""

        function_call = getattr(message, "function_call", None)
        if function_call is not None:
            name = getattr(function_call, "name", None)
            arguments = getattr(function_call, "arguments", None) or "{}"
            if name:
                return {"name": str(name), "arguments": str(arguments), "reasoning_content": str(reasoning_content)}

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            first = tool_calls[0]
            func = getattr(first, "function", None)
            if func is None:
                return None
            name = getattr(func, "name", None)
            arguments = getattr(func, "arguments", None) or "{}"
            if not name:
                return None
            return {"name": str(name), "arguments": str(arguments), "reasoning_content": str(reasoning_content)}

        return None

    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> Any:
        """发起一次带 tools 的补全，返回 choices[0].message。"""
        # 最终防线：校验并修复所有 messages 中的 tool_calls
        from llm.BaseChatModel import _sanitize_messages_for_api
        messages = _sanitize_messages_for_api(messages)
        try:
            response = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
                top_p=self.top_p,
                frequency_penalty=self.frequency_penalty,
                extra_body=self.extra_body,
            )
            return response.choices[0].message
        except BadRequestError as e:
            raise RuntimeError(f"请求参数错误: {e}")
        except AuthenticationError as e:
            raise RuntimeError(f"API认证失败: {e}")
        except RateLimitError as e:
            raise RuntimeError(f"API请求频率超限: {e}")
        except APIConnectionError as e:
            raise RuntimeError(f"API连接失败: {e}")
        except APIError as e:
            raise RuntimeError(f"API错误: {e}")

    def request_llm_with_tools(self, messages: list[dict], tools: list[dict]) -> Optional[dict[str, str]]:
        """发起带工具的补全请求并提取工具调用信息。

        发送消息和工具定义到 GLM 模型，从响应中优先提取 function_call（旧格式），
        兼容 tool_calls（新格式）的 name、arguments 和 reasoning_content。

        Args:
            messages: 对话消息列表。
            tools: 工具定义列表。

        Returns:
            包含 name、arguments、reasoning_content 的字典，无工具调用时返回 None。

        Raises:
            RuntimeError: API 请求失败时抛出。
        """
        # 最终防线：校验并修复所有 messages 中的 tool_calls
        from llm.BaseChatModel import _sanitize_messages_for_api
        messages = _sanitize_messages_for_api(messages)
        try:
            response = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
                top_p=self.top_p,
                frequency_penalty=self.frequency_penalty,
                extra_body=self.extra_body,
            )
            msg = response.choices[0].message
            return self.extract_tool_call(msg)
        except BadRequestError as e:
            raise RuntimeError(f"请求参数错误: {e}")
        except AuthenticationError as e:
            raise RuntimeError(f"API认证失败: {e}")
        except RateLimitError as e:
            raise RuntimeError(f"API请求频率超限: {e}")
        except APIConnectionError as e:
            raise RuntimeError(f"API连接失败: {e}")
        except APIError as e:
            raise RuntimeError(f"API错误: {e}")
