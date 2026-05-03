from __future__ import annotations

import json
import time as _time
from typing import Any, Callable, Optional

from openai import APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

from .BaseChatModel import BaseChatModel


class GemmaChatModel(BaseChatModel):


    def __init__(self, model_name: str | None = None, **kwargs: Any) -> None:
        super().__init__(model_name=model_name, **kwargs)

    def build_tools(self) -> list[dict]:
        return self.build_functions_gemma()

    def build_functions_gemma(self):
        """严格适配本地 Qwen 服务端的工具调用格式（type + function 嵌套）"""
        return [
            {
                "type": "function",  # 必需：类型必须是 "function"
                "function": {  # 必需：嵌套的 function 对象（服务端要求的核心）
                    "name": "return_to_desktop",
                    "description": "Return to the desktop",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "click",
                    "description": "Click at grid cell (gx, gy) shown on screenshot overlay; maps to cell center in screen pixels",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {
                                "type": "number",
                                "description": "Grid column index gx (0=left), non-negative integer",
                                "minimum": 0
                            },
                            "y": {
                                "type": "number",
                                "description": "Grid row index gy (0=top), non-negative integer",
                                "minimum": 0
                            },
                            "button": {
                                "type": "string",
                                "enum": ["left", "right", "middle"],
                                "description": "Mouse button to click (left, right, middle)"
                            }
                        },
                        "required": ["x", "y"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "double_click",
                    "description": "Double click at grid cell (gx, gy) from screenshot overlay",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {
                                "type": "number",
                                "description": "Grid column index gx (0=left)",
                                "minimum": 0
                            },
                            "y": {
                                "type": "number",
                                "description": "Grid row index gy (0=top)",
                                "minimum": 0
                            },
                            "button": {
                                "type": "string",
                                "enum": ["left", "right", "middle"],
                                "description": "Mouse button to double click (left, right, middle)"
                            }
                        },
                        "required": ["x", "y"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "right_click",
                    "description": "Right click at grid cell (gx, gy) from screenshot overlay",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {
                                "type": "number",
                                "description": "Grid column index gx (0=left)",
                                "minimum": 0
                            },
                            "y": {
                                "type": "number",
                                "description": "Grid row index gy (0=top)",
                                "minimum": 0
                            }
                        },
                        "required": ["x", "y"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "move_to",
                    "description": "Move mouse to grid cell center (gx, gy) from screenshot overlay",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {
                                "type": "number",
                                "description": "Grid column index gx (0=left)",
                                "minimum": 0
                            },
                            "y": {
                                "type": "number",
                                "description": "Grid row index gy (0=top)",
                                "minimum": 0
                            }
                        },
                        "required": ["x", "y"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "type_text",
                    "description": "Type text input to the active window",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Text content to type"
                            }
                        },
                        "required": ["text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "press_key",
                    "description": "Press and release a single keyboard key",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Name of the key to press (e.g., 'enter', 'tab', 'a', '1')"
                            }
                        },
                        "required": ["key"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "hotkey",
                    "description": "Press a combination of keyboard keys (e.g., 'ctrl+c', 'alt+f4')",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Key combination (e.g., 'ctrl+c', 'alt+f4')"
                            }
                        },
                        "required": ["key"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "scroll",
                    "description": "Scroll mouse wheel; optional gx, gy to scroll at that grid cell",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "clicks": {
                                "type": "integer",
                                "description": "Number of scroll clicks (positive = up, negative = down)"
                            },
                            "x": {
                                "type": "number",
                                "description": "Optional grid column gx",
                                "minimum": 0
                            },
                            "y": {
                                "type": "number",
                                "description": "Optional grid row gy",
                                "minimum": 0
                            }
                        },
                        "required": ["clicks"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "open_app",
                    "description": "Open an application by its file path",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Full file path to the application executable (e.g., 'C:\\Program Files\\Notepad++\\notepad++.exe')"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "wait",
                    "description": "Wait for a specified number of seconds",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "seconds": {
                                "type": "number",
                                "description": "Number of seconds to wait (supports decimal values)",
                                "minimum": 0.1
                            }
                        },
                        "required": ["seconds"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "screenshot",
                    "description": "Take a screenshot of the entire screen and return the file path",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "over",
                    "description": "Mark the current task as completed",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
        ]
    def extract_function_call(self, message: Any) -> Optional[dict[str, str]]:
        """
        尝试从模型输出中提取工具调用信息。
        返回格式：{"name": ..., "arguments": "...json..."} 或 None
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

        return {"name": str(name), "arguments": str(arguments)}
    def request_llm_with_tools(self, messages: list[dict], tools: list[dict]) -> Optional[dict[str, str]]:
        try:
            response = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
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
        Gemma 流式请求带工具的补全。
        - 使用 tools 参数（Gemma 兼容格式）
        - 内置智能缓冲：每 50ms 或累积 30 字符触发一次回调
        """
        try:
            stream = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
                extra_body=self.extra_body,
                stream=True,
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

        last_callback_time = _time.time()
        callback_interval = 0.05
        min_chars_for_callback = 30

        def _flush_buffer():
            nonlocal last_callback_time
            if reasoning_buffer:
                text = "".join(reasoning_buffer)
                reasoning_buffer.clear()
                stream_callback(text, "think")
            if content_buffer:
                text = "".join(content_buffer)
                content_buffer.clear()
                stream_callback(text, "content")
            last_callback_time = _time.time()

        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    reasoning_buffer.append(reasoning)
                content = getattr(delta, 'content', None)
                if content:
                    content_buffer.append(content)

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
            return {"name": "finish", "arguments": json.dumps({"message": error_msg}, ensure_ascii=False)}

        _flush_buffer()

        if not tool_call_chunks:
            content_text = "".join(content_buffer).strip()
            reasoning_text = "".join(reasoning_buffer).strip()
            if not content_text and not reasoning_text:
                return None
            return {
                "name": None,
                "arguments": None,
                "content": content_text,
                "reasoning_content": reasoning_text,
            }

        first_tc = tool_call_chunks[min(tool_call_chunks.keys())]
        name = first_tc["name"].strip()
        arguments = first_tc["arguments"].strip()

        if not name:
            content_text = "".join(content_buffer).strip()
            reasoning_text = "".join(reasoning_buffer).strip()
            return {
                "name": None,
                "arguments": None,
                "content": content_text,
                "reasoning_content": reasoning_text,
            }

        reasoning_content = "".join(reasoning_buffer)
        return {"name": name, "arguments": arguments, "reasoning_content": reasoning_content}

    def stream_complete(
        self,
        messages: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> Any:
        """
        Gemma 流式纯文本补全。
        - 内置智能缓冲机制
        - 返回完整消息对象
        """
        try:
            stream = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                extra_body=self.extra_body,
                stream=True,
            )
        except BadRequestError as e:
            error_msg = f"请求参数错误: {e}"
            if "inappropriate content" in str(e).lower() or "data inspection" in str(e).lower():
                error_msg = "内容审核未通过：输入内容可能包含不适当的内容，请修改后重试。"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg
        except AuthenticationError as e:
            error_msg = f"API认证失败: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg
        except RateLimitError as e:
            error_msg = f"API请求频率超限: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg
        except APIConnectionError as e:
            error_msg = f"API连接失败: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg
        except APIError as e:
            error_msg = f"API错误: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg
        except Exception as e:
            error_msg = f"未知错误: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg

        reasoning_buffer: list[str] = []
        content_buffer: list[str] = []

        last_callback_time = _time.time()
        callback_interval = 0.05
        min_chars_for_callback = 30

        def _flush_buffer():
            nonlocal last_callback_time
            if reasoning_buffer:
                text = "".join(reasoning_buffer)
                reasoning_buffer.clear()
                stream_callback(text, "think")
            if content_buffer:
                text = "".join(content_buffer)
                content_buffer.clear()
                stream_callback(text, "content")
            last_callback_time = _time.time()

        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    reasoning_buffer.append(reasoning)
                content = getattr(delta, 'content', None)
                if content:
                    content_buffer.append(content)

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
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            return msg

        _flush_buffer()

        from types import SimpleNamespace
        msg = SimpleNamespace()
        msg.content = "".join(content_buffer)
        msg.reasoning_content = "".join(reasoning_buffer)
        return msg