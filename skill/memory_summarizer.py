from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .registry import SkillRegistry


@dataclass
class SkillExecutionMemory:
    """Skill 执行记忆数据类。"""

    skill_id: str
    session_id: str
    timestamp: str
    success: bool
    errors: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    best_practices: list[str] = field(default_factory=list)
    summary: str = ""


SUMMARIZE_PROMPT = """请分析以下 Skill 执行会话历史，提取关键经验。

Skill ID: {skill_id}

会话历史:
{conversation}

请以 JSON 格式返回以下字段（不要包含任何其他文字，只返回 JSON）:
{{
    "success": true/false,
    "errors": ["错误1", "错误2"],
    "fixes": ["修复方法1", "修复方法2"],
    "best_practices": ["最佳实践1", "最佳实践2"],
    "summary": "本次执行的简要总结"
}}

分析要点：
1. 执行过程中遇到的错误（包括错误类型、错误信息、发生原因）
2. 错误是如何被修复的（具体的修复步骤、解决方案）
3. 成功的执行步骤（哪些操作顺利完成）
4. 最佳实践建议（基于本次执行经验，对未来类似任务的建议）
"""


def summarize_skill_execution(
    skill_id: str,
    conversation_messages: list[dict],
    llm_model,
) -> SkillExecutionMemory:
    """
    调用 LLM 分析会话历史，提取关键经验。

    Args:
        skill_id: Skill 标识符
        conversation_messages: 会话消息列表
        llm_model: LLM 模型实例

    Returns:
        SkillExecutionMemory 对象
    """
    import json

    conversation_text = _format_conversation(conversation_messages)
    prompt = SUMMARIZE_PROMPT.format(
        skill_id=skill_id,
        conversation=conversation_text,
    )

    try:
        messages = [{"role": "user", "content": prompt}]
        response_msg = llm_model.complete(messages)
        response_text = getattr(response_msg, "content", "") or str(response_msg)
        result = _parse_llm_response(response_text)
    except Exception as e:
        result = {
            "success": False,
            "errors": [f"LLM 分析失败: {str(e)}"],
            "fixes": [],
            "best_practices": [],
            "summary": "无法生成执行总结",
        }

    return SkillExecutionMemory(
        skill_id=skill_id,
        session_id=str(uuid.uuid4())[:8],
        timestamp=datetime.now().isoformat(),
        success=result.get("success", False),
        errors=result.get("errors", []),
        fixes=result.get("fixes", []),
        best_practices=result.get("best_practices", []),
        summary=result.get("summary", ""),
    )


def _format_conversation(messages: list[dict]) -> str:
    """格式化会话消息为文本。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        metadata = msg.get("metadata")

        if metadata and isinstance(metadata, dict):
            meta_type = metadata.get("type")
            if meta_type == "tool_call":
                name = metadata.get("name", "unknown")
                args = metadata.get("args", {})
                args_str = _format_tool_args(args)
                lines.append(f"[assistant/tool_call]: 调用工具: {name}, 参数: {args_str}")
                continue

        if role == "tool":
            tool_name = metadata.get("name", "unknown") if metadata else "unknown"
            content_str = _format_content(content)
            lines.append(f"[tool/{tool_name}]: {content_str}")
            continue

        content_str = _format_content(content)
        lines.append(f"[{role}]: {content_str}")

    return "\n".join(lines)


def _format_content(content) -> str:
    """格式化消息内容。"""
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(
            c.get("text", str(c)) if isinstance(c, dict) else str(c)
            for c in content
        )
    return str(content)


def _format_tool_args(args) -> str:
    """格式化工具调用参数。"""
    import json

    if not args:
        return "{}"

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args

    if not isinstance(args, dict):
        return str(args)

    formatted_parts = []
    for key, value in args.items():
        if isinstance(value, str) and len(value) > 100:
            value = value[:100] + "..."
        formatted_parts.append(f"{key}={repr(value)}")

    return "{" + ", ".join(formatted_parts) + "}"


def _parse_llm_response(response: str) -> dict:
    """解析 LLM 返回的 JSON 响应。"""
    import json
    import re

    json_match = re.search(r"\{[\s\S]*\}", response)
    if json_match:
        return json.loads(json_match.group())
    return {
        "success": False,
        "errors": ["无法解析 LLM 响应"],
        "fixes": [],
        "best_practices": [],
        "summary": response,
    }


def save_skill_memory(
    skill_id: str,
    memory: SkillExecutionMemory,
    registry: SkillRegistry,
) -> Path | None:
    """
    在 Skill 包目录下创建或追加 skill_memory.md 文件。

    Args:
        skill_id: Skill 标识符
        memory: SkillExecutionMemory 对象
        registry: Skill 注册表

    Returns:
        skill_memory.md 文件路径，如果保存失败则返回 None
    """
    skill_def = registry.get(skill_id)
    if not skill_def or not skill_def.relative_path:
        return None

    skill_package_dir = skill_def.relative_path.parent
    if not skill_package_dir.exists():
        skill_package_dir.mkdir(parents=True, exist_ok=True)

    memory_path = skill_package_dir / "skill_memory.md"
    memory_content = format_memory_for_file(memory)

    if memory_path.exists():
        append_skill_memory(memory_path, memory_content)
    else:
        memory_path.write_text(memory_content, encoding="utf-8")

    return memory_path


def append_skill_memory(skill_memory_path: Path, new_content: str) -> None:
    """
    追加新内容到现有 skill_memory.md 文件。

    Args:
        skill_memory_path: skill_memory.md 文件路径
        new_content: 要追加的新内容
    """
    existing = skill_memory_path.read_text(encoding="utf-8")
    updated = existing.rstrip() + "\n\n---\n\n" + new_content
    skill_memory_path.write_text(updated, encoding="utf-8")


def format_memory_for_file(memory: SkillExecutionMemory) -> str:
    """
    将 SkillExecutionMemory 格式化为 Markdown 字符串。

    Args:
        memory: SkillExecutionMemory 对象

    Returns:
        格式化的 Markdown 字符串
    """
    lines = [
        f"# Skill 执行记录",
        "",
        f"- **Skill ID**: {memory.skill_id}",
        f"- **会话 ID**: {memory.session_id}",
        f"- **时间戳**: {memory.timestamp}",
        f"- **执行状态**: {'成功' if memory.success else '失败'}",
        "",
    ]

    if memory.errors:
        lines.append("## 遇到的错误")
        lines.append("")
        for err in memory.errors:
            lines.append(f"- {err}")
        lines.append("")

    if memory.fixes:
        lines.append("## 修复方法")
        lines.append("")
        for fix in memory.fixes:
            lines.append(f"- {fix}")
        lines.append("")

    if memory.best_practices:
        lines.append("## 最佳实践")
        lines.append("")
        for bp in memory.best_practices:
            lines.append(f"- {bp}")
        lines.append("")

    if memory.summary:
        lines.append("## 总结")
        lines.append("")
        lines.append(memory.summary)

    return "\n".join(lines)
