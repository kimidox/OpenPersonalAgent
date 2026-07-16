from __future__ import annotations

import base64
import json
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal, Optional

from openai import OpenAI, APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

import config
from logger import get_module_logger

logger = get_module_logger("BaseChatModel")
from executor import Executor
from base_tool import ATOMIC_TOOL_DEFINITIONS, CONTROL_TOOL_DEFINITIONS, REQUEST_TOOL_DETAILS_DEFINITION
from llm.token_usage import TokenUsage


class StreamResultType(str, Enum):
    """流式结果类型"""
    TEXT = "text"
    TOOL_CALL = "tool_call"
    ERROR = "error"
    TRUNCATED = "truncated"  # 新增：被截断的响应


@dataclass
class StreamResult:
    """统一的流式返回结构"""
    result_type: Literal["text", "tool_call", "error", "truncated"]
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[str] = None
    token_usage: Optional[TokenUsage] = None
    error_message: Optional[str] = None

    @classmethod
    def from_text(
        cls,
        content: str,
        reasoning_content: str = "",
        token_usage: Optional[TokenUsage] = None,
    ) -> "StreamResult":
        return cls(
            result_type="text",
            content=content,
            reasoning_content=reasoning_content,
            token_usage=token_usage,
        )

    @classmethod
    def from_tool_call(
        cls,
        name: str,
        arguments: str,
        reasoning_content: str = "",
        token_usage: Optional[TokenUsage] = None,
    ) -> "StreamResult":
        return cls(
            result_type="tool_call",
            tool_name=name,
            tool_arguments=arguments,
            reasoning_content=reasoning_content,
            token_usage=token_usage,
        )

    @classmethod
    def from_truncated(
        cls,
        content: str,
        reasoning_content: str = "",
        token_usage: Optional[TokenUsage] = None,
    ) -> "StreamResult":
        return cls(
            result_type="truncated",
            content=content,
            reasoning_content=reasoning_content,
            token_usage=token_usage,
        )

    @classmethod
    def from_error(cls, message: str) -> "StreamResult":
        return cls(
            result_type="error",
            error_message=message,
            content=message,
        )

    def to_legacy_dict(self) -> Optional[dict[str, str]]:
        """向后兼容：转换为旧的 dict 返回格式"""
        if self.result_type == "text":
            return {
                "name": None,
                "arguments": None,
                "content": self.content,
                "reasoning_content": self.reasoning_content or "",
                "token_usage": self.token_usage,
            }
        elif self.result_type == "tool_call":
            return {
                "name": self.tool_name,
                "arguments": self.tool_arguments,
                "reasoning_content": self.reasoning_content or "",
                "token_usage": self.token_usage,
            }
        else:  # error
            return {
                "name": "finish",
                "arguments": json.dumps({"message": self.error_message}, ensure_ascii=False),
                "token_usage": None,
            }

    def to_simple_namespace(self):
        """向后兼容：转换为 SimpleNamespace 对象"""
        from types import SimpleNamespace
        return SimpleNamespace(
            content=self.content or "",
            reasoning_content=self.reasoning_content or "",
            token_usage=self.token_usage,
        )


