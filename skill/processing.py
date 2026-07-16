from __future__ import annotations

import re
from pathlib import Path

from .types import SkillDefinition

# 内联附属文件的大小上限（字节），避免一次内联过大文件
_INLINE_FILE_MAX_BYTES = 16 * 1024  # 16 KB

# 可内联的文件扩展名
_INLINEABLE_EXTS = (".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv")

# 匹配 SKILL.md 中「读取/加载/参考 <path>」等附属文件引用。
# 支持：读取`./example/x.md`、读取 'example/x.md'、读取附属文件 example/x.md、加载 "x.md"
_ATTACH_RE = re.compile(
    r"(?:读取附属文件|读取附属|读取|加载|参考|引用|引入)\s*"
    r"[`'\"]?\s*\.?/?([^\s`'\"\)\]]+\.(?:md|markdown|txt|json|yaml|yml|csv))\s*[`'\"]?",
    re.IGNORECASE,
)


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
            "当前 Skills 目录下没有可用 Skill"
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


def _collect_referenced_attach_paths(body: str) -> list[str]:
    """从 SKILL.md 正文中提取应被内联的附属文件相对路径。

    过滤掉明显是命令模板的反引号内容（如 scripts/xxx.py、session_id、title 等字段名）。
    仅保留 .md/.txt/.json/.yaml/.yml/.csv 等文档类文件。
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for m in _ATTACH_RE.finditer(body or ""):
        rel = m.group(1).strip().strip("'\"").lstrip("./").replace("\\", "/")
        # 排除 scripts/ 下的脚本（它们是命令模板，不是要读取的附属文件）
        if rel.startswith("scripts/"):
            continue
        # 排除 SKILL.md 自身
        if rel.lower() in ("skill.md", "skill_memory.md"):
            continue
        if rel.lower().endswith(_INLINEABLE_EXTS) and rel not in seen:
            seen.add(rel)
            ordered.append(rel)
    return ordered


def _inline_attach_files(skill: SkillDefinition) -> str:
    """读取并内联 SKILL.md 中引用的附属文件内容。

    返回附加到正文后的文本块；如果没有任何可内联文件，返回空字符串。
    """
    if not skill.relative_path:
        return ""

    try:
        import config
        skill_pkg_dir = Path(config.WORKER_DIR) / skill.relative_path.parent
    except Exception:
        return ""

    if not skill_pkg_dir.is_dir():
        return ""

    refs = _collect_referenced_attach_paths(skill.body or "")
    if not refs:
        return ""

    blocks: list[str] = []
    for rel in refs:
        target = (skill_pkg_dir / rel).resolve()
        # 安全检查：目标必须在 skill 包目录下
        try:
            target.relative_to(skill_pkg_dir.resolve())
        except ValueError:
            blocks.append(f"\n\n---\n⚠️ 引用的附属文件超出 skill 包范围，已忽略：`{rel}`")
            continue

        if not target.exists():
            blocks.append(f"\n\n---\n⚠️ 文档引用的附属文件不存在：`{rel}`（请勿再尝试读取该文件）")
            continue
        if not target.is_file():
            blocks.append(f"\n\n---\n⚠️ 引用的路径不是文件：`{rel}`")
            continue

        try:
            size = target.stat().st_size
        except OSError:
            continue

        if size > _INLINE_FILE_MAX_BYTES:
            blocks.append(
                f"\n\n---\n⚠️ 附属文件 `{rel}` 体积过大（{size} 字节），未自动内联。"
                f"如需读取，请用 file_operation(action=\"read\", path=\"{rel}\", skill_id=\"{skill.skill_id}\")"
            )
            continue

        try:
            content = target.read_text(encoding="utf-8", errors="replace").rstrip()
        except Exception as e:
            blocks.append(f"\n\n---\n⚠️ 读取附属文件 `{rel}` 失败：{e}")
            continue

        blocks.append(f"\n\n---\n## 附属文件：`{rel}`（已自动内联，无需再调用工具读取）\n\n{content}")

    return "".join(blocks)


def format_skill_for_prompt(s: SkillDefinition) -> str:
    res=""
    header = f"# Skill: {s.name} (`{s.skill_id}`)\n"

    res+=header

    if s.description:
        res+= f"\n{s.description}\n\n"

    res += "---\n\n" + s.body

    # 自动内联附属文件（避免 LLM 再发工具调用读取导致路径问题）
    inlined = _inline_attach_files(s)
    if inlined:
        res += inlined

    # 追加执行记忆（如果存在且非空）
    if s.memory_content and s.memory_content.strip():
        res += "\n\n---\n## 执行记忆\n" + s.memory_content.strip()

    return res


