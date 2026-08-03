"""流式响应解析模块。

从 BaseChatModel.py 中提取的流式响应解析相关类和函数，包括：
- StreamResultType: 流式结果类型枚举
- StreamResult: 统一的流式返回结构
- StreamParser: 统一的流式响应解析器
- _sanitize_tool_arguments: 工具参数清洗函数
- _sanitize_messages_for_api: 消息格式修复函数
"""
from __future__ import annotations

import json
import re
import time as _time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal, Optional

from base_tool import ATOMIC_TOOL_DEFINITIONS, CONTROL_TOOL_DEFINITIONS, REQUEST_TOOL_DETAILS_DEFINITION
from logger import get_module_logger
from llm.token_usage import TokenUsage

logger = get_module_logger("StreamParser")


# ═══════════════════════════════════════════════════════════════
# 工具参数清洗
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# StreamResultType & StreamResult
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# StreamParser
# ═══════════════════════════════════════════════════════════════

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

    def _process_tool_call(self, delta: Any) -> None:
        """处理工具调用流式拼接（function_call 旧格式，GLM 使用）"""
        tool_call = getattr(delta, 'function_call', None)
        if tool_call:
            if 0 not in self._tool_call_chunks:
                self._tool_call_chunks[0] = {
                    "id": "",
                    "name": "",
                    "arguments": "",
                }
            name_chunk = ""
            arguments_chunk = ""
            if hasattr(tool_call, 'name') and tool_call.name:
                name_chunk = tool_call.name
                self._tool_call_chunks[0]["name"] += name_chunk
            if hasattr(tool_call, 'arguments') and tool_call.arguments:
                arguments_chunk = tool_call.arguments
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
                self._process_tool_call(delta)
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
