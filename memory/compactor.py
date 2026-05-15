from __future__ import annotations

import re
from typing import Any, Callable

import config
from llm.BaseChatModel import BaseChatModel
from memory import Memory


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量。

    根据文本中的中文字符比例采用不同的估算策略：
    - 中文字符按 1.5 字符/token 估算
    - 英文及其他字符按 4 字符/token 估算

    Args:
        text: 待估算的文本内容。

    Returns:
        估算的 token 数量。
    """
    if not text:
        return 0

    chinese_pattern = re.compile(r"[\u4e00-\u9fff]")
    chinese_chars = len(chinese_pattern.findall(text))
    total_chars = len(text)

    if total_chars == 0:
        return 0

    chinese_ratio = chinese_chars / total_chars

    if chinese_ratio > 0.3:
        return int(total_chars / 1.5)
    else:
        return int(total_chars / 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """估算消息列表的总 token 数量。

    遍历消息列表，累加每条消息的 token 估算值。
    主要计算 role 和 content 字段的 token 数。

    Args:
        messages: 消息列表，每条消息为包含 role、content 等字段的字典。

    Returns:
        消息列表的总 token 估算值。
    """
    total_tokens = 0

    for message in messages:
        role = message.get("role", "")
        total_tokens += estimate_tokens(role)

        content = message.get("content")
        if isinstance(content, str):
            total_tokens += estimate_tokens(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    total_tokens += estimate_tokens(text)

        name = message.get("name", "")
        if name:
            total_tokens += estimate_tokens(name)

        total_tokens += 4

    return total_tokens


class ContextCompactor:
    """上下文压缩器。

    负责检测上下文是否需要压缩，并调用 LLM 生成摘要以压缩对话历史。
    """

    def __init__(self, memory: Memory, model: BaseChatModel) -> None:
        """初始化上下文压缩器。

        Args:
            memory: Memory 实例，用于访问消息存储。
            model: BaseChatModel 实例，用于调用 LLM 生成摘要。
        """
        self.memory = memory
        self.model = model

    def should_compact(self, messages: list[dict]) -> bool:
        """判断是否需要压缩上下文。

        根据配置的上下文窗口大小和压缩阈值判断当前消息列表是否需要压缩。

        Args:
            messages: 当前消息列表。

        Returns:
            如果需要压缩返回 True，否则返回 False。
        """
        if not config.COMPACTION_ENABLED:
            return False

        current_tokens = estimate_messages_tokens(messages)
        threshold_tokens = int(config.CONTEXT_WINDOW_SIZE * config.COMPACTION_THRESHOLD)

        return current_tokens >= threshold_tokens

    def generate_summary(
        self,
        messages: list[dict],
        log_callback: Callable[[str, str], Any] | None = None,
    ) -> str:
        """调用 LLM 生成对话摘要。

        使用结构化提示词，要求摘要包含：
        - 用户意图
        - 已执行操作
        - 关键决策
        - 重要结果

        Args:
            messages: 待压缩的消息列表。
            log_callback: 可选的日志回调函数。

        Returns:
            生成的摘要文本。
        """
        conversation_text = self._format_messages_for_summary(messages)

        system_prompt = """你是一个对话摘要助手。请将以下对话历史压缩为简洁的结构化摘要。

摘要必须包含以下部分：
1. 用户意图：用户想要达成什么目标
2. 已执行操作：已经执行了哪些关键操作
3. 关键决策：做出了哪些重要决策
4. 重要结果：获得了哪些重要结果或结论

请用简洁的中文撰写摘要，保留关键信息，省略无关细节。"""

        user_prompt = f"""以下是对话历史，请生成摘要：

{conversation_text}

请生成结构化摘要："""

        summary_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if log_callback:
            log_callback("正在生成对话摘要...", "info")

        response = self.model.complete(summary_messages)

        summary = getattr(response, "content", "") or ""

        if log_callback:
            log_callback(f"摘要生成完成，长度: {len(summary)} 字符", "info")

        return summary

    def _format_messages_for_summary(self, messages: list[dict]) -> str:
        """将消息列表格式化为摘要用的文本。

        Args:
            messages: 消息列表。

        Returns:
            格式化后的文本。
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                content = " ".join(text_parts)

            if content:
                lines.append(f"[{role}]: {content}")

        return "\n".join(lines)

    def compact(
        self,
        conversation_id: str,
        messages: list[dict],
        log_callback: Callable[[str, str], Any] | None = None,
    ) -> list[dict]:
        """压缩对话上下文。

        执行以下步骤：
        1. 从 memory 获取待压缩和保留的消息
        2. 调用 LLM 生成摘要
        3. 保存摘要到 memory
        4. 返回压缩后的消息列表

        Args:
            conversation_id: 会话 ID。
            messages: 当前消息列表。
            log_callback: 可选的日志回调函数。

        Returns:
            压缩后的消息列表（包含摘要消息和保留的最近消息）。
        """
        if log_callback:
            log_callback("开始压缩对话上下文...", "info")

        to_compact, to_keep = self.memory.get_messages_for_compaction(
            conversation_id,
            config.COMPACTION_KEEP_RECENT,
        )

        if not to_compact:
            if log_callback:
                log_callback("没有需要压缩的消息", "info")
            return messages

        if log_callback:
            log_callback(
                f"待压缩消息: {len(to_compact)} 条，保留消息: {len(to_keep)} 条",
                "info",
            )

        summary = self.generate_summary(to_compact, log_callback)

        compacted_ids = []
        for msg in to_compact:
            msg_id = msg.get("id") or msg.get("message_id")
            if msg_id:
                compacted_ids.append(msg_id)

        self.memory.save_compaction_summary(conversation_id, summary, compacted_ids)

        if log_callback:
            log_callback("对话上下文压缩完成", "info")

        summary_message = {
            "role": "system",
            "content": f"[对话历史摘要]\n{summary}",
        }

        compacted_messages = [summary_message] + to_keep

        return compacted_messages
