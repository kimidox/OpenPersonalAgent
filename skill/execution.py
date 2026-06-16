from __future__ import annotations

from .loader import load_skill_memory_lazy
from .processing import format_skill_for_prompt, normalize_skill_id
from .registry import SkillRegistry
from logger import get_module_logger

logger = get_module_logger("SkillExecution")

SKILL_CONTROL_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "select_skill",
        "description": (
            "从 Skill 列表中按 skill_id 加载完整文档。同一轮对话可多次调用："
            "若任务需要多种规范（例如先走 A 流程再走 B 约束），应依次 select_skill；"
            "后加载的文档会与先前已加载的一并作为约束，而非互相覆盖。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Skill 唯一标识，与列表中反引号内一致"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "finish",
        "description": "当已根据所选 Skill（可多个）完成用户业务目标时调用，返回面向用户的最终答复。",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "给用户的最终说明或结果摘要"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "ask_user",
        "description": (
            "当缺少关键信息、存在多种合理走向需用户拍板、或必须确认敏感操作前，向用户提问。"
            "调用后会暂停本轮 Agent，直到用户在输入框回复；用户回复后对话会从你的澄清点继续。"
            "请勿滥用：同一任务内澄清次数宜少而精。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "向用户提出的具体问题（简洁、可回答）"},
                "context": {
                    "type": "string",
                    "description": "可选：为何需要这条信息，或当前已掌握信息的简要说明",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：若干互斥选项；用户可照抄其一回复，也可自由作答",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "load_skill_memory",
        "description": (
            "加载指定 Skill 的执行经验（skill_memory.md）。"
            "当你执行 Skill 遇到任何问题、困难、失败、工具报错或异常时，都必须调用此工具获取历史经验帮助解决问题。"
            "经验内容包含之前执行该 Skill 时遇到的问题及解决方案。"
            "可通过 query 参数进行语义检索，精准获取与当前问题相关的经验。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Skill 唯一标识"},
                "query": {"type": "string", "description": "可选：检索关键词，用于语义搜索相关经验。不提供则返回最近的记录。"},
            },
            "required": ["skill_id"],
        },
    },
]


def execute_skill_control_tool(
    name: str,
    args: dict,
    *,
    registry: SkillRegistry,
    active_skill_text: list[str],
    active_skill_ids: list[str],
    disabled_skill_ids: frozenset[str] | None = None,
) -> tuple[str, bool, str | None]:
    """
    执行 Skill 控制类工具。
    返回 (tool_result_text, should_terminate, final_user_message)。
    should_terminate 为 True 且 final_user_message 非空时表示正常结束。
    """
    if name == "select_skill":
        logger.debug(f"select_skill: {args}")
        sid = normalize_skill_id(str(args.get("skill_id", "")))
        if sid in active_skill_ids:
            i = active_skill_ids.index(sid)
            return (active_skill_text[i], False, None)
        if disabled_skill_ids is not None and sid in disabled_skill_ids:
            return (
                f"错误: Skill「{sid}」已在设置中禁用，无法加载到会话。请在界面设置中重新启用后再试。",
                False,
                None,
            )
        s = registry.get(sid)
        if s is None:
            return (f"错误: 未找到 skill_id={sid!r}。请从系统提示的列表中选择有效 id。", False, None)
        doc = format_skill_for_prompt(s)
        active_skill_text.append(doc)
        active_skill_ids.append(sid)
        return (doc, False, None)

    if name == "finish":
        msg = str(args.get("message", "")).strip()
        logger.debug(f"finish: message 原始值={args.get('message', '')!r}, strip 后={msg!r}")
        if not msg:
            return ("错误：finish 的 message 参数不能为空。你必须先通过正常文本输出完整回复内容，然后再调用 finish(message='你的完整回复') 结束任务。请重新输出回复。", False, None)
        return (msg, True, msg)

    if name == "ask_user":
        q = str(args.get("question", "")).strip()
        if not q:
            return ("错误：ask_user 需要提供非空的 question。", False, None)
        lines: list[str] = ["【向你确认】", "", q]
        ctx = str(args.get("context", "")).strip()
        if ctx:
            lines.extend(["", f"说明：{ctx}"])
        raw_choices = args.get("choices")
        if isinstance(raw_choices, list) and raw_choices:
            lines.extend(["", "可选回复（可照抄其中一条，或自由回答）："])
            for i, c in enumerate(raw_choices, 1):
                if c is None:
                    continue
                s = str(c).strip()
                if s:
                    lines.append(f"{i}. {s}")
        lines.extend(
            [
                "",
                "（本回合已暂停：请在下一条消息中直接回复；收到后 Agent 会从当前进度继续。）",
            ]
        )
        return ("\n".join(lines), False, None)

    if name == "load_skill_memory":
        sid = normalize_skill_id(str(args.get("skill_id", "")))
        query = args.get("query")
        if query is not None:
            query = str(query).strip()
            if not query:
                query = None
        s = registry.get(sid)
        if s is None:
            return (f"错误: 未找到 skill_id={sid!r}。", False, None)
        load_skill_memory_lazy(s, registry, query=query)
        if s.memory_content and s.memory_content.strip():
            return (
                f"### Skill「{sid}」执行经验\n\n{s.memory_content.strip()}\n\n请参考以上经验，避免重复之前的错误。",
                False,
                None,
            )
        return (f"Skill「{sid}」暂无执行经验记录。", False, None)

    return (f"未知 Skill 控制工具: {name}", False, None)
