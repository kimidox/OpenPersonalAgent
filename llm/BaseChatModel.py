from __future__ import annotations

import base64
import json
import re
import threading
import time as _time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import Future
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
from llm.communication_state import LLMCommunicationContext, LLMCommunicationState, transition_state, create_initial_context
from llm.async_executor import get_executor_manager, AsyncTaskResult, TaskState


def _sanitize_tool_arguments(arguments: Any) -> str:
    """确保 tool_calls 中的 arguments 是有效的 JSON 字符串。

    这是发送 API 请求前的最终防线，防止任何路径产生的非法 arguments 导致 API 报错。
    """
    if arguments is None:
        return "{}"
    if isinstance(arguments, str):
        # 验证是否为有效 JSON
        try:
            json.loads(arguments)
            return arguments
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("[API] 检测到非 JSON 的 arguments: %s，已修复为 {}", repr(arguments[:100]))
            return "{}"
    elif isinstance(arguments, dict):
        return json.dumps(arguments, ensure_ascii=False)
    else:
        logger.warning("[API] 检测到非预期的 arguments 类型: %s，已修复为 {}", type(arguments))
        return "{}"


def _sanitize_messages_for_api(messages: list[dict]) -> list[dict]:
    """在发送 API 请求前校验并修复所有 messages 中的 tool_calls。

    确保所有 assistant 消息中的 tool_calls[].function.arguments 都是有效的 JSON 字符串。
    """
    sanitized = []
    for msg in messages:
        if msg.get("role") == "assistant" and "tool_calls" in msg:
            tool_calls = msg["tool_calls"]
            if isinstance(tool_calls, list):
                sanitized_tc = []
                for tc in tool_calls:
                    if isinstance(tc, dict) and "function" in tc:
                        func = tc["function"]
                        if isinstance(func, dict) and "arguments" in func:
                            # 修复 arguments
                            func_copy = dict(func)
                            func_copy["arguments"] = _sanitize_tool_arguments(func["arguments"])
                            tc_copy = dict(tc)
                            tc_copy["function"] = func_copy
                            sanitized_tc.append(tc_copy)
                        else:
                            sanitized_tc.append(tc)
                    else:
                        sanitized_tc.append(tc)
                msg_copy = dict(msg)
                msg_copy["tool_calls"] = sanitized_tc
                sanitized.append(msg_copy)
            else:
                sanitized.append(msg)
        else:
            sanitized.append(msg)
    return sanitized


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
        """构造文本类型的流式结果。

        Args:
            content: 模型输出的文本内容。
            reasoning_content: 推理/思考过程内容，默认为空。
            token_usage: 本次请求的 token 用量统计。

        Returns:
            StreamResult: result_type 为 "text" 的实例。
        """
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
        """构造工具调用类型的流式结果。

        Args:
            name: 工具/函数名称。
            arguments: 工具调用参数的 JSON 字符串。
            reasoning_content: 推理/思考过程内容，默认为空。
            token_usage: 本次请求的 token 用量统计。

        Returns:
            StreamResult: result_type 为 "tool_call" 的实例。
        """
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
        """构造截断类型的流式结果。

        当模型输出因 max_tokens 限制被截断（finish_reason="length"）且无工具调用时使用。

        Args:
            content: 截断前的部分文本内容。
            reasoning_content: 截断前的推理/思考过程内容，默认为空。
            token_usage: 本次请求的 token 用量统计。

        Returns:
            StreamResult: result_type 为 "truncated" 的实例。
        """
        return cls(
            result_type="truncated",
            content=content,
            reasoning_content=reasoning_content,
            token_usage=token_usage,
        )

    @classmethod
    def from_error(cls, message: str) -> "StreamResult":
        """构造错误类型的流式结果。

        Args:
            message: 错误描述信息。

        Returns:
            StreamResult: result_type 为 "error" 的实例。
        """
        return cls(
            result_type="error",
            error_message=message,
            content=message,
        )

    def to_legacy_dict(self) -> Optional[dict[str, str]]:
        """向后兼容：将 StreamResult 转换为旧的 dict 返回格式。

        text 类型返回 content/arguments/name 字段，tool_call 类型返回工具信息，
        error 类型将 name 设为 "finish" 并将错误信息序列化为 arguments。

        Returns:
            包含 name、arguments、content、reasoning_content、token_usage 的字典。
        """
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
        """向后兼容：将 StreamResult 转换为 SimpleNamespace 对象。

        仅提取 content、reasoning_content 和 token_usage 字段，
        适用于不关心 tool_call 差异的旧代码路径。

        Returns:
            SimpleNamespace: 包含 content、reasoning_content、token_usage 属性的对象。
        """
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

    # 已知工具名集合，用于 XML 兜底解析时的函数名验证，防止 prose 误判
    _KNOWN_TOOL_NAMES = frozenset(
        [t["name"] for t in ATOMIC_TOOL_DEFINITIONS]
        + [t["name"] for t in CONTROL_TOOL_DEFINITIONS]
        + [REQUEST_TOOL_DETAILS_DEFINITION["name"]]
    )
    
    # 【性能优化】缓存正则表达式对象，避免重复编译
    _XML_TOOL_CALL_BLOCK_PATTERN = re.compile(
        r"<\s*tool_call\s*>(.*?)<\s*/tool_call\s*>",
        re.DOTALL | re.IGNORECASE
    )
    _XML_FUNCTION_PATTERN = re.compile(
        r"<\s*function\s*=\s*([A-Za-z_][\w]*)\s*>(.*?)<\s*/function\s*>",
        re.DOTALL | re.IGNORECASE
    )
    _XML_PARAMETER_PATTERN = re.compile(
        r"<\s*parameter\s*=\s*([A-Za-z_][\w]*)\s*>(.*?)<\s*/parameter\s*>",
        re.DOTALL | re.IGNORECASE
    )
    _JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

    @staticmethod
    def _extract_tool_call_from_text(text: str) -> Optional[tuple[str, str]]:
        """从文本中提取 Qwen3 风格的 XML 工具调用。

        用于本地后端（如 llama.cpp + thinking 模式）未把 XML 解析
        为结构化 tool_calls 字段、而是原样输出到 reasoning_content / content
        的兜底场景。

        支持两种格式：
        - 格式 A（Qwen3 原生）：<function=NAME><parameter=KEY>VALUE</parameter>...</function>
        - 格式 B（Hermes JSON）：{"name": "NAME", "arguments": {...}}

        返回 (name, arguments_json_str) 或 None。
        函数名必须在内置工具名集合中，否则返回 None（防止 prose 误判）。
        """
        if not text or "█" not in text.lower():
            return None

        # 多 block 检测
        block_count = text.lower().count("█")
        if block_count > 1:
            logger.warning(
                "[StreamParser] 检测到多个 █ 块（%d 个），仅处理第一个",
                block_count,
            )

        # 截取第一个块
        block_match = StreamParser._XML_TOOL_CALL_BLOCK_PATTERN.search(text)
        if not block_match:
            return None
        block = block_match.group(1)

        # 格式 A：Qwen3 原生
        result = StreamParser._extract_xml_tool_call(block)
        if result is not None:
            return result

        # 格式 B：Hermes / OpenAI JSON 兼容
        return StreamParser._extract_json_tool_call(block)

    @staticmethod
    def _extract_xml_tool_call(block: str) -> Optional[tuple[str, str]]:
        """从 XML 块中提取 Qwen3 原生格式的工具调用。

        Args:
            block: XML 块内的内容。

        Returns:
            (name, arguments_json_str) 或 None。
        """
        func_match = StreamParser._XML_FUNCTION_PATTERN.search(block)
        if not func_match:
            return None

        name = func_match.group(1)
        params_text = func_match.group(2)
        params: dict[str, Any] = {}
        for key, value in StreamParser._XML_PARAMETER_PATTERN.findall(params_text):
            value = value.strip()
            if value[:1] in "[{":
                try:
                    params[key] = json.loads(value)
                except json.JSONDecodeError:
                    params[key] = value
            else:
                params[key] = value
        if name not in StreamParser._KNOWN_TOOL_NAMES:
            logger.warning(
                "[StreamParser] XML 解析到未知工具名 %r，忽略（可能是 prose 误判）",
                name,
            )
            return None
        return name, json.dumps(params, ensure_ascii=False)

    @staticmethod
    def _extract_json_tool_call(block: str) -> Optional[tuple[str, str]]:
        """从 XML 块中提取 Hermes JSON 格式的工具调用。

        Args:
            block: XML 块内的内容。

        Returns:
            (name, arguments_json_str) 或 None。
        """
        json_match = StreamParser._JSON_OBJECT_PATTERN.search(block)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group(0))
            name = data.get("name")
            if not name:
                return None
            args = data.get("arguments", {})
            if isinstance(args, dict):
                args_str = json.dumps(args, ensure_ascii=False)
            elif isinstance(args, str):
                try:
                    parsed = json.loads(args)
                    if isinstance(parsed, dict):
                        args_str = json.dumps(parsed, ensure_ascii=False)
                    else:
                        args_str = "{}"
                except json.JSONDecodeError:
                    args_str = "{}"
            else:
                args_str = json.dumps(args, ensure_ascii=False) if args else "{}"
            if name not in StreamParser._KNOWN_TOOL_NAMES:
                logger.warning(
                    "[StreamParser] JSON 解析到未知工具名 %r，忽略（可能是 prose 误判）",
                    name,
                )
                return None
            return str(name), args_str
        except json.JSONDecodeError:
            return None


        # 多 block 检测：Qwen3 一般单轮只调一个工具，多个时只取第一个但记录 warning
        block_count = text.lower().count("<tool_call>")
        if block_count > 1:
            logger.warning(
                "[StreamParser] 检测到多个 <tool_call> 块（%d 个），仅处理第一个",
                block_count,
            )

        # 截取第一个 <tool_call>... 演艺经历 块（使用缓存的正则）
        block_match = StreamParser._XML_TOOL_CALL_BLOCK_PATTERN.search(text)
        if not block_match:
            return None
        block = block_match.group(1)

        # 格式 A：Qwen3 原生 <function=NAME>...<parameter=KEY>VALUE</parameter>...</function>（使用缓存的正则）
        func_match = StreamParser._XML_FUNCTION_PATTERN.search(block)
        if func_match:
            name = func_match.group(1)
            params_text = func_match.group(2)
            params: dict[str, Any] = {}
            for key, value in StreamParser._XML_PARAMETER_PATTERN.findall(params_text):
                value = value.strip()
                # 仅对明确是 JSON 复合类型（array/object）的值做解析，
                # 纯数字/布尔/字符串保持原样——避免 skill_id="8" 被误转为 int 8
                # 导致与云端结构化 tool_calls 行为不一致（云端始终返回字符串）。
                if value[:1] in "[{":
                    try:
                        params[key] = json.loads(value)
                    except json.JSONDecodeError:
                        params[key] = value
                else:
                    params[key] = value
            # 函数名验证：必须在已知工具名集合中
            if name not in StreamParser._KNOWN_TOOL_NAMES:
                logger.warning(
                    "[StreamParser] XML 解析到未知工具名 %r，忽略（可能是 prose 误判）",
                    name,
                )
                return None
            return name, json.dumps(params, ensure_ascii=False)

        # 格式 B：Hermes / OpenAI JSON 兼容（使用缓存的正则）
        json_match = StreamParser._JSON_OBJECT_PATTERN.search(block)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                name = data.get("name")
                if not name:
                    return None
                args = data.get("arguments", {})
                if isinstance(args, dict):
                    args_str = json.dumps(args, ensure_ascii=False)
                elif isinstance(args, str):
                    # 验证字符串是否为有效 JSON，如果不是则尝试解析
                    try:
                        parsed = json.loads(args)
                        if isinstance(parsed, dict):
                            args_str = json.dumps(parsed, ensure_ascii=False)
                        else:
                            # 如果不是 dict，包装成空对象
                            args_str = "{}"
                    except json.JSONDecodeError:
                        # 无法解析为 JSON，返回空对象
                        args_str = "{}"
                else:
                    args_str = json.dumps(args, ensure_ascii=False) if args else "{}"
                if name not in StreamParser._KNOWN_TOOL_NAMES:
                    logger.warning(
                        "[StreamParser] JSON 解析到未知工具名 %r，忽略（可能是 prose 误判）",
                        name,
                    )
                    return None
                return str(name), args_str
            except json.JSONDecodeError:
                pass

        return None

    def __init__(
        self,
        stream_callback: Callable[[str, str], None],
        messages: list[dict],
        estimate_tokens: Callable[[list[dict]], int],
        callback_interval: float = 0.1,  # 优化：从50ms增加到100ms，降低回调频率
        min_chars_for_callback: int = 50,  # 优化：从30增加到50，减少小批量回调
        on_tool_call_chunk: Callable[[dict], None] | None = None,
    ) -> None:
        """初始化流式解析器，配置回调策略、缓冲区和性能监控。

        Args:
            stream_callback: 流式回调函数 (content, msg_type)，用于向调用方发送增量数据。
            messages: 当前消息列表，用于 token 估算。
            estimate_tokens: token 估算函数，接收消息列表返回估算值。
            callback_interval: 回调最小间隔（秒），默认 0.1s，控制回调频率。
            min_chars_for_callback: 触发回调的最小缓冲字符数，默认 50。
            on_tool_call_chunk: 工具调用块回调，接收增量 tool_call chunk 字典。
        """
        self._callback = stream_callback
        self._messages = messages
        self._estimate_tokens = estimate_tokens
        self._callback_interval = callback_interval
        self._min_chars = min_chars_for_callback
        self._on_tool_call_chunk = on_tool_call_chunk

        # Buffers（性能优化：预分配缓冲区大小）
        self._reasoning_buffer: list[str] = []
        self._content_buffer: list[str] = []
        self._tool_call_chunks: dict[int, dict[str, Any]] = {}
        self._all_reasoning_parts: list[str] = []
        self._all_content_parts: list[str] = []
        self._all_content_chars = 0
        self._token_usage: Optional[TokenUsage] = None

        # Callback timing
        self._last_callback_time = _time.time()
        
        # 【性能优化】性能监控指标
        self._performance_metrics = {
            'callback_count': 0,  # 回调次数
            'total_callback_delay_ms': 0.0,  # 总回调延迟（毫秒）
            'max_callback_delay_ms': 0.0,  # 最大回调延迟
            'buffer_flush_count': 0,  # 缓冲区刷新次数
            'total_buffered_chars': 0,  # 总缓冲字符数
            'avg_buffered_chars': 0.0,  # 平均缓冲字符数
        }

    def _flush_buffer(self) -> None:
        """排空缓冲区并通过回调发送
        
        性能优化：
        1. 移除高频DEBUG日志，降低I/O开销
        2. 添加性能监控，记录回调延迟和缓冲区使用情况
        """
        flush_start_time = _time.time()
        total_chars_flushed = 0
        
        if self._reasoning_buffer:
            # 【性能优化】使用 join 代替循环拼接，减少字符串拷贝
            text = "".join(self._reasoning_buffer)
            total_chars_flushed += len(text)
            self._all_reasoning_parts.append(text)
            self._reasoning_buffer.clear()
            self._callback(text, "think")
        if self._content_buffer:
            # 【性能优化】使用 join 代替循环拼接，减少字符串拷贝
            text = "".join(self._content_buffer)
            total_chars_flushed += len(text)
            self._all_content_parts.append(text)
            self._content_buffer.clear()
            self._callback(text, "content")
        
        # 更新性能监控指标
        callback_delay_ms = (_time.time() - flush_start_time) * 1000
        self._performance_metrics['callback_count'] += 1
        self._performance_metrics['total_callback_delay_ms'] += callback_delay_ms
        self._performance_metrics['max_callback_delay_ms'] = max(
            self._performance_metrics['max_callback_delay_ms'], 
            callback_delay_ms
        )
        self._performance_metrics['buffer_flush_count'] += 1
        self._performance_metrics['total_buffered_chars'] += total_chars_flushed
        
        # 计算平均缓冲字符数
        if self._performance_metrics['buffer_flush_count'] > 0:
            self._performance_metrics['avg_buffered_chars'] = (
                self._performance_metrics['total_buffered_chars'] / 
                self._performance_metrics['buffer_flush_count']
            )
        
        self._last_callback_time = _time.time()

    def get_performance_metrics(self) -> dict:
        """获取性能监控指标
        
        Returns:
            dict: 包含性能指标的字典，包括：
                - callback_count: 回调次数
                - avg_callback_delay_ms: 平均回调延迟（毫秒）
                - max_callback_delay_ms: 最大回调延迟（毫秒）
                - buffer_flush_count: 缓冲区刷新次数
                - avg_buffered_chars: 平均缓冲字符数
                - total_buffered_chars: 总缓冲字符数
        """
        metrics = dict(self._performance_metrics)
        # 计算平均回调延迟
        if metrics['callback_count'] > 0:
            metrics['avg_callback_delay_ms'] = (
                metrics['total_callback_delay_ms'] / metrics['callback_count']
            )
        else:
            metrics['avg_callback_delay_ms'] = 0.0
        return metrics
    
    def log_performance_summary(self) -> None:
        """记录性能摘要日志（在流式处理结束时调用）"""
        metrics = self.get_performance_metrics()
        
        # 使用字符串格式化而不是参数传递，兼容项目的自定义logger
        summary_msg = (
            f"[StreamParser 性能摘要] "
            f"回调次数: {metrics['callback_count']}, "
            f"平均回调延迟: {metrics['avg_callback_delay_ms']:.2f}ms, "
            f"最大回调延迟: {metrics['max_callback_delay_ms']:.2f}ms, "
            f"缓冲区刷新次数: {metrics['buffer_flush_count']}, "
            f"平均缓冲字符数: {metrics['avg_buffered_chars']:.1f}, "
            f"总缓冲字符数: {metrics['total_buffered_chars']}"
        )
        logger.info(summary_msg)
        
        # 性能告警：如果平均回调延迟超过阈值，记录警告
        PERFORMANCE_WARNING_THRESHOLD_MS = 10.0  # 平均回调延迟警告阈值（毫秒）
        if metrics['avg_callback_delay_ms'] > PERFORMANCE_WARNING_THRESHOLD_MS:
            warning_msg = (
                f"[StreamParser 性能告警] "
                f"平均回调延迟 {metrics['avg_callback_delay_ms']:.2f}ms 超过阈值 {PERFORMANCE_WARNING_THRESHOLD_MS:.2f}ms，"
                f"可能影响流式响应性能。建议增大回调间隔或字符阈值。"
            )
            logger.warning(warning_msg)

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

    def _emit_tool_call_chunk(
        self,
        tool_call_index: int,
        name_chunk: str,
        arguments_chunk: str,
        accumulated_name: str,
        accumulated_arguments: str,
        is_complete: bool = False,
        source: str = "streaming",
    ) -> None:
        """发出工具调用增量回调

        Args:
            tool_call_index: 工具调用索引
            name_chunk: 工具名称增量片段
            arguments_chunk: 参数增量片段
            accumulated_name: 已累积的工具名称
            accumulated_arguments: 已累积的参数
            is_complete: 是否已完成（流结束）
            source: 来源类型（"streaming" 结构化流式 / "xml_fallback" XML一次性）
        """
        if self._on_tool_call_chunk:
            chunk_data = {
                "name_chunk": name_chunk,
                "arguments_chunk": arguments_chunk,
                "accumulated_name": accumulated_name,
                "accumulated_arguments": accumulated_arguments,
                "tool_call_index": tool_call_index,
                "is_complete": is_complete,
                "source": source,
            }
            self._on_tool_call_chunk(chunk_data)

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
                    name_chunk = ""
                    arguments_chunk = ""
                    if tc.function.name:
                        name_chunk = tc.function.name
                        self._tool_call_chunks[idx]["name"] += name_chunk
                    if tc.function.arguments:
                        arguments_chunk = tc.function.arguments
                        self._tool_call_chunks[idx]["arguments"] += arguments_chunk
                    
                    # 在累积数据后调用回调
                    if name_chunk or arguments_chunk:
                        self._emit_tool_call_chunk(
                            tool_call_index=idx,
                            name_chunk=name_chunk,
                            arguments_chunk=arguments_chunk,
                            accumulated_name=self._tool_call_chunks[idx]["name"],
                            accumulated_arguments=self._tool_call_chunks[idx]["arguments"],
                            is_complete=False,
                        )

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
            name_chunk = ""
            arguments_chunk = ""
            if hasattr(function_call, 'name') and function_call.name:
                name_chunk = function_call.name
                self._tool_call_chunks[0]["name"] += name_chunk
            if hasattr(function_call, 'arguments') and function_call.arguments:
                arguments_chunk = function_call.arguments
                self._tool_call_chunks[0]["arguments"] += arguments_chunk
            
            # 在累积数据后调用回调
            if name_chunk or arguments_chunk:
                self._emit_tool_call_chunk(
                    tool_call_index=0,
                    name_chunk=name_chunk,
                    arguments_chunk=arguments_chunk,
                    accumulated_name=self._tool_call_chunks[0]["name"],
                    accumulated_arguments=self._tool_call_chunks[0]["arguments"],
                    is_complete=False,
                )

    def _build_result_truncated(self) -> StreamResult:
        """处理被截断的响应：finish_reason="length" 时优先返回工具调用，否则返回 truncated。

        AI-BRANCH-MARKER: 截断场景分支
        - 存在原因: max_tokens 截断可能导致工具调用不完整
        - 适用条件: finish_reason == "length"
        - 不能合并原因: 截断处理与正常完成逻辑差异显著
        """
        content_text = "".join(self._all_content_parts).strip()
        reasoning_text = "".join(self._all_reasoning_parts).strip()
        if self._tool_call_chunks:
            for idx, tc_data in self._tool_call_chunks.items():
                self._emit_tool_call_chunk(
                    tool_call_index=idx,
                    name_chunk="",
                    arguments_chunk="",
                    accumulated_name=tc_data["name"],
                    accumulated_arguments=tc_data["arguments"],
                    is_complete=True,
                )
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
        return StreamResult.from_truncated(
            content=content_text,
            reasoning_content=reasoning_text,
            token_usage=self._token_usage,
        )

    def _build_result_no_tool_calls(self) -> StreamResult:
        """处理无工具调用的纯文本响应，含 XML 兜底解析。

        AI-BRANCH-MARKER: XML 兜底解析分支
        - 存在原因: llama.cpp + thinking 模式可能输出 XML 工具调用到 reasoning_content
        - 适用条件: 本地后端未返回结构化 tool_calls 字段
        - 不能合并原因: 需要从非结构化文本中解析，与正常结构化路径不同
        """
        content_text = "".join(self._all_content_parts).strip()
        reasoning_text = "".join(self._all_reasoning_parts).strip()

        # XML 兜底解析：本地后端可能把 XML 工具调用输出到 reasoning_content
        # 而非结构化 tool_calls 字段，这里从文本中提取并转交 agent 执行。
        parsed = self._extract_tool_call_from_text(reasoning_text) \
            or self._extract_tool_call_from_text(content_text)
        if parsed:
            name, arguments = parsed
            logger.warning(
                "[StreamParser] 从 reasoning/content 中解析到 XML 工具调用 "
                "(本地后端未返回结构化 tool_calls): name=%s", name,
            )
            if self._on_tool_call_chunk:
                self._emit_tool_call_chunk(
                    tool_call_index=0,
                    name_chunk="",
                    arguments_chunk="",
                    accumulated_name=name,
                    accumulated_arguments=arguments,
                    is_complete=True,
                    source="xml_fallback",
                )
            return StreamResult.from_tool_call(
                name=name,
                arguments=arguments,
                reasoning_content=reasoning_text,
                token_usage=self._token_usage,
            )

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

    def _build_result(self, finish_reason: Optional[str] = None) -> StreamResult:
        """将累积数据组装为 StreamResult。

        拆分为 _build_result_truncated / _build_result_no_tool_calls 子方法，
        降低单个方法复杂度。
        """
        self._flush_buffer()

        if finish_reason == "length":
            return self._build_result_truncated()

        if self._token_usage is None:
            estimated_prompt = self._estimate_tokens(self._messages)
            estimated_completion = max(1, self._all_content_chars // 4)
            self._token_usage = TokenUsage(
                prompt_tokens=estimated_prompt,
                completion_tokens=estimated_completion,
                total_tokens=estimated_prompt + estimated_completion,
            )

        if not self._tool_call_chunks:
            return self._build_result_no_tool_calls()

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

        for idx, tc_data in self._tool_call_chunks.items():
            self._emit_tool_call_chunk(
                tool_call_index=idx,
                name_chunk="",
                arguments_chunk="",
                accumulated_name=tc_data["name"],
                accumulated_arguments=tc_data["arguments"],
                is_complete=True,
            )

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
                    # 【性能优化】记录性能摘要日志
                    self.log_performance_summary()
                    return self._build_result(finish_reason)

                # Process tool_calls and function_call
                self._process_tool_calls(delta)
                self._process_function_call(delta)
        except Exception:
            # Flush on error, will be handled by caller
            self._flush_buffer()
            # 【性能优化】即使异常也记录性能摘要
            self.log_performance_summary()
            raise

        # Fallback: stream iterator exhausted without finish_reason
        # 【性能优化】记录性能摘要日志
        self.log_performance_summary()
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

    # 超时阈值（秒）
    WAITING_FOR_RESPONSE_TIMEOUT = 30  # 等待响应超时30秒
    RECEIVING_STREAM_STALL_TIMEOUT = 60  # 流数据停滞超时60秒

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.95,
        frequency_penalty: float = 0.6,
        extra_body: Optional[dict[str, Any]] = None,
        enable_vision: bool = True,
        enable_deep_thinking: bool = True,
        enable_tool_call: bool = True,
    ) -> None:
        """初始化聊天模型，配置 API 参数、通信状态追踪和超时检测。

        extra_body 默认同时包含 DashScope 和 llama.cpp 两个后端的兼容字段，
        使 enable_thinking 在云端和本地都能生效。

        Args:
            model_name: 模型名称，默认使用 config.MODEL_NAME。
            api_key: OpenAI API 密钥，默认使用 config.OPENAI_API_KEY。
            base_url: API 基础 URL，默认使用 config.OPENAI_BASE_URL。
            temperature: 生成温度，默认 0.7。
            top_p: 核采样参数，默认 0.95。
            frequency_penalty: 频率惩罚，默认 0.6。
            extra_body: 额外请求体字段，默认包含 enable_thinking 双端兼容字段。
            enable_vision: 是否启用视觉/图片能力，默认 True。
            enable_deep_thinking: 是否启用深度思考，默认 True。
            enable_tool_call: 是否启用工具调用，默认 True。
        """
        self.model_name = model_name or config.MODEL_NAME
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = base_url or config.OPENAI_BASE_URL
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.enable_vision = enable_vision
        self.enable_deep_thinking = enable_deep_thinking
        self.enable_tool_call = enable_tool_call
        # 默认 extra_body 同时包含 DashScope 和 llama.cpp 两个后端的兼容字段，
        # 让 enable_thinking 的意图在云端和本地都能生效（见 llm/__init__.py 的 get_chat_model）。
        self.extra_body = extra_body if extra_body is not None else {
            "enable_thinking": enable_deep_thinking,
            "chat_template_kwargs": {"enable_thinking": enable_deep_thinking},
        }
        self._client: Optional[OpenAI] = None

        # LLM通信状态追踪
        self._llm_communication_context: LLMCommunicationContext = create_initial_context(
            model_name=self.model_name
        )
        self._state_update_callback: Optional[Callable[[dict], None]] = None

        # 超时检测定时器
        self._timeout_timer: Optional[threading.Timer] = None
        self._timeout_timer_lock: threading.Lock = threading.Lock()

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
                # 通过 EventBus 发布 LLM 状态告警事件，避免 llm→ui_flet 反向依赖
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
           - CONTROL_TOOL_DEFINITIONS：控制类工具（select_skill, finish, ask_user）
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
        """将图片文件编码为 base64 字符串。

        Args:
            image_path: 图片文件的绝对路径。

        Returns:
            str: 图片的 base64 编码字符串。
        """
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
        """通过字符数估算消息的 token 数量，用于流式回调策略。

        采用简单的 4 字符 ≈ 1 token 估算，支持纯文本和多模态消息格式。

        Args:
            messages: OpenAI 格式的消息列表。

        Returns:
            估算的 token 数量，最小值为 1。
        """
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
        # 最终防线：校验并修复所有 messages 中的 tool_calls
        messages = _sanitize_messages_for_api(messages)
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

        stream_callback(error_msg, "content")
        self._transition_communication_state(
            LLMCommunicationState.COMMUNICATION_ENDED,
            error_message=error_msg
        )
        self._transition_communication_state(LLMCommunicationState.IDLE)
        return StreamResult.from_error(error_msg)

    def stream_request_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        stream_callback: Callable[[str, str], None],
    ) -> StreamResult:
        """
        流式请求带工具的补全（同步方法，向后兼容）。
        - stream_callback(content: str, type: str) 实时回调：
          - type="think": 推理内容（reasoning_content）
          - type="content": 普通文本内容
          - type="tool_call": 工具调用信息
        - 返回 StreamResult，包含文本回复或工具调用信息

        性能优化：移除高频DEBUG日志，降低I/O开销

        注意：此方法会阻塞主线程，推荐使用异步版本 async_stream_request_llm_with_tools
        """
        # 移除高频DEBUG日志：方法入口

        # 创建初始通信上下文
        self._transition_communication_state(LLMCommunicationState.IDLE)

        # 最终防线：校验并修复所有 messages 中的 tool_calls
        messages = _sanitize_messages_for_api(messages)

        try:
            # 转换状态为 SENDING_REQUEST，记录开始时间
            self._transition_communication_state(
                LLMCommunicationState.SENDING_REQUEST,
                start_timestamp=_time.time()
            )

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

            # 请求已发送，启动等待响应超时检测
            self._start_timeout_timer(self.WAITING_FOR_RESPONSE_TIMEOUT, "waiting_for_response")
        except (BadRequestError, AuthenticationError, RateLimitError, APIConnectionError, APIError) as e:
            return self._handle_api_error(e, stream_callback)
        except Exception as e:
            return self._handle_api_error(e, stream_callback)

        # 创建带状态转换的流式回调包装函数
        wrapped_stream_callback = self._create_streaming_wrapped_callback(stream_callback)

        # 工具调用流式回调：将工具调用增量数据通过 stream_callback 发送
        def on_tool_call_chunk_wrapper(chunk_data: dict) -> None:
            """处理工具调用增量数据的回调函数

            Args:
                chunk_data: 包含工具调用增量信息的字典，包含：
                    - name_chunk: 工具名称增量片段
                    - arguments_chunk: 参数增量片段
                    - accumulated_name: 已累积的工具名称
                    - accumulated_arguments: 已累积的参数
                    - tool_call_index: 工具调用索引
                    - is_complete: 是否已完成（流结束）
            """
            # 只在完成时发送完整信息，避免流式过程中频繁发送
            if chunk_data.get("is_complete"):
                name = chunk_data.get("accumulated_name", "")
                arguments = chunk_data.get("accumulated_arguments", "")
                if name:
                    # 格式：调用工具 `{name}` · {arguments}
                    stream_callback(f"调用工具 `{name}` · {arguments}", "tool_call")

        parser = StreamParser(
            stream_callback=wrapped_stream_callback,
            messages=messages,
            estimate_tokens=self._estimate_tokens_from_messages,
            on_tool_call_chunk=on_tool_call_chunk_wrapper,  # 新增：传递工具调用流式回调
        )

        return self._process_stream_result(parser, stream, stream_callback)

    def async_stream_request_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        stream_callback: Callable[[str, str], None],
        *,
        task_id: Optional[str] = None,
        timeout: Optional[float] = None,
        on_complete: Optional[Callable[[AsyncTaskResult], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> tuple[str, Future]:
        """
        异步流式请求带工具的补全（非阻塞主线程）。

        使用 ThreadPoolExecutor 在后台线程执行 LLM 调用，避免阻塞主线程，
        实现并发处理能力。适用于需要同时处理多个 LLM 请求的场景。

        Args:
            messages: 消息列表
            tools: 工具定义列表
            stream_callback: 流式回调函数，格式：callback(content: str, type: str)
            task_id: 任务唯一标识符（可选，默认自动生成）
            timeout: 任务超时时间（秒），None 表示不限制
            on_complete: 任务完成回调（成功）
            on_error: 任务错误回调（失败）

        Returns:
            tuple[str, Future]: (任务ID, Future对象)
                - 任务ID：用于后续查询、取消任务
                - Future对象：用于跟踪任务状态

        使用示例：
        ```python
        # 提交异步任务
        task_id, future = model.async_stream_request_llm_with_tools(
            messages, tools, callback
        )

        # 等待结果（非阻塞，可以在等待期间处理其他任务）
        try:
            result = model.wait_for_async_task(task_id, timeout=30.0)
            print(f"任务完成: {result}")
        except TimeoutError:
            print(f"任务超时")
            model.cancel_async_task(task_id)
        ```

        注意事项：
        1. stream_callback 会在后台线程中调用，请确保回调函数是线程安全的
        2. 任务完成后建议调用 cleanup_async_task 清理资源
        3. 可以使用 wait_for_async_task 等待任务结果
        4. 可以使用 cancel_async_task 取消正在执行的任务
        """
        # 生成任务 ID
        if task_id is None:
            task_id = f"llm_async_{uuid.uuid4().hex[:12]}"

        # 获取线程池管理器
        executor = get_executor_manager()

        # 提交异步任务
        future = executor.submit(
            task_id=task_id,
            func=self.stream_request_llm_with_tools,
            messages=messages,
            tools=tools,
            stream_callback=stream_callback,
            timeout=timeout,
            on_complete=on_complete,
            on_error=on_error,
        )

        logger.debug(f"[AsyncLLM] 异步任务已提交: task_id={task_id}")

        return task_id, future

    def wait_for_async_task(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> StreamResult:
        """
        等待异步任务完成并获取结果（阻塞当前线程，但不阻塞主线程）。

        Args:
            task_id: 任务 ID
            timeout: 等待超时时间（秒），None 表示不限制

        Returns:
            StreamResult: 任务执行结果

        Raises:
            TimeoutError: 任务超时
            KeyError: 任务不存在
            Exception: 任务执行失败的错误
        """
        executor = get_executor_manager()
        task_result = executor.get_result(task_id, timeout=timeout)

        if task_result.is_success:
            return task_result.result
        else:
            if task_result.error:
                raise task_result.error
            else:
                raise RuntimeError(f"任务执行失败: {task_id}")

    def cancel_async_task(self, task_id: str) -> bool:
        """
        取消异步任务。

        Args:
            task_id: 任务 ID

        Returns:
            bool: 是否成功取消
        """
        executor = get_executor_manager()
        return executor.cancel(task_id)

    def get_async_task_state(self, task_id: str) -> Optional[TaskState]:
        """
        获取异步任务状态。

        Args:
            task_id: 任务 ID

        Returns:
            TaskState: 任务状态，如果任务不存在则返回 None
        """
        executor = get_executor_manager()
        return executor.get_task_state(task_id)

    def is_async_task_running(self, task_id: str) -> bool:
        """
        检查异步任务是否正在运行。

        Args:
            task_id: 任务 ID

        Returns:
            bool: 任务是否正在运行
        """
        executor = get_executor_manager()
        return executor.is_task_running(task_id)

    def get_async_task_stats(self) -> dict:
        """
        获取线程池统计信息。

        Returns:
            dict: 统计信息字典，包含：
                - total_tasks: 总任务数
                - active_tasks: 活跃任务数
                - max_workers: 最大线程数
        """
        executor = get_executor_manager()
        return executor.get_stats()

    def cleanup_async_tasks(self, max_age_seconds: float = 3600) -> int:
        """
        清理已完成的旧异步任务（释放内存）。

        Args:
            max_age_seconds: 最大保留时间（秒），默认 1 小时

        Returns:
            int: 清理的任务数量
        """
        executor = get_executor_manager()
        return executor.cleanup_finished_tasks(max_age_seconds)

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
        
        性能优化：移除高频DEBUG日志，降低I/O开销
        """
        # 移除高频DEBUG日志：方法入口

        # 创建初始通信上下文
        self._transition_communication_state(LLMCommunicationState.IDLE)

        # 最终防线：校验并修复所有 messages 中的 tool_calls
        messages = _sanitize_messages_for_api(messages)

        try:
            # 转换状态为 SENDING_REQUEST，记录开始时间
            self._transition_communication_state(
                LLMCommunicationState.SENDING_REQUEST,
                start_timestamp=_time.time()
            )

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

            # 请求已发送，启动等待响应超时检测
            self._start_timeout_timer(self.WAITING_FOR_RESPONSE_TIMEOUT, "waiting_for_response")
        except (BadRequestError, AuthenticationError, RateLimitError, APIConnectionError, APIError) as e:
            return self._handle_api_error(e, stream_callback)
        except Exception as e:
            return self._handle_api_error(e, stream_callback)

        # 创建带状态转换的流式回调包装函数
        wrapped_stream_callback = self._create_streaming_wrapped_callback(stream_callback)

        parser = StreamParser(
            stream_callback=wrapped_stream_callback,
            messages=messages,
            estimate_tokens=self._estimate_tokens_from_messages,
        )

        return self._process_stream_result(parser, stream, stream_callback)

    def _create_streaming_wrapped_callback(
        self,
        stream_callback: Callable[[str, str], None],
    ) -> Callable[[str, str], None]:
        """创建带状态转换的流式回调包装函数。

        在首次收到数据时将状态转换为 RECEIVING_STREAM，
        并在每次收到数据时更新 last_data_timestamp。

        Args:
            stream_callback: 原始流式回调函数。

        Returns:
            包装后的流式回调函数。
        """
        first_chunk_received = [False]

        def wrapped_stream_callback(content: str, msg_type: str) -> None:
            # 首次收到数据时转换状态为 RECEIVING_STREAM
            if not first_chunk_received[0]:
                first_chunk_received[0] = True
                self._transition_communication_state(
                    LLMCommunicationState.RECEIVING_STREAM
                )
            # 每次收到数据时更新 last_data_timestamp
            self._transition_communication_state(
                LLMCommunicationState.RECEIVING_STREAM,
                last_data_timestamp=_time.time()
            )
            stream_callback(content, msg_type)

        return wrapped_stream_callback

    def _process_stream_result(
        self,
        parser: StreamParser,
        stream,
        stream_callback: Callable[[str, str], None],
    ) -> StreamResult:
        """处理流式响应结果，包含状态转换和异常处理。

        Args:
            parser: StreamParser 实例。
            stream: 流式响应对象。
            stream_callback: 流式回调函数，用于发送错误信息。

        Returns:
            StreamResult: 流式响应处理结果。
        """
        try:
            result = parser.process_stream(stream)
            # 流正常结束，转换状态为 COMMUNICATION_ENDED
            self._transition_communication_state(LLMCommunicationState.COMMUNICATION_ENDED)
            return result
        except Exception as e:
            error_msg = f"流式响应处理错误: {e}"
            stream_callback(error_msg, "content")
            # 异常时转换状态为 COMMUNICATION_ENDED
            self._transition_communication_state(
                LLMCommunicationState.COMMUNICATION_ENDED,
                error_message=error_msg
            )
            return StreamResult.from_error(error_msg)
        finally:
            # 方法返回前重置状态为 IDLE
            self._transition_communication_state(LLMCommunicationState.IDLE)

    def execute_function_call(self, fname: str, args: dict, executor: Executor) -> str:
        """执行指定的工具调用并返回结果字符串。

        Args:
            fname: 工具/函数名称。
            args: 工具调用参数字典。
            executor: Executor 实例，用于执行本地动作。

        Returns:
            str: 工具执行的返回结果。
        """
        action = {"action": fname}
        if args:
            action.update(args)
        return executor.execute_action(action)

    def _build_image_analysis_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None,
        conversation_history: list[dict] | None,
    ) -> list[dict]:
        """构建图像分析的消息列表。

        拼装系统提示、对话历史和用户消息（含图像）为完整的消息列表。

        Args:
            system_prompt: 系统提示文本。
            user_prompt: 用户提示文本。
            image_path: 图像文件路径，可为 None。
            conversation_history: 对话历史消息列表，可为 None。

        Returns:
            list[dict]: 构建好的消息列表。
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

        return messages

    def _process_tool_call_iteration(
        self,
        current_messages: list[dict],
        tools: list[dict],
        executor: Executor,
        log_callback: Optional[Callable[[str, str], Any]] = None,
    ) -> tuple[list[dict], bool, str]:
        """处理单次工具调用迭代。

        执行一次工具调用：请求模型、解析 tool_call、执行本地动作、
        将动作结果回填给模型。

        Args:
            current_messages: 当前消息列表。
            tools: 工具定义列表。
            executor: Executor 实例，用于执行本地动作。
            log_callback: 日志回调函数，可为 None。

        Returns:
            tuple[list[dict], bool, str]: (更新后的消息列表, 是否应提前返回, 返回值)。
                当 should_return 为 True 时，return_value 为最终结果；
                当 should_return 为 False 时，return_value 无意义，继续迭代。
        """
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
        # 确保 arg_str 是有效的 JSON 字符串
        try:
            json.loads(arg_str)
            valid_arg_str = arg_str
        except (json.JSONDecodeError, TypeError):
            valid_arg_str = "{}"
        current_messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": _call_id,
                "type": "function",
                "function": {"name": fname, "arguments": valid_arg_str},
            }],
        })

        result = self.execute_function_call(fname, args, executor)

        if log_callback:
            log_callback(str({fname: {"result": result}}), "response")

        if result == "任务完成":
            if log_callback:
                log_callback("任务完成", "response")
            return current_messages, True, "任务完成"

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

        return current_messages, False, ""

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

        messages = self._build_image_analysis_messages(
            system_prompt, user_prompt, image_path, conversation_history
        )

        tools = self.build_tools()
        current_messages = list(messages)
        executor = executor or Executor(".")

        for _ in range(getattr(config, "MAX_ITERATIONS", 20)):
            current_messages, should_return, return_value = self._process_tool_call_iteration(
                current_messages, tools, executor, log_callback
            )
            if should_return:
                return return_value

        if log_callback:
            log_callback("任务异常", "response")
        return "任务异常"