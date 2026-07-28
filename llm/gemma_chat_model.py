from __future__ import annotations

import json
from typing import Any, Optional

from openai import APIError, BadRequestError, AuthenticationError, RateLimitError, APIConnectionError

from .BaseChatModel import BaseChatModel


class GemmaChatModel(BaseChatModel):
    """
    Gemma 系列实现：
    - 使用新格式（tools + tool_choice）
    - 支持 reasoning_content
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

