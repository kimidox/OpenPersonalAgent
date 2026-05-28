from __future__ import annotations

import re

from .types import SkillDefinition


def normalize_skill_id(skill_id: str) -> str:
    return (skill_id or "").strip()


def summarize_skill(s: SkillDefinition) -> str:
    desc = s.description or "(无描述)"
    type_tag = "[系统内置]" if s.skill_type == "builtin" else "[用户]"
    res=f"""
<Skill>
<type>{type_tag}</type>
<id>{s.skill_id}</id>
<name>{s.name}</name>
<desc>{desc}</desc>
<dir>{s.relative_path}</dir>
</Skill>
"""
    return res


def build_skills_catalog_text(skills: list[SkillDefinition]) -> str:
    if not skills:
        return (
            "（当前 Skills 目录下没有可用 Skill；请在 skill/Skills/ 下为每个 Skill 建一级子文件夹，"
            "并在其中放置与文件夹同名的 .md，或任意一个 .md 作为主文档。）"
        )
    lines = [summarize_skill(s) for s in skills]
    lines_str= f"""<Skills>{"".join(lines)}</Skills>"""
    return "可用 Skill 列表（如果当前用户行为满足触发条件，请先调用 select_skill 加载完整文档后再执行步骤）：\n" + "\n"+lines_str


def _trigger_segments_from_description_and_name(description: str, name: str) -> set[str]:
    """
    从 description、name 中抽出用于与用户问题做子串匹配的片段。
    - description / name 按 ，、。；;|/ 及换行等切分，每段长度 ≥2 即参与匹配；
    - name 单独作为一段（长度 ≥2）；
    - 若 description 切分后只有一段，整段 description 也参与（便于短句型描述）。
    """
    segs: set[str] = set()
    d = (description or "").strip().lower()
    n = (name or "").strip().lower()
    if len(n) >= 2:
        segs.add(n)
    if not d:
        return segs
    parts = [p.strip().lower() for p in re.split(r"[，,。、；;|/\n\r\t]+", d) if p.strip()]
    for t in parts:
        if len(t) >= 2:
            segs.add(t)
    if len(parts) <= 1 and len(d) >= 2:
        segs.add(d)
    return segs


def user_query_matches_skill_description(user_query: str, description: str, name: str) -> bool:
    """用户问题（小写）是否包含 description/name 派生的任一触发片段。"""
    q = (user_query or "").strip().lower()
    if len(q) < 1:
        return False
    for seg in _trigger_segments_from_description_and_name(description, name):
        if seg and seg in q:
            return True
    return False


def skills_auto_matched_for_query(skills: list[SkillDefinition], user_query: str) -> list[SkillDefinition]:
    """
    根据 Skill 前置元数据选出「本回合应自动生效」的文档（无需模型先 select_skill）。
    - auto_load: always / true / global / 1 / yes / on → 每轮用户提问都加载
    - 否则：用 **description**（及 name）切分出的片段与用户问题做子串匹配，任一片段命中即加载；
      建议在 description 里用 、或 ， 写多个触发短语（如：「你是谁、你叫什么、姓名」）。
    顺序：先所有 always，再按文件顺序追加 description 命中的 Skill（去重 skill_id）。
    """
    q = (user_query or "").strip().lower()
    ordered = sorted(
        skills,
        key=lambda s: (str(s.relative_path or ""), normalize_skill_id(s.skill_id)),
    )
    seen: set[str] = set()
    always: list[SkillDefinition] = []
    keyed: list[SkillDefinition] = []

    for s in ordered:
        sid = normalize_skill_id(s.skill_id)
        if sid in seen:
            continue
        mode = (s.extra_meta.get("auto_load") or "").strip().lower()
        if mode in ("always", "true", "global", "1", "yes", "on"):
            always.append(s)
            seen.add(sid)

    for s in ordered:
        sid = normalize_skill_id(s.skill_id)
        if sid in seen:
            continue
        if not (s.description or "").strip() and not (s.name or "").strip():
            continue
        if user_query_matches_skill_description(q, s.description, s.name):
            keyed.append(s)
            seen.add(sid)

    return always + keyed


def format_skill_for_prompt(s: SkillDefinition) -> str:
    res=""
    header = f"# Skill: {s.name} (`{s.skill_id}`)\n"

    res+=header

    if s.description:
        res+= f"\n{s.description}\n\n"

    res += "---\n\n" + s.body

    # 追加执行记忆（如果存在且非空）
    if s.memory_content and s.memory_content.strip():
        res += "\n\n---\n## 执行记忆\n" + s.memory_content.strip()

    return res


