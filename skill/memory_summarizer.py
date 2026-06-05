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
    """
    解析 LLM 返回的 JSON 响应，使用多种提取策略。

    策略优先级：
    1. 代码块提取 - 查找 ```json ... ``` 或 ``` ... ``` 代码块
    2. 精确 JSON 对象匹配 - 使用更精确的正则表达式匹配完整的 JSON 对象
    3. 逐行查找 - 从响应中逐行查找包含 JSON 结构的行
    4. 宽松匹配 - 使用现有的宽松正则表达式作为兜底

    Args:
        response: LLM 返回的原始响应文本

    Returns:
        解析后的字典，如果所有策略都失败则返回默认错误响应
    """
    import json
    import re

    print(f"[SkillSummary] 开始解析 LLM 响应, 长度={len(response)}")
    print(f"[SkillSummary] 原始响应内容 (前500字符): {response[:500]}")

    # 记录解析失败的详细信息
    parse_errors = []

    # 策略 1：代码块提取
    print(f"[SkillSummary] 尝试提取 JSON (策略1: 代码块提取)")
    try:
        result = _extract_json_from_code_block(response)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略1(代码块提取)成功")
            return result
        parse_errors.append("策略1(代码块提取): 未找到有效JSON代码块")
    except Exception as e:
        error_msg = f"策略1(代码块提取)异常: {type(e).__name__}: {e}"
        print(f"[SkillSummary] ⚠️ {error_msg}")
        parse_errors.append(error_msg)
    print(f"[SkillSummary] ⚠️ 策略1(代码块提取)失败，尝试下一策略")

    # 策略 2：精确 JSON 对象匹配
    print(f"[SkillSummary] 尝试提取 JSON (策略2: 精确JSON匹配)")
    try:
        result = _extract_json_precise(response)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略2(精确JSON匹配)成功")
            return result
        parse_errors.append("策略2(精确JSON匹配): 未找到有效JSON对象")
    except Exception as e:
        error_msg = f"策略2(精确JSON匹配)异常: {type(e).__name__}: {e}"
        print(f"[SkillSummary] ⚠️ {error_msg}")
        parse_errors.append(error_msg)
    print(f"[SkillSummary] ⚠️ 策略2(精确JSON匹配)失败，尝试下一策略")

    # 策略 3：逐行查找
    print(f"[SkillSummary] 尝试提取 JSON (策略3: 逐行查找)")
    try:
        result = _extract_json_line_by_line(response)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略3(逐行查找)成功")
            return result
        parse_errors.append("策略3(逐行查找): 未找到有效JSON结构")
    except Exception as e:
        error_msg = f"策略3(逐行查找)异常: {type(e).__name__}: {e}"
        print(f"[SkillSummary] ⚠️ {error_msg}")
        parse_errors.append(error_msg)
    print(f"[SkillSummary] ⚠️ 策略3(逐行查找)失败，尝试下一策略")

    # 策略 4：宽松匹配（兜底）
    print(f"[SkillSummary] 尝试提取 JSON (策略4: 宽松匹配)")
    try:
        result = _extract_json_loose(response)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略4(宽松匹配)成功")
            return result
        parse_errors.append("策略4(宽松匹配): 未找到有效JSON结构")
    except Exception as e:
        error_msg = f"策略4(宽松匹配)异常: {type(e).__name__}: {e}"
        print(f"[SkillSummary] ⚠️ {error_msg}")
        parse_errors.append(error_msg)

    # 所有策略都失败，执行降级处理
    print(f"[SkillSummary] ❌ 所有策略都失败，执行降级处理")
    print(f"[SkillSummary] 📋 解析错误汇总:")
    for i, error in enumerate(parse_errors, 1):
        print(f"[SkillSummary]   {i}. {error}")

    # 降级处理：返回默认结构，确保流程不中断
    fallback_result = _create_fallback_response(response, parse_errors)
    print(f"[SkillSummary] 🔄 已生成降级响应，流程将继续执行")
    return fallback_result