class StreamParser:
    """
    统一的流式响应解析器。
    
    封装流式响应的解析逻辑：
    - 缓冲区管理（reasoning, content, tool_calls）
    - 智能回调机制（50ms / 30 字符触发）
    - finish_reason 检测（stop / tool_calls / function_call / length）
    - 流迭代器耗尽兜底
    """

    def __init__(
        self,
        stream_callback: Callable[[str, str], None],
        messages: list[dict],
        estimate_tokens: Callable[[list[dict]], int],
        callback_interval: float = 0.05,
        min_chars_for_callback: int = 30,
    ) -> None:
        self._callback = stream_callback
        self._messages = messages
        self._estimate_tokens = estimate_tokens
        self._callback_interval = callback_interval
        self._min_chars = min_chars_for_callback

        # Buffers
        self._reasoning_buffer: list[str] = []
        self._content_buffer: list[str] = []
        self._tool_call_chunks: dict[int, dict[str, Any]] = {}
        self._all_reasoning_parts: list[str] = []
        self._all_content_parts: list[str] = []
        self._all_content_chars = 0
        self._token_usage: Optional[TokenUsage] = None

        # Callback timing
        self._last_callback_time = _time.time()

    def _flush_buffer(self) -> None:
        """排空缓冲区并通过回调发送"""
        if self._reasoning_buffer:
            text = "".join(self._reasoning_buffer)
            self._all_reasoning_parts.append(text)
            self._reasoning_buffer.clear()
            logger.debug("[StreamParser._flush_buffer] 调用回调: type=think, content前50字=%s", text[:50] if text else "(空)")
            self._callback(text, "think")
        if self._content_buffer:
            text = "".join(self._content_buffer)
            self._all_content_parts.append(text)
            self._content_buffer.clear()
            logger.debug("[StreamParser._flush_buffer] 调用回调: type=content, content前50字=%s", text[:50] if text else "(空)")
            self._callback(text, "content")
        self._last_callback_time = _time.time()

    def _should_flush(self) -> bool:
        """判断是否应该排空缓冲区"""
        current_time = _time.time()
        total_buffered = (
            sum(len(s) for s in self._reasoning_buffer) +
            sum(len(s) for s in self._content_buffer)
        )
        return (
            (current_time - self._last_callback_time >= self._callback_interval) or
            (total_buffered >= self._min_chars)
        )

    def _process_delta(self, delta: Any) -> None:
        """处理单个 delta 块"""
        reasoning = getattr(delta, 'reasoning_content', None)
        if reasoning:
            self._reasoning_buffer.append(reasoning)
            self._all_content_chars += len(reasoning)
        content = getattr(delta, 'content', None)
        if content:
            self._content_buffer.append(content)
            self._all_content_chars += len(content)

        if self._should_flush() and (self._reasoning_buffer or self._content_buffer):
            self._flush_buffer()

    def _process_tool_calls(self, delta: Any) -> None:
        """处理工具调用流式拼接（tool_calls 格式）"""
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in self._tool_call_chunks:
                    self._tool_call_chunks[idx] = {
                        "id": tc.id or "",
                        "name": "",
                        "arguments": "",
                    }
                if tc.function:
                    if tc.function.name:
                        self._tool_call_chunks[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        self._tool_call_chunks[idx]["arguments"] += tc.function.arguments

    def _process_function_call(self, delta: Any) -> None:
        """处理工具调用流式拼接（function_call 旧格式，GLM 使用）"""
        function_call = getattr(delta, 'function_call', None)
        if function_call:
            if 0 not in self._tool_call_chunks:
                self._tool_call_chunks[0] = {
                    "id": "",
                    "name": "",
                    "arguments": "",
                }
            if hasattr(function_call, 'name') and function_call.name:
                self._tool_call_chunks[0]["name"] += function_call.name
            if hasattr(function_call, 'arguments') and function_call.arguments:
                self._tool_call_chunks[0]["arguments"] += function_call.arguments

    def _build_result(self, finish_reason: Optional[str] = None) -> StreamResult:
        """将累积数据组装为 StreamResult"""
        self._flush_buffer()

        # 处理被截断的情况：finish_reason="length" 表示输出被 max_tokens 截断
        if finish_reason == "length":
            content_text = "".join(self._all_content_parts).strip()
            reasoning_text = "".join(self._all_reasoning_parts).strip()
            # 如果有部分工具调用内容，仍然返回 tool_call 类型让 agent 尝试执行
            if self._tool_call_chunks:
                first_tc = self._tool_call_chunks[min(self._tool_call_chunks.keys())]
                name = first_tc["name"].strip()
                arguments = first_tc["arguments"].strip()
                if name:
                    reasoning_content = "".join(self._all_reasoning_parts)
                    return StreamResult.from_tool_call(
                        name=name,
                        arguments=arguments,
                        reasoning_content=reasoning_content,
                        token_usage=self._token_usage,
                    )
            # 否则返回 truncated 类型，让 agent 给 LLM 第二轮机会
            return StreamResult.from_truncated(
                content=content_text,
                reasoning_content=reasoning_text,
                token_usage=self._token_usage,
            )

        if self._token_usage is None:
            estimated_prompt = self._estimate_tokens(self._messages)
            estimated_completion = max(1, self._all_content_chars // 4)
            self._token_usage = TokenUsage(
                prompt_tokens=estimated_prompt,
                completion_tokens=estimated_completion,
                total_tokens=estimated_prompt + estimated_completion,
            )

        if not self._tool_call_chunks:
            content_text = "".join(self._all_content_parts).strip()
            reasoning_text = "".join(self._all_reasoning_parts).strip()
            if not content_text and not reasoning_text:
                return StreamResult(
                    result_type="text",
                    content="",
                    reasoning_content="",
                    token_usage=self._token_usage,
                )
            return StreamResult.from_text(
                content=content_text,
                reasoning_content=reasoning_text,
                token_usage=self._token_usage,
            )

        first_tc = self._tool_call_chunks[min(self._tool_call_chunks.keys())]
        name = first_tc["name"].strip()
        arguments = first_tc["arguments"].strip()

        if not name:
            content_text = "".join(self._all_content_parts).strip()
            reasoning_text = "".join(self._all_reasoning_parts).strip()
            return StreamResult.from_text(
                content=content_text,
                reasoning_content=reasoning_text,
                token_usage=self._token_usage,
            )

        reasoning_content = "".join(self._all_reasoning_parts)
        return StreamResult.from_tool_call(
            name=name,
            arguments=arguments,
            reasoning_content=reasoning_content,
            token_usage=self._token_usage,
        )

    def process_stream(self, stream: Any) -> StreamResult:
        """
        遍历流迭代器并返回 StreamResult。
        
        优先使用 finish_reason 判断结束，流迭代器耗尽作为兜底。
        """
        try:
            for chunk in stream:
                # Extract token usage
                usage = getattr(chunk, 'usage', None)
                if usage:
                    self._token_usage = TokenUsage(
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                        total_tokens=getattr(usage, 'total_tokens', 0) or 0,
                    )

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                self._process_delta(delta)

                # Check finish_reason - primary end signal
                finish_reason = getattr(chunk.choices[0], 'finish_reason', None)
                if finish_reason:
                    return self._build_result(finish_reason)

                # Process tool_calls and function_call
                self._process_tool_calls(delta)
                self._process_function_call(delta)
        except Exception:
            # Flush on error, will be handled by caller
            self._flush_buffer()
            raise

        # Fallback: stream iterator exhausted without finish_reason
        return self._build_result()


class BaseChatModel(ABC):
    """
    模型无关的对话/工具调用封装。
    让 `agent.py` 不再关心：
    - OpenAI 兼容客户端如何创建
    - 工具调用字段如何解析（tool_calls / function_call）
    - 图像消息如何拼装
    - 工具调用循环如何执行
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        frequency_penalty: float = 0.6,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> None:
        self.model_name = model_name or config.MODEL_NAME
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = base_url or config.OPENAI_BASE_URL
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.extra_body = extra_body if extra_body is not None else {"enable_thinking": True}
        self._client: Optional[OpenAI] = None

    def get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @abstractmethod
    def build_tools(self) -> list[dict]:
        """返回工具 schema（用于 LLM tool/function call）。"""

    def build_skill_agent_tools(self) -> list[dict]:
        """返回 SkillAgent 专用工具 schema。"""
        tools: list[dict] = []
        for tool_def in CONTROL_TOOL_DEFINITIONS:
            tools.append({
                "type": "function",
                "function": tool_def
            })
        for tool_def in ATOMIC_TOOL_DEFINITIONS:
            tools.append({
                "type": "function",
                "function": tool_def
            })
        return tools

    def build_tool_catalog(self) -> list[dict]:
        """
        构建工具目录（简要描述）。
        
        【目录+补发 渐进披露机制 - 第一阶段】
        
        工作原理：
        1. 从 ATOMIC_TOOL_DEFINITIONS 中提取每个工具的名称和简要描述（第一行）
        2. 简要描述用于让 LLM 快速了解工具用途，无需完整参数定义
        3. 当 LLM 需要使用某个工具时，调用 request_tool_details 获取完整定义
        
        优势：
        - 减少 token 消耗：初始只提供简要描述，完整定义按需获取
        - 提高响应效率：避免一次性传递大量工具定义
        - 按需披露：LLM 只获取实际需要的工具定义
        
        返回格式示例：
        [{"name": "run_command", "brief": "执行命令行程序或脚本。"}, ...]
        """
        catalog = []
        for tool_def in ATOMIC_TOOL_DEFINITIONS:
            catalog.append({
                "name": tool_def["name"],
                "brief": tool_def["description"].split('\n')[0]
            })
        return catalog

    def build_skill_agent_tools_initial(self) -> list[dict]:
        """
        返回初始工具集（目录 + request_tool_details + CONTROL 工具）。
        
        【目录+补发 渐进披露机制 - 初始化阶段】
        
        工作原理：
        1. 只提供两类工具：
           - request_tool_details：用于按需获取原子工具的完整定义
           - CONTROL_TOOL_DEFINITIONS：控制类工具（select_skill, finish, ask_user, load_skill_memory）
        2. 原子工具（run_command, file_operation 等）不直接提供，需通过 request_tool_details 获取
        
        流程说明：
        ┌─────────────────────────────────────────────────────────────┐
        │  初始化阶段                                                    │
        │  ├─ 提供 request_tool_details（补发工具）                      │
        │  ├─ 提供 CONTROL 工具（控制流程）                              │
        │  └─ 不提供 ATOMIC 工具（按需获取）                              │
        └─────────────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────────────┐
        │  运行阶段                                                      │
        │  ├─ LLM 调用 request_tool_details 获取需要的工具定义           │
        │  ├─ 工具定义动态添加到 tools 列表                              │
        │  └─ LLM 使用获取到的工具执行任务                                │
        └─────────────────────────────────────────────────────────────┘
        
        返回格式：
        [{"type": "function", "function": REQUEST_TOOL_DETAILS_DEFINITION},
         {"type": "function", "function": select_skill 定义},
         {"type": "function", "function": finish 定义},
         ...]
        """
        tools: list[dict] = []

        tools.append({
            "type": "function",
            "function": REQUEST_TOOL_DETAILS_DEFINITION
        })

        for tool_def in CONTROL_TOOL_DEFINITIONS:
            tools.append({
                "type": "function",
                "function": tool_def
            })

        return tools

    def get_tool_full_definition(self, tool_name: str) -> Optional[dict]:
        """
        获取指定工具的完整定义。
        
        【目录+补发 渐进披露机制 - 补发阶段】
        
        工作原理：
        1. 当 LLM 调用 request_tool_details 时，此方法查找对应工具的完整定义
        2. 完整定义包含：name, description, parameters（含完整 schema）
        3. 找到的定义会被动态添加到 tools 列表，供后续调用
        
        参数：
        - tool_name: 工具名称（如 "run_command", "file_operation", "select_skill"）
        
        返回：
        - 找到：完整工具定义 dict
        - 未找到：None
        
        注意：此方法依次查找 ATOMIC_TOOL_DEFINITIONS 和 CONTROL_TOOL_DEFINITIONS。
        """
        # 先查找原子工具定义
        for tool_def in ATOMIC_TOOL_DEFINITIONS:
            if tool_def["name"] == tool_name:
                return tool_def
        # 再查找控制工具定义
        for tool_def in CONTROL_TOOL_DEFINITIONS:
            if tool_def["name"] == tool_name:
                return tool_def
        return None

    def format_tool_for_request(self, tool_def: dict) -> dict:
        """
        将工具定义格式化为请求格式。
        
        默认实现返回新格式：{"type": "function", "function": tool_def}
        子类可以重写此方法以支持不同的格式（如GLM的旧格式）。
        
        参数：
        - tool_def: 工具定义 dict（包含 name, description, parameters）
        
        返回：
        - 格式化后的工具定义
        """
        return {"type": "function", "function": tool_def}

    def get_tool_name_from_formatted(self, formatted_tool: dict) -> Optional[str]:
        """
        从格式化后的工具定义中提取工具名称。
        
        默认实现返回：formatted_tool.get("function", {}).get("name")
        子类可以重写此方法以支持不同的格式（如GLM的旧格式）。
        
        参数：
        - formatted_tool: 格式化后的工具定义
        
        返回：
        - 工具名称字符串，如果无法提取则返回 None
        """
        return formatted_tool.get("function", {}).get("name")

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def extract_function_call(self, message: Any) -> Optional[dict[str, str]]:
        """
        尝试从模型输出中提取工具调用信息。
        返回格式：{"name": ..., "arguments": "...json...", "reasoning_content": ...} 或 None
        """
        reasoning_content = getattr(message, "reasoning_content", None) or ""

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
            return {"name": str(name), "arguments": str(arguments), "reasoning_content": reasoning_content}

        legacy = getattr(message, "function_call", None)
        if legacy is not None:
            name = getattr(legacy, "name", None)
            arguments = getattr(legacy, "arguments", None) or "{}"
            if name:
                return {"name": str(name), "arguments": str(arguments), "reasoning_content": reasoning_content}

        return None

    def _estimate_tokens_from_messages(self, messages: list[dict]) -> int:
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        total_chars += len(item.get("text", ""))
        return max(1, total_chars // 4)

    @abstractmethod
    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> Any:
        """发起一次带 tools 的补全，返回 choices[0].message。"""

    def complete(self, messages: list[dict]) -> Any:
        """发起一次不带工具的纯文本补全，返回 choices[0].message。"""
        try:
            response = self.get_client().chat.completions.create(
                model=self.model_name,
                messages=messages,
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

    @abstractmethod
    def request_llm_with_tools(self, messages: list[dict], tools: list[dict]) -> Optional[dict[str, str]]:
        """请求带工具的补全，返回函数调用信息或 None。"""

    def stream_request_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> StreamResult:
        """
        流式请求带工具的补全。
        - stream_callback(content: str, type: str) 实时回调：
          - type="think": 推理内容（reasoning_content）
          - type="content": 普通文本内容
        - 返回 StreamResult，包含文本回复或工具调用信息
        """
        logger.debug("[stream_request_llm_with_tools] 方法入口: messages=%d 条, tools=%d 个, callback=%s",
                     len(messages), len(tools), "已提供" if stream_callback else "未提供")
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
                max_tokens=8192,
                stream=True,
                stream_options={"include_usage": True},
            )
        except BadRequestError as e:
            error_msg = f"请求参数错误: {e}"
            if "inappropriate content" in str(e).lower() or "data inspection" in str(e).lower():
                error_msg = "内容审核未通过：输入内容可能包含不适当的内容，请修改后重试。"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except AuthenticationError as e:
            error_msg = f"API认证失败: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except RateLimitError as e:
            error_msg = f"API请求频率超限: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except APIConnectionError as e:
            error_msg = f"API连接失败: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except APIError as e:
            error_msg = f"API错误: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except Exception as e:
            error_msg = f"未知错误: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)

        parser = StreamParser(
            stream_callback=stream_callback,
            messages=messages,
            estimate_tokens=self._estimate_tokens_from_messages,
        )

        try:
            return parser.process_stream(stream)
        except Exception as e:
            error_msg = f"流式响应处理错误: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)

    def stream_complete(
        self,
        messages: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> StreamResult:
        """
        流式纯文本补全。
        - stream_callback(content: str, type: str) 实时回调：
          - type="think": 推理内容（reasoning_content）
          - type="content": 普通文本内容
        - 返回 StreamResult，包含完整文本回复
        """
        logger.debug("[stream_complete] 方法入口: messages=%d 条, callback=%s", len(messages), "已提供" if stream_callback else "未提供")
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
            return StreamResult.from_error(error_msg)
        except AuthenticationError as e:
            error_msg = f"API认证失败: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except RateLimitError as e:
            error_msg = f"API请求频率超限: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except APIConnectionError as e:
            error_msg = f"API连接失败: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except APIError as e:
            error_msg = f"API错误: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)
        except Exception as e:
            error_msg = f"未知错误: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)

        parser = StreamParser(
            stream_callback=stream_callback,
            messages=messages,
            estimate_tokens=self._estimate_tokens_from_messages,
        )

        try:
            return parser.process_stream(stream)
        except Exception as e:
            error_msg = f"流式响应处理错误: {e}"
            stream_callback(error_msg, "content")
            return StreamResult.from_error(error_msg)

    def execute_function_call(self, fname: str, args: dict, executor: Executor) -> str:
        action = {"action": fname}
        if args:
            action.update(args)
        return executor.execute_action(action)

    def analyze_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        conversation_history: list[dict] | None = None,
        executor: Executor | None = None,
        log_callback: Optional[Callable[[str, str], Any]] = None,
    ) -> str:
        """
        负责：
        1) 拼装系统+用户(含图像) messages
        2) 循环请求模型 -> 解析 tool_call -> 执行本地动作 -> 将动作结果回填给模型
        3) 遇到 "任务完成" 时返回
        """

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for msg in conversation_history:
                messages.append(msg)

        user_content: list[dict] = []
        if user_prompt:
            user_content.append({"type": "text", "text": user_prompt})

        if image_path:
            base64_image = self.encode_image(image_path)
            user_content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
            )

        if user_content:
            messages.append({"role": "user", "content": user_content})

        tools = self.build_tools()
        current_messages = list(messages)
        executor = executor or Executor(".")

        for _ in range(getattr(config, "MAX_ITERATIONS", 20)):
            function_call = self.request_llm_with_tools(current_messages, tools)
            if not function_call:
                raise Exception("未知的响应类型（未发现 tool_calls）")

            fname = function_call.get("name")
            arg_str = function_call.get("arguments") or "{}"
            try:
                args = json.loads(arg_str)
            except Exception:
                args = {}

            if log_callback:
                log_callback(str({fname: {"args": args}}), "response")

            # 关键修复：追加 assistant(tool_calls) 消息，满足 OpenAI 协议
            # （tool 消息前必须有带 tool_calls 的 assistant 消息）
            _call_id = f"call_{id(args):x}"
            current_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": _call_id,
                    "type": "function",
                    "function": {"name": fname, "arguments": arg_str},
                }],
            })

            result = self.execute_function_call(fname, args, executor)

            if log_callback:
                log_callback(str({fname: {"result": result}}), "response")

            if result == "任务完成":
                if log_callback:
                    log_callback("任务完成", "response")
                return "任务完成"

            current_messages.append({
                "role": "tool",
                "name": fname,
                "tool_call_id": _call_id,
                "content": str(result),
            })
            current_screenshot = executor.screenshot()
            current_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{self.encode_image(current_screenshot)}"
                            },
                        }
                    ],
                }
            )

        if log_callback:
            log_callback("任务异常", "response")
        return "任务异常"