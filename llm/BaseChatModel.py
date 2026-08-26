"""模型无关的对话/工具调用封装。

从 BaseChatModel.py 中让 `agent.py` 不再关心：
- OpenAI 兼容客户端如何创建
- 工具调用字段如何解析（tool_calls / function_call）
- 图像消息如何拼装
- 工具调用循环如何执行

拆分说明（2026-08）：
- StreamParser、StreamResult、StreamResultType、_sanitize_* -> llm/stream_parser.py
- ClientManager、TimeoutManager、StateTransitionMixin、ErrorHandlingMixin -> llm/connection.py
- 本文件保留 BaseChatModel 核心抽象基类定义
- 为保持向后兼容，通过重新导出使 `from llm.BaseChatModel import xxx` 继续工作
"""
from __future__ import annotations

import base64
import json
import time as _time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import Future
from typing import Any, Callable, Optional

from openai import BadRequestError, AuthenticationError, RateLimitError, APIConnectionError, APIError

import config
from logger import get_module_logger

logger = get_module_logger("BaseChatModel")

from executor import Executor
from base_tool import ATOMIC_TOOL_DEFINITIONS, CONTROL_TOOL_DEFINITIONS, REQUEST_TOOL_DETAILS_DEFINITION
from llm.token_usage import TokenUsage
from llm.communication_state import LLMCommunicationState
from llm.async_executor import get_executor_manager, AsyncTaskResult, TaskState

# 从拆分出的模块导入
from llm.stream_parser import (
    StreamParser,
    StreamResult,
    StreamResultType,
    _sanitize_tool_arguments,
    _sanitize_messages_for_api,
)
from llm.connection import (
    ClientManager,
    TimeoutManager,
    StateTransitionMixin,
    ErrorHandlingMixin,
)

# ═══════════════════════════════════════════════════════════════
# 向后兼容重新导出
# 保持 `from llm.BaseChatModel import StreamResult` 等外部引用正常工作
# ═══════════════════════════════════════════════════════════════
__all__ = [
    "BaseChatModel",
    "StreamResult",
    "StreamResultType",
    "StreamParser",
    "_sanitize_tool_arguments",
    "_sanitize_messages_for_api",
]


def _is_rate_limit_error(e: Exception) -> bool:
    """判断异常是否为 429 限流错误（含 OpenRouter 等聚合服务的流中错误）。

    OpenRouter 的流中 429 以普通 APIError 抛出（str 仅含 "Provider returned
    error"，不含状态码），状态码需从 e.body.code 中识别。
    """
    if isinstance(e, RateLimitError):
        return True
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        code = body.get("code")
        if code == 429 or str(code) == "429":
            return True
        inner = body.get("error")
        if isinstance(inner, dict):
            inner_code = inner.get("code")
            if inner_code == 429 or str(inner_code) == "429":
                return True
    return "429" in str(e) or "rate limit" in str(e).lower()


def _rate_limit_backoff(retry_count: int) -> float:
    """429 限流的重试退避时长（秒）。

    限流窗口通常按分钟计（如 OpenRouter 免费档约 20 请求/分钟），
    短退避（秒级）的密集重试会持续打满窗口形成重试风暴，
    因此使用 15/30/60 秒的长退避等待窗口恢复。
    """
    return min(15 * retry_count, 60)