def _create_fallback_response(response: str, parse_errors: list[str]) -> dict:
    """
    创建降级响应，当所有 JSON 解析策略都失败时使用。

    Args:
        response: 原始 LLM 响应文本
        parse_errors: 解析过程中的错误列表

    Returns:
        包含基本字段的默认响应字典
    """
    # 截取响应内容，避免过长
    truncated_response = response[:1000] if len(response) > 1000 else response

    # 构建错误信息
    error_summary = "JSON解析失败"
    if parse_errors:
        error_summary = f"JSON解析失败: {parse_errors[0]}"

    return {
        "success": False,
        "errors_and_fixes": [error_summary],
        "tips": ["建议检查LLM响应格式，确保返回有效的JSON"],
        "summary": f"[解析失败] 原始响应: {truncated_response}",
    }


def _fix_json_format(json_str: str) -> str:
    """
    修复常见的 JSON 格式错误。

    修复策略包括：
    1. 修复属性名缺少双引号
    2. 将单引号替换为双引号
    3. 移除尾随逗号
    4. 移除控制字符
    5. 移除注释

    Args:
        json_str: 可能包含格式错误的 JSON 字符串

    Returns:
        修复后的 JSON 字符串
    """
    import re

    original_str = json_str
    fixes_applied = []
    fix_details = []  # 记录详细的修复信息

    print(f"[SkillSummary] 开始 JSON 格式修复, 原始长度={len(json_str)}")

    # 策略 1：修复属性名缺少双引号
    # 匹配模式：{key: 或 ,key: 其中 key 是标识符（字母、数字、下划线）
    # 注意：需要避免匹配已经在引号中的属性名
    fixed = json_str

    # 匹配未加引号的属性名（排除已经在引号中的）
    # 模式：在 { 或 , 之后，可能有空格，然后是标识符，然后是 :
    pattern = r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)'
    matches = list(re.finditer(pattern, fixed))

    if matches:
        fixed_count = 0
        # 从后往前替换，避免位置偏移
        for match in reversed(matches):
            # 检查属性名是否已经被引号包围
            prop_name = match.group(2)
            start_pos = match.start(2)
            # 检查前面是否有引号
            if start_pos > 0 and fixed[start_pos - 1] in ['"', "'"]:
                continue
            # 添加双引号
            fixed = fixed[:match.start(2)] + '"' + prop_name + '"' + fixed[match.end(2):]
            fixed_count += 1

        if fixed != json_str:
            fixes_applied.append("添加属性名双引号")
            fix_details.append(f"添加了 {fixed_count} 处属性名双引号")
            print(f"[SkillSummary] 修复操作: 添加属性名双引号 ({fixed_count} 处)")
            print(f"[SkillSummary] 修复前片段: {json_str[max(0, matches[0].start() - 20):matches[0].end() + 20]}")
            print(f"[SkillSummary] 修复后片段: {fixed[max(0, matches[0].start() - 20):matches[0].end() + 22]}")
            json_str = fixed

    # 策略 2：将单引号替换为双引号
    # 需要小心处理，避免破坏字符串内的单引号
    # 简单策略：将键和值的单引号替换为双引号
    fixed = json_str

    # 替换键的单引号：'key': -> "key":
    fixed = re.sub(r"'([^']+)'(\s*:)", r'"\1"\2', fixed)

    # 替换值的单引号：: 'value' -> : "value"
    # 注意：这可能会误替换字符串内的单引号，但对于简单的 JSON 通常有效
    fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)

    if fixed != json_str:
        fixes_applied.append("单引号替换为双引号")
        fix_details.append("将单引号替换为双引号")
        print(f"[SkillSummary] 修复操作: 单引号替换为双引号")
        json_str = fixed

    # 策略 3：移除尾随逗号
    # 匹配：,} 或 ,] 中的逗号
    fixed = re.sub(r',(\s*[}\]])', r'\1', json_str)

    if fixed != json_str:
        fixes_applied.append("移除尾随逗号")
        fix_details.append("移除了尾随逗号")
        print(f"[SkillSummary] 修复操作: 移除尾随逗号")
        json_str = fixed

    # 策略 4：移除控制字符
    # 移除或转义控制字符（除了常见的空白字符）
    fixed = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)

    if fixed != json_str:
        fixes_applied.append("移除控制字符")
        fix_details.append("移除了控制字符")
        print(f"[SkillSummary] 修复操作: 移除控制字符")
        json_str = fixed

    # 策略 5：移除注释
    # 移除单行注释
    fixed = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)
    # 移除多行注释
    fixed = re.sub(r'/\*[\s\S]*?\*/', '', fixed)

    if fixed != json_str:
        fixes_applied.append("移除注释")
        fix_details.append("移除了注释内容")
        print(f"[SkillSummary] 修复操作: 移除注释")
        json_str = fixed

    # 记录修复日志
    if fixes_applied:
        print(f"[SkillSummary] JSON 格式修复完成: {', '.join(fixes_applied)}")
        print(f"[SkillSummary] 修复前 (前100字符): {original_str[:100]}")
        print(f"[SkillSummary] 修复后 (前100字符): {json_str[:100]}")
    else:
        print(f"[SkillSummary] 未检测到需要修复的 JSON 格式问题")

    return json_str


