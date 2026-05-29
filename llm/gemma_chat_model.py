from __future__ import annotations

import json
import time as _time
from types import SimpleNamespace
from typing import Any, Callable, Optional

from openai import APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

from .BaseChatModel import BaseChatModel
from .token_usage import TokenUsage


class GemmaChatModel(BaseChatModel):
    """
    Gemma 系列实现：
    - 使用新格式（tools + tool_choice）
    - 支持 reasoning_content
    - 内置智能缓冲机制
    """

    def __init__(self, model_name: str | None = None, **kwargs: Any) -> None:
        super().__init__(model_name=model_name, **kwargs)

    def build_tools(self) -> list[dict]:
        return self.build_functions_gemma()

    def build_functions_gemma(self) -> list[dict]:
        """Gemma使用新格式工具定义（type + function 嵌套）"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "select_skill",
                    "description": "加载指定的 Skill 文档，获取完整的操作指南",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_id": {
                                "type": "string",
                                "description": "要加载的 Skill 的 ID"
                            }
                        },
                        "required": ["skill_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "执行 Windows CMD 命令，用于文件操作、脚本执行等",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "要执行的命令"
                            },
                            "cwd": {
                                "type": "string",
                                "description": "工作目录，默认为当前目录"
                            },
                            "skill_id": {
                                "type": "string",
                                "description": "技能ID，用于读取Skill包内文件时指定"
                            },
                            "timeout_sec": {
                                "type": "integer",
                                "description": "命令执行超时时间（秒）"
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_user",
                    "description": "向用户询问关键信息或请求确认",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "要问用户的问题"
                            },
                            "choices": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "可选的回答选项列表"
                            },
                            "context": {
                                "type": "string",
                                "description": "问题的上下文信息"
                            }
                        },
                        "required": ["question"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "完成任务，向用户提供最终答复",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "给用户的最终答复消息"
                            }
                        },
                        "required": ["message"]
                    }
                }
            }
        ]

    def extract_function_call(self, message: Any) -> Optional[dict[str, str]]:
        """
        尝试从模型输出中提取工具调用信息。
        返回格式：{"name": ..., "arguments": "...json...", "reasoning_content": ...} 或 None
        """
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return None

        first = tool_calls[0]
        func = getattr(first, "function", None)
        if func is None:
            return None

        name = getattr(func, "name", None)
        arguments = getattr(func, "arguments", None) or "{}"
        if not name:
            return None

        reasoning_content = getattr(message, "reasoning_content", None) or ""
        return {"name": str(name), "arguments": str(arguments), "reasoning_content": str(reasoning_content)}

    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> Any:
        """发起一次带 tools 的补全，返回 choices[0].message。"""
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
            return self.extract_function_call(msg)
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

    def stream_request_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> Optional[dict[str, str]]:
        """
        流式请求带工具的补全。
        - stream_callback(content: str, type: str) 实时回调：
          - type="think": 推理内容（reasoning_content）
          - type="content": 普通文本内容
        - 返回完整的 function_call（若有），否则返回 None
        - 内置智能缓冲：每 50ms 或累积 30 字符触发一次回调，避免UI过载
        """
        token_usage: Optional[TokenUsage] = None
        all_content_chars = 0

        try:
            stream = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
                top_p=self.top_p,
                frequency_penalty=self.frequency_penalty,
                extra_body=self.extra_body,
                stream=True,
                stream_options={"include_usage": True},
            )
        except BadRequestError as e:
            error_msg = f"请求参数错误: {e}"
            if "inappropriate content" in str(e).lower() or "data inspection" in str(e).lower():
                error_msg = "内容审核未通过：输入内容可能包含不适当的内容，请修改后重试。"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}
        except AuthenticationError as e:
            error_msg = f"API认证失败: {e}"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}
        except RateLimitError as e:
            error_msg = f"API请求频率超限: {e}"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}
        except APIConnectionError as e:
            error_msg = f"API连接失败: {e}"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}
        except APIError as e:
            error_msg = f"API错误: {e}"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}
        except Exception as e:
            error_msg = f"未知错误: {e}"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}

        reasoning_buffer: list[str] = []
        content_buffer: list[str] = []
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        all_reasoning_parts: list[str] = []
        all_content_parts: list[str] = []

        last_callback_time = _time.time()
        callback_interval = 0.05
        min_chars_for_callback = 30

        def _flush_buffer():
            nonlocal last_callback_time
            if reasoning_buffer:
                text = "".join(reasoning_buffer)
                all_reasoning_parts.append(text)
                reasoning_buffer.clear()
                stream_callback(text, "think")
            if content_buffer:
                text = "".join(content_buffer)
                all_content_parts.append(text)
                content_buffer.clear()
                stream_callback(text, "content")
            last_callback_time = _time.time()

        try:
            for chunk in stream:
                usage = getattr(chunk, 'usage', None)
                if usage:
                    token_usage = TokenUsage(
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                        total_tokens=getattr(usage, 'total_tokens', 0) or 0,
                    )
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    reasoning_buffer.append(reasoning)
                    all_content_chars += len(reasoning)
                content = getattr(delta, 'content', None)
                if content:
                    content_buffer.append(content)
                    all_content_chars += len(content)

                current_time = _time.time()
                total_buffered = sum(len(s) for s in reasoning_buffer) + sum(len(s) for s in content_buffer)
                should_flush = (
                    (current_time - last_callback_time >= callback_interval) or
                    (total_buffered >= min_chars_for_callback)
                )
                if should_flush and (reasoning_buffer or content_buffer):
                    _flush_buffer()

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_call_chunks:
                            tool_call_chunks[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc.function:
                            if tc.function.name:
                                tool_call_chunks[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_call_chunks[idx]["arguments"] += tc.function.arguments
        except Exception as e:
            _flush_buffer()
            error_msg = f"流式响应处理错误: {e}"
            stream_callback(error_msg, "content")
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False), "token_usage": None}

        _flush_buffer()

        if token_usage is None:
            estimated_prompt = self._estimate_tokens_from_messages(messages)
            estimated_completion = max(1, all_content_chars // 4)
            token_usage = TokenUsage(
                prompt_tokens=estimated_prompt,
                completion_tokens=estimated_completion,
                total_tokens=estimated_prompt + estimated_completion,
            )

        if not tool_call_chunks:
            content_text = "".join(all_content_parts).strip()
            reasoning_text = "".join(all_reasoning_parts).strip()
            if not content_text and not reasoning_text:
                return None
            return {
                "name": None,
                "arguments": None,
                "content": content_text,
                "reasoning_content": reasoning_text,
                "token_usage": token_usage,
            }

        first_tc = tool_call_chunks[min(tool_call_chunks.keys())]
        name = first_tc["name"].strip()
        arguments = first_tc["arguments"].strip()

        if not name:
            content_text = "".join(all_content_parts).strip()
            reasoning_text = "".join(all_reasoning_parts).strip()
            return {
                "name": None,
                "arguments": None,
                "content": content_text,
                "reasoning_content": reasoning_text,
                "token_usage": token_usage,
            }

        reasoning_content = "".join(all_reasoning_parts)
        return {"name": name, "arguments": arguments, "reasoning_content": reasoning_content, "token_usage": token_usage}

    def stream_complete(
        self,
        messages: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> Any:
        """
        流式纯文本补全。
        - stream_callback(content: str, type: str) 实时回调：
          - type="think": 推理内容（reasoning_content）
          - type="content": 普通文本内容
        - 返回完整消息对象（兼容原有接口）
        - 内置智能缓冲：每 50ms 或累积 30 字符触发一次回调，避免UI过载
        """
        token_usage: Optional[TokenUsage] = None
        all_content_chars = 0

        try:
            stream = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                top_p=self.top_p,
                frequency_penalty=self.frequency_penalty,
                extra_body=self.extra_body,
                stream=True,
                stream_options={"include_usage": True},
            )
        except BadRequestError as e:
            error_msg = f"请求参数错误: {e}"
            if "inappropriate content" in str(e).lower() or "data inspection" in str(e).lower():
                error_msg = "内容审核未通过：输入内容可能包含不适当的内容，请修改后重试。"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except AuthenticationError as e:
            error_msg = f"API认证失败: {e}"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except RateLimitError as e:
            error_msg = f"API请求频率超限: {e}"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except APIConnectionError as e:
            error_msg = f"API连接失败: {e}"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except APIError as e:
            error_msg = f"API错误: {e}"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except Exception as e:
            error_msg = f"未知错误: {e}"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg

        reasoning_buffer: list[str] = []
        content_buffer: list[str] = []
        all_reasoning_parts: list[str] = []
        all_content_parts: list[str] = []

        last_callback_time = _time.time()
        callback_interval = 0.05
        min_chars_for_callback = 30

        def _flush_buffer():
            nonlocal last_callback_time
            if reasoning_buffer:
                text = "".join(reasoning_buffer)
                all_reasoning_parts.append(text)
                reasoning_buffer.clear()
                stream_callback(text, "think")
            if content_buffer:
                text = "".join(content_buffer)
                all_content_parts.append(text)
                content_buffer.clear()
                stream_callback(text, "content")
            last_callback_time = _time.time()

        try:
            for chunk in stream:
                usage = getattr(chunk, 'usage', None)
                if usage:
                    token_usage = TokenUsage(
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                        total_tokens=getattr(usage, 'total_tokens', 0) or 0,
                    )
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    reasoning_buffer.append(reasoning)
                    all_content_chars += len(reasoning)
                content = getattr(delta, 'content', None)
                if content:
                    content_buffer.append(content)
                    all_content_chars += len(content)

                current_time = _time.time()
                total_buffered = sum(len(s) for s in reasoning_buffer) + sum(len(s) for s in content_buffer)
                should_flush = (
                    (current_time - last_callback_time >= callback_interval) or
                    (total_buffered >= min_chars_for_callback)
                )
                if should_flush and (reasoning_buffer or content_buffer):
                    _flush_buffer()
        except Exception as e:
            _flush_buffer()
            error_msg = f"流式响应处理错误: {e}"
            stream_callback(error_msg, "content")
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg

        _flush_buffer()

        if token_usage is None:
            estimated_prompt = self._estimate_tokens_from_messages(messages)
            estimated_completion = max(1, all_content_chars // 4)
            token_usage = TokenUsage(
                prompt_tokens=estimated_prompt,
                completion_tokens=estimated_completion,
                total_tokens=estimated_prompt + estimated_completion,
            )

        msg = SimpleNamespace()
        msg.content = "".join(all_content_parts)
        msg.reasoning_content = "".join(all_reasoning_parts)
        msg.token_usage = token_usage
        return msg