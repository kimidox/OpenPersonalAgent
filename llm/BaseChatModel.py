from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from openai import OpenAI

import config
from executor import Executor


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

    def complete_with_tools(self, messages: list[dict], tools: list[dict]) -> Any:
        """发起一次带 tools 的补全，返回 choices[0].message。"""
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

    def complete(self, messages: list[dict]) -> Any:
        """发起一次不带工具的纯文本补全，返回 choices[0].message。"""
        response = self.get_client().chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            extra_body=self.extra_body,
        )
        return response.choices[0].message

    def request_llm_with_tools(self, messages: list[dict], tools: list[dict]) -> Optional[dict[str, str]]:
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