def _try_parse_json(json_str: str) -> dict | None:
    """
    尝试解析 JSON 字符串，支持自动修复常见格式错误。

    解析策略优先级：
    1. 直接解析（不修复）
    2. 修复后解析（多种修复策略组合）

    Args:
        json_str: 待解析的 JSON 字符串

    Returns:
        解析成功返回字典，失败返回 None
    """
    import json

    print(f"[SkillSummary] 尝试解析 JSON, 内容长度={len(json_str)}")

    # 策略 1：直接解析
    try:
        result = json.loads(json_str)
        if isinstance(result, dict):
            print(f"[SkillSummary] ✅ JSON 直接解析成功")
            return result
        print(f"[SkillSummary] ⚠️ JSON 解析结果不是字典类型: {type(result)}")
        return None
    except json.JSONDecodeError as e:
        print(f"[SkillSummary] 直接解析失败: {e.msg}")
        print(f"[SkillSummary] 错误类型: {type(e).__name__}")
        print(f"[SkillSummary] 错误位置: 行 {e.lineno}, 列 {e.colno}, 字符位置 {e.pos}")
        # 显示错误上下文，用 [HERE] 标记错误位置
        context_start = max(0, e.pos - 30)
        context_end = min(len(json_str), e.pos + 30)
        print(f"[SkillSummary] 错误上下文: ...{json_str[context_start:e.pos]}[HERE]{json_str[e.pos:context_end]}...")

    # 策略 2：尝试修复后解析
    print(f"[SkillSummary] 尝试修复 JSON 格式后重新解析...")
    fixed_json = _fix_json_format(json_str)

    # 检查是否有修复
    if fixed_json == json_str:
        print(f"[SkillSummary] 未进行任何修复，解析失败")
        return None

    try:
        result = json.loads(fixed_json)
        if isinstance(result, dict):
            print(f"[SkillSummary] ✅ JSON 修复后解析成功")
            return result
        print(f"[SkillSummary] ⚠️ JSON 解析结果不是字典类型: {type(result)}")
        return None
    except json.JSONDecodeError as e:
        print(f"[SkillSummary] 修复后解析仍然失败: {e.msg}")
        print(f"[SkillSummary] 错误类型: {type(e).__name__}")
        print(f"[SkillSummary] 错误位置: 行 {e.lineno}, 列 {e.colno}, 字符位置 {e.pos}")
        # 显示修复后的错误上下文
        context_start = max(0, e.pos - 30)
        context_end = min(len(fixed_json), e.pos + 30)
        print(f"[SkillSummary] 修复后错误上下文: ...{fixed_json[context_start:e.pos]}[HERE]{fixed_json[e.pos:context_end]}...")
        return None


def _extract_json_from_code_block(response: str) -> dict | None:
    """
    策略1：从代码块中提取 JSON。

    查找 ```json ... ``` 或 ``` ... ``` 格式的代码块。

    Args:
        response: LLM 响应文本

    Returns:
        解析成功返回字典，失败返回 None
    """
    import re

    print(f"[SkillSummary] 尝试提取 JSON (策略1: 代码块提取)")

    # 匹配 ```json ... ``` 或 ``` ... ``` 代码块
    pattern = r"```(?:json)?\s*\n([\s\S]*?)\n```"
    matches = re.findall(pattern, response)

    if not matches:
        print(f"[SkillSummary] 策略1: 未找到代码块")
        return None

    print(f"[SkillSummary] 策略1: 找到 {len(matches)} 个代码块候选")

    for i, code_content in enumerate(matches):
        print(f"[SkillSummary] 策略1: 尝试解析候选 {i + 1} (长度: {len(code_content)})")
        result = _try_parse_json(code_content.strip())
        if result is not None:
            print(f"[SkillSummary] ✅ 策略1: JSON 解析成功")
            return result

    print(f"[SkillSummary] 策略1: 所有代码块候选都无法解析为有效 JSON")
    return None


