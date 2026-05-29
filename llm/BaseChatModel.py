from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from openai import OpenAI, APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

import config
from executor import Executor
from base_tool import ATOMIC_TOOL_DEFINITIONS, CONTROL_TOOL_DEFINITIONS, REQUEST_TOOL_DETAILS_DEFINITION
from llm.token_usage import TokenUsage


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
        - tool_name: 工具名称（如 "run_command", "file_operation"）
        
        返回：
        - 找到：完整工具定义 dict
        - 未找到：None
        
        注意：此方法只处理 ATOMIC_TOOL_DEFINITIONS 中的工具，
              CONTROL 工具在初始化时已直接提供。
        """
        for tool_def in ATOMIC_TOOL_DEFINITIONS:
            if tool_def["name"] == tool_name:
                return tool_def
        return None

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def extract_function_call(self, message: Any) -> Optional[dict[str, str]]:
        """
        尝试从模型输出中提取工具调用信息。
        返回格式：{"name": ..., "arguments": "...json..."} 或 None
        """

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
            return {"name": str(name), "arguments": str(arguments)}

        legacy = getattr(message, "function_call", None)
        if legacy is not None:
            name = getattr(legacy, "name", None)
            arguments = getattr(legacy, "arguments", None) or "{}"
            if name:
                return {"name": str(name), "arguments": str(arguments)}

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
        import time as _time

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
        import time as _time

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
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except AuthenticationError as e:
            error_msg = f"API认证失败: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except RateLimitError as e:
            error_msg = f"API请求频率超限: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except APIConnectionError as e:
            error_msg = f"API连接失败: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except APIError as e:
            error_msg = f"API错误: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
            msg = SimpleNamespace()
            msg.content = error_msg
            msg.reasoning_content = ""
            msg.token_usage = None
            return msg
        except Exception as e:
            error_msg = f"未知错误: {e}"
            stream_callback(error_msg, "content")
            from types import SimpleNamespace
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
            from types import SimpleNamespace
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

        from types import SimpleNamespace
        msg = SimpleNamespace()
        msg.content = "".join(all_content_parts)
        msg.reasoning_content = "".join(all_reasoning_parts)
        msg.token_usage = token_usage
        return msg

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

            result = self.execute_function_call(fname, args, executor)

            if log_callback:
                log_callback(str({fname: {"result": result}}), "response")

            if result == "任务完成":
                if log_callback:
                    log_callback("任务完成", "response")
                return "任务完成"

            current_messages.append({"role": "tool", "name": fname, "content": str(result)})
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