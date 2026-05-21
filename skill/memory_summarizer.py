from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from resource_path import paths
from memory.searcher import MemorySearcher
from .registry import SkillRegistry


@dataclass
class SkillExecutionMemory:
    """Skill 执行记忆数据类。"""

    skill_id: str
    session_id: str
    timestamp: str
    success: bool
    errors_and_fixes: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    summary: str = ""


SUMMARIZE_PROMPT = """分析以下 Skill 执行会话，提取关键经验。只返回 JSON，不要其他文字。

Skill ID: {skill_id}

会话历史:
{conversation}

返回格式:
{{
    "success": true/false,
    "errors_and_fixes": ["错误: xxx → 修复: xxx"],
    "tips": ["对未来执行的建议1", "建议2"],
    "summary": "一句话总结"
}}

要求：
1. errors_and_fixes: 将错误和对应修复合并，格式"错误: ... → 修复: ..."；无错误则留空数组
2. tips: 对未来执行该skill最有价值的建议，合并最佳实践
3. summary: 一句话概括本次执行结果
4. 所有字段内容精简，避免重复
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
    import traceback
    
    print(f"[SkillSummary] summarize_skill_execution 开始: skill_id={skill_id}, messages_count={len(conversation_messages)}")
    
    conversation_text = _format_conversation(conversation_messages)
    print(f"[SkillSummary] 格式化会话文本完成: length={len(conversation_text)}")
    
    prompt = SUMMARIZE_PROMPT.format(
        skill_id=skill_id,
        conversation=conversation_text,
    )
    print(f"[SkillSummary] 准备调用 LLM 进行总结 (skill_id={skill_id})")

    try:
        messages = [{"role": "user", "content": prompt}]
        response_msg = llm_model.complete(messages)
        response_text = getattr(response_msg, "content", "") or str(response_msg)
        print(f"[SkillSummary] LLM 响应接收完成 (skill_id={skill_id}), length={len(response_text)}")
        
        result = _parse_llm_response(response_text)
        print(f"[SkillSummary] JSON 解析成功 (skill_id={skill_id}), success={result.get('success')}")
    except Exception as e:
        print(f"[SkillSummary] ❌ LLM 分析异常 (skill_id={skill_id}): {type(e).__name__}: {e}")
        print(f"[SkillSummary] 📋 异常堆栈:\n{traceback.format_exc()}")
        
        result = {
            "success": False,
            "errors_and_fixes": [f"LLM 分析失败: {str(e)}"],
            "tips": [],
            "summary": "无法生成执行总结",
        }

    memory = SkillExecutionMemory(
        skill_id=skill_id,
        session_id=str(uuid.uuid4())[:8],
        timestamp=datetime.now().isoformat(),
        success=result.get("success", False),
        errors_and_fixes=result.get("errors_and_fixes", []),
        tips=result.get("tips", []),
        summary=result.get("summary", ""),
    )
    
    print(f"[SkillSummary] summarize_skill_execution 完成: skill_id={skill_id}, success={memory.success}")
    return memory


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
        "errors_and_fixes": ["无法解析 LLM 响应"],
        "tips": [],
        "summary": response,
    }


def save_skill_memory(
    skill_id: str,
    memory: SkillExecutionMemory,
    registry: SkillRegistry,
    searcher: MemorySearcher | None = None,
) -> str | None:
    """
    保存 Skill 执行记忆到数据库。

    Args:
        skill_id: Skill 标识符
        memory: SkillExecutionMemory 对象
        registry: Skill 注册表
        searcher: MemorySearcher 实例（可选）

    Returns:
        segment_id，如果保存失败则返回 None
    """
    _searcher = searcher or MemorySearcher()
    
    memory_content = format_memory_for_file(memory)
    metadata = {
        "session_id": memory.session_id,
        "timestamp": memory.timestamp,
        "success": memory.success,
        "errors_and_fixes": memory.errors_and_fixes,
        "tips": memory.tips,
        "summary": memory.summary,
    }
    
    try:
        segment_id = _searcher.add_segment(
            memory_type=MemorySearcher.SKILL,
            content=memory_content,
            related_id=skill_id,
            metadata=metadata,
        )
        print(f"[SkillSummary] save_skill_memory: 已保存到数据库 skill_id={skill_id}, segment_id={segment_id}")
        return segment_id
    except Exception as e:
        print(f"[SkillSummary] save_skill_memory: 保存到数据库失败 skill_id={skill_id}, error={e}")
        return None


def append_skill_memory(skill_memory_path: Path, new_content: str) -> None:
    """
    追加新内容到现有 skill_memory.md 文件（用于向后兼容）。

    Args:
        skill_memory_path: skill_memory.md 文件路径
        new_content: 要追加的新内容
    """
    existing = skill_memory_path.read_text(encoding="utf-8")
    updated = existing.rstrip() + "\n\n---\n\n" + new_content
    skill_memory_path.write_text(updated, encoding="utf-8")


def format_memory_for_file(memory: SkillExecutionMemory) -> str:
    status = "成功" if memory.success else "失败"
    parts = [f"### {status} | {memory.timestamp[:10]}", ""]

    if memory.errors_and_fixes:
        parts.append("- 错误与修复:")
        for ef in memory.errors_and_fixes:
            parts.append(f"  - {ef}")

    if memory.tips:
        parts.append("- 要点:")
        for tip in memory.tips:
            parts.append(f"  - {tip}")

    if memory.summary:
        parts.append(f"- 总结: {memory.summary}")

    return "\n".join(parts)


def get_skill_memory(
    skill_id: str,
    query: str | None = None,
    limit: int = 5,
    searcher: MemorySearcher | None = None,
) -> list[dict[str, Any]]:
    """
    获取 Skill 执行记忆。

    Args:
        skill_id: Skill 标识符
        query: 检索查询（可选，如果不提供则返回所有记忆）
        limit: 返回数量限制
        searcher: MemorySearcher 实例（可选）

    Returns:
        记忆片段列表
    """
    _searcher = searcher or MemorySearcher()
    
    if query:
        segments = _searcher.search(
            query=query,
            memory_type=MemorySearcher.SKILL,
            related_id=skill_id,
            limit=limit,
        )
    else:
        segments = _searcher.get_all(
            memory_type=MemorySearcher.SKILL,
            related_id=skill_id,
            limit=limit,
        )
    
    return [
        {
            "content": seg.content,
            "metadata": seg.metadata,
            "created_at": seg.created_at.isoformat() if seg.created_at else None,
            "score": seg.score,
        }
        for seg in segments
    ]


def migrate_skill_memory_from_file(
    skill_id: str,
    skill_memory_path: Path,
    searcher: MemorySearcher | None = None,
) -> int:
    """
    从文件迁移 Skill 记忆到数据库。

    Args:
        skill_id: Skill 标识符
        skill_memory_path: skill_memory.md 文件路径
        searcher: MemorySearcher 实例（可选）

    Returns:
        迁移的片段数量
    """
    if not skill_memory_path.exists():
        return 0
    
    _searcher = searcher or MemorySearcher()
    content = skill_memory_path.read_text(encoding="utf-8")
    
    if not content.strip():
        return 0
    
    segments = _parse_skill_memory_file(content)
    migrated = 0
    
    for seg_content, metadata in segments:
        _searcher.add_segment(
            memory_type=MemorySearcher.SKILL,
            content=seg_content,
            related_id=skill_id,
            metadata=metadata,
        )
        migrated += 1
    
    if migrated > 0:
        backup_path = skill_memory_path.with_suffix(".md.bak")
        skill_memory_path.rename(backup_path)
    
    return migrated


def _parse_skill_memory_file(content: str) -> list[tuple[str, dict]]:
    """解析 skill_memory.md 文件格式，返回 (内容, 元数据) 列表。"""
    import re
    
    segments = []
    pattern = r"###\s*(成功|失败)\s*\|\s*([^\n]+)\n(.*?)(?=###\s*(?:成功|失败)|$)"
    matches = re.findall(pattern, content, re.DOTALL)
    
    for status, date_str, seg_content in matches:
        seg_content = seg_content.strip()
        if seg_content:
            metadata = {
                "success": status == "成功",
                "original_date": date_str.strip(),
                "migrated_from_file": True,
            }
            segments.append((seg_content, metadata))
    
    if not matches and content.strip():
        segments.append((content.strip(), {"migrated_from_file": True}))
    
    return segments
