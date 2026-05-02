from __future__ import annotations

import time as _time
from typing import Any, Callable, Optional

from .BaseChatModel import BaseChatModel


class GLMChatModel(BaseChatModel):
    """
    GLM 实现：
    与当前项目的 Qwen tool schema 相同（均为 type/function 嵌套）。
    不同模型的 tool_calls 解析逻辑已统一在 BaseChatModel。
    """

    def __init__(self, model_name: str | None = None, **kwargs: Any) -> None:
        super().__init__(model_name=model_name, **kwargs)

    def request_llm_with_tools(self, messages: list[dict], tools: list[dict]) -> Optional[dict[str, str]]:
        response = self.get_client().chat.completions.create(
            model=self.model_name,
            messages=messages,
            functions=tools,
            function_call="auto",
            temperature=self.temperature,
            extra_body=self.extra_body,
        )
        msg = response.choices[0].message
        return self.extract_function_call(msg)

    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> Any:
        response = self.get_client().chat.completions.create(
            model=self.model_name,
            messages=messages,
            functions=tools,
            function_call="auto",
            temperature=self.temperature,
            extra_body=self.extra_body,
        )
        return response.choices[0].message

    def stream_request_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> Optional[dict[str, str]]:
        """
        GLM 流式请求带工具的补全。
        - 使用 functions 参数（GLM 兼容格式）
        - 内置智能缓冲：每 50ms 或累积 30 字符触发一次回调
        """
        stream = self.get_client().chat.completions.create(
            model=self.model_name,
            messages=messages,
            functions=tools,
            function_call="auto",
            temperature=self.temperature,
            extra_body=self.extra_body,
            stream=True,
        )

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
        GLM 流式纯文本补全。
        - 内置智能缓冲机制
        - 返回完整消息对象
        """
        stream = self.get_client().chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            extra_body=self.extra_body,
            stream=True,
        )

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

        _flush_buffer()

        from types import SimpleNamespace
        msg = SimpleNamespace()
        msg.content = "".join(content_buffer)
        msg.reasoning_content = "".join(reasoning_buffer)
        return msg

    def build_tools(self) -> list[dict]:
        return self.build_functions()

    def build_functions(self):
        """Register OpenAI function_call interfaces for local automation."""
        return [
            {"name": "return_to_desktop", "description": "Return to the desktop",
             "parameters": {"type": "object", "properties": {}, "required": []}},
            {
                "name": "click",
                "description": "Click at grid cell from screenshot overlay (gx, gy); cell center maps to screen pixels",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "Grid column index gx (0=left), must match screenshot grid labels",
                            "minimum": 0
                        },
                        "y": {
                            "type": "integer",
                            "description": "Grid row index gy (0=top), must match screenshot grid labels",
                            "minimum": 0
                        },
                        "button": {"type": "string"}
                    },
                    "required": ["x", "y"]
                },
            },
            {
                "name": "double_click",
                "description": "Double click at grid cell (gx, gy) from screenshot overlay",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "Grid column index gx (0=left)",
                            "minimum": 0
                        },
                        "y": {
                            "type": "integer",
                            "description": "Grid row index gy (0=top)",
                            "minimum": 0
                        },
                        "button": {"type": "string"}
                    },
                    "required": ["x", "y"]
                },
            },
            {
                "name": "right_click",
                "description": "Right click at grid cell (gx, gy) from screenshot overlay",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "Grid column index gx (0=left)",
                            "minimum": 0
                        },
                        "y": {
                            "type": "integer",
                            "description": "Grid row index gy (0=top)",
                            "minimum": 0
                        },
                    },
                    "required": ["x", "y"]
                },
            },
            {
                "name": "move_to",
                "description": "Move mouse to grid cell center (gx, gy) from screenshot overlay",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "Grid column index gx (0=left)",
                            "minimum": 0
                        },
                        "y": {
                            "type": "integer",
                            "description": "Grid row index gy (0=top)",
                            "minimum": 0
                        },
                    }, "required": ["x", "y"]},
            },
            {
                "name": "type_text",
                "description": "Type text",
                "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            },
            {
                "name": "press_key",
                "description": "Press a single key",
                "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
            },
            {
                "name": "hotkey",
                "description": "Press a combination of keys",
                "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
            },
            {
                "name": "scroll",
                "description": "Scroll; optional gx, gy to scroll at that grid cell center",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "clicks": {"type": "integer"},
                        "x": {
                            "type": "integer",
                            "description": "Optional grid column gx if scrolling at a cell",
                            "minimum": 0
                        },
                        "y": {
                            "type": "integer",
                            "description": "Optional grid row gy if scrolling at a cell",
                            "minimum": 0
                        },
                    },
                    "required": ["clicks"]
                },
            },
            {
                "name": "open_app",
                "description": "Open an application by path",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            },
            {
                "name": "wait",
                "description": "Wait for a number of seconds",
                "parameters": {"type": "object", "properties": {"seconds": {"type": "integer"}},
                               "required": ["seconds"]},
            },
            {
                "name": "screenshot",
                "description": "Take a screenshot and return the path",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "over",
                "description": "Mark the current task as successfully completed and terminate the current execution flow. This function should only be called when all objectives have been fulfilled and no further actions are required.",
                "parameters": {"type": "object", "properties": {}},
            }
        ]