class BaseChatModel(
    ABC,
    ClientManager,
    TimeoutManager,
    StateTransitionMixin,
    ErrorHandlingMixin,
):
    """
    模型无关的对话/工具调用封装。
    让 `agent.py` 不再关心：
    - OpenAI 兼容客户端如何创建
    - 工具调用字段如何解析（tool_calls / function_call）
    - 图像消息如何拼装
    - 工具调用循环如何执行
    """

    # 超时阈值（秒）—— 委托给 TimeoutManager，但在此保留类属性以供外部引用
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
        # 先初始化混入类
        ClientManager.__init__(self)
        TimeoutManager.__init__(self)
        # StateTransitionMixin 需要 self.model_name，所以延后在设置属性后初始化

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

        # StateTransitionMixin 初始化（需要 self.model_name）
        StateTransitionMixin.__init__(self)
        # ErrorHandlingMixin 不需要 __init__

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

    def extract_tool_call(self, message: Any) -> Optional[dict[str, str]]:
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

        # LLM API 调用重试逻辑（最多 LLM_MAX_RETRIES 次）
        # 429 限流使用长退避（15/30/60s）等待限流窗口恢复，其他错误沿用指数退避
        import config as _cfg
        _max_retries = getattr(_cfg, 'LLM_MAX_RETRIES', 3)
        _retry_count = 0

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

        while True:
            # === 阶段1：建立流式请求（create 错误在此重试） ===
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

            except (RateLimitError, APIConnectionError) as e:
                # 可重试错误：速率限制、网络连接问题
                _retry_count += 1
                if _retry_count <= _max_retries:
                    _backoff = _rate_limit_backoff(_retry_count) if _is_rate_limit_error(e) else min(2 ** _retry_count, 10)
                    logger.warning(
                        "LLM API 可重试错误 (%d/%d): %s, %d秒后重试",
                        _retry_count, _max_retries, type(e).__name__, _backoff,
                    )
                    _time.sleep(_backoff)
                    continue
                else:
                    return self._handle_api_error(e, stream_callback)

            except (BadRequestError, AuthenticationError, APIError) as e:
                # 不可重试错误：参数错误、认证失败等
                return self._handle_api_error(e, stream_callback)
            except Exception as e:
                _retry_count += 1
                if _retry_count <= _max_retries:
                    _backoff = min(2 ** _retry_count, 10)
                    logger.warning(
                        "LLM API 未知错误 (%d/%d): %s, %d秒后重试",
                        _retry_count, _max_retries, type(e).__name__, _backoff,
                    )
                    _time.sleep(_backoff)
                    continue
                else:
                    return self._handle_api_error(e, stream_callback)

            # === 阶段2：处理流式响应（流中限流/连接错误在此重试） ===
            # 记录是否已向前端输出内容：流中错误仅在未输出内容时才可安全重试（避免内容重复）
            _streamed_any = [False]
            _base_wrapped_callback = self._create_streaming_wrapped_callback(stream_callback)

            def _tracked_stream_callback(content: str, msg_type: str) -> None:
                _streamed_any[0] = True
                _base_wrapped_callback(content, msg_type)

            # 每次重试必须使用全新的 StreamParser（旧实例已累积部分流数据）
            parser = StreamParser(
                stream_callback=_tracked_stream_callback,
                messages=messages,
                estimate_tokens=self._estimate_tokens_from_messages,
                on_tool_call_chunk=on_tool_call_chunk_wrapper,
            )

            try:
                result = parser.process_stream(stream)
                # 流正常结束，转换状态为 COMMUNICATION_ENDED
                self._transition_communication_state(LLMCommunicationState.COMMUNICATION_ENDED)
                return result
            except Exception as e:
                # 流中限流/连接错误（如 OpenRouter 流中 429 "Provider returned error"）：
                # 尚未向前端输出任何内容时，等待后重建整个请求重试
                _retryable = (
                    not _streamed_any[0]
                    and _retry_count < _max_retries
                    and (isinstance(e, APIConnectionError) or _is_rate_limit_error(e))
                )
                if _retryable:
                    _retry_count += 1
                    _backoff = _rate_limit_backoff(_retry_count) if _is_rate_limit_error(e) else min(2 ** _retry_count, 10)
                    logger.warning(
                        "流中可重试错误 (%d/%d): %s, %d秒后重试整个请求",
                        _retry_count, _max_retries, type(e).__name__, _backoff,
                    )
                    self._transition_communication_state(
                        LLMCommunicationState.COMMUNICATION_ENDED,
                        error_message=str(e)
                    )
                    _time.sleep(_backoff)
                    continue  # 回到阶段1：重新 create 流
                error_msg = f"流式响应处理错误: {e}"
                if _is_rate_limit_error(e):
                    error_msg += "（模型服务限流 429，请稍后重试或切换模型）"
                stream_callback(error_msg, "assistant")
                # 异常时转换状态为 COMMUNICATION_ENDED
                self._transition_communication_state(
                    LLMCommunicationState.COMMUNICATION_ENDED,
                    error_message=error_msg
                )
                return StreamResult.from_error(error_msg)
            finally:
                # 方法返回前重置状态为 IDLE
                self._transition_communication_state(LLMCommunicationState.IDLE)

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
            stream_callback(error_msg, "assistant")
            # 异常时转换状态为 COMMUNICATION_ENDED
            self._transition_communication_state(
                LLMCommunicationState.COMMUNICATION_ENDED,
                error_message=error_msg
            )
            return StreamResult.from_error(error_msg)
        finally:
            # 方法返回前重置状态为 IDLE
            self._transition_communication_state(LLMCommunicationState.IDLE)

    def execute_tool_call(self, fname: str, args: dict, executor: Executor) -> str:
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
        tool_call = self.request_llm_with_tools(current_messages, tools)
        if not tool_call:
            raise Exception("未知的响应类型（未发现 tool_calls）")

        fname = tool_call.get("name")
        arg_str = tool_call.get("arguments") or "{}"
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

        result = self.execute_tool_call(fname, args, executor)

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

    # DEPRECATED: 仅 agent.py 使用，主流程不走此路径
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