def _extract_json_precise(response: str) -> dict | None:
    """
    策略2：使用精确正则表达式匹配完整的 JSON 对象。

    使用正则表达式匹配嵌套的大括号结构。

    Args:
        response: LLM 响应文本

    Returns:
        解析成功返回字典，失败返回 None
    """
    import re

    print(f"[SkillSummary] 尝试提取 JSON (策略2: 精确JSON匹配)")

    # 匹配完整的 JSON 对象（支持一层嵌套）
    # 这个正则表达式匹配从 { 开始，到对应的 } 结束
    # 可以处理简单的嵌套结构
    pattern = r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}"
    matches = re.findall(pattern, response)

    if not matches:
        print(f"[SkillSummary] 策略2: 未找到 JSON 对象模式")
        return None

    print(f"[SkillSummary] 策略2: 找到 {len(matches)} 个可能的 JSON 对象候选")

    # 优先尝试最长的匹配（通常是最完整的 JSON）
    matches_sorted = sorted(matches, key=len, reverse=True)

    for i, json_candidate in enumerate(matches_sorted):
        print(f"[SkillSummary] 策略2: 尝试解析候选 {i + 1} (长度: {len(json_candidate)})")
        result = _try_parse_json(json_candidate)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略2: JSON 解析成功")
            return result

    print(f"[SkillSummary] 策略2: 所有候选都无法解析为有效 JSON")
    return None


def _extract_json_line_by_line(response: str) -> dict | None:
    """
    策略3：逐行查找包含 JSON 结构的行。

    查找同时包含 { 和 } 的行，尝试提取 JSON。

    Args:
        response: LLM 响应文本

    Returns:
        解析成功返回字典，失败返回 None
    """
    print(f"[SkillSummary] 尝试提取 JSON (策略3: 逐行查找)")

    lines = response.split('\n')
    json_candidates = []

    for i, line in enumerate(lines):
        line = line.strip()
        if '{' in line and '}' in line:
            json_candidates.append((i, line))

    if not json_candidates:
        print(f"[SkillSummary] 策略3: 未找到包含 JSON 结构的行")
        return None

    print(f"[SkillSummary] 策略3: 找到 {len(json_candidates)} 个包含 JSON 结构的行候选")

    for line_num, candidate in json_candidates:
        print(f"[SkillSummary] 策略3: 尝试解析第 {line_num + 1} 行 (长度: {len(candidate)})")
        result = _try_parse_json(candidate)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略3: JSON 解析成功")
            return result

    # 尝试合并多行
    print(f"[SkillSummary] 策略3: 尝试合并多行查找 JSON")
    start_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if '{' in line and start_idx is None:
            start_idx = i
        if '}' in line and start_idx is not None:
            end_idx = i
            break

    if start_idx is not None and end_idx is not None:
        merged_content = '\n'.join(lines[start_idx:end_idx + 1])
        print(f"[SkillSummary] 策略3: 合并行 {start_idx + 1} 到 {end_idx + 1} (长度: {len(merged_content)})")
        result = _try_parse_json(merged_content)
        if result is not None:
            print(f"[SkillSummary] ✅ 策略3: JSON 解析成功 (合并多行)")
            return result

    print(f"[SkillSummary] 策略3: 所有尝试都失败")
    return None


def _extract_json_loose(response: str) -> dict | None:
    """
    策略4：宽松匹配（兜底策略）。

    使用最宽松的正则表达式匹配，从第一个 { 到最后一个 }。

    Args:
        response: LLM 响应文本

    Returns:
        解析成功返回字典，失败返回 None
    """
    import re

    print(f"[SkillSummary] 尝试提取 JSON (策略4: 宽松匹配)")

    pattern = r"\{[\s\S]*\}"
    match = re.search(pattern, response)

    if not match:
        print(f"[SkillSummary] 策略4: 未找到任何 JSON 结构")
        return None

    json_str = match.group()
    print(f"[SkillSummary] 策略4: 找到宽松匹配候选 (长度: {len(json_str)})")

    result = _try_parse_json(json_str)
    if result is not None:
        print(f"[SkillSummary] ✅ 策略4: JSON 解析成功")
        return result

    print(f"[SkillSummary] 策略4: 宽松匹配候选无法解析为有效 JSON")
    return None


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
