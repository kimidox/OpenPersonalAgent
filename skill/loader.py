from __future__ import annotations

from pathlib import Path

from .types import SkillDefinition
import config


def _parse_simple_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """
    解析可选的 YAML 风格前置块（无 PyYAML 依赖）：以 --- 包裹的简单 key: value 行。
    """
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    meta_block = parts[1].strip()
    body = parts[2].lstrip("\n")
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def resolve_skill_markdown_in_package(package_dir: Path) -> Path | None:
    """
    在单个 Skill 包目录（一层子文件夹）内解析要加载的 Markdown 路径。
    优先级：
    1) 与同文件夹名一致的 `<文件夹名>.md` / `.markdown`
    2) 该目录下按文件名的第一个 `.md` / `.markdown`（仅当前目录，不递归子目录）
    """
    if not package_dir.is_dir():
        return None
    name = package_dir.name
    for ext in (".md", ".markdown"):
        preferred = package_dir / f"{name}{ext}"
        if preferred.is_file():
            return preferred
    md_files = sorted(
        (
            p
            for p in package_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".md", ".markdown")
        ),
        key=lambda p: p.name.lower(),
    )
    return md_files[0] if md_files else None


def resolve_skill_memory_path(skill_md_path: Path) -> Path | None:
    """
    获取 skill 主文档同目录下的 skill_memory.md 路径。

    参数：
        skill_md_path: skill 主文档路径

    返回：
        如果存在 skill_memory.md 则返回其路径，否则返回 None
    """
    memory_path = skill_md_path.parent / "skill_memory.md"
    if memory_path.is_file():
        return memory_path
    return None


def load_skill_memory(skill_md_path: Path) -> str | None:
    """
    读取 skill_memory.md 文件内容。

    参数：
        skill_md_path: skill 主文档路径

    返回：
        文件内容字符串，如果文件不存在则返回 None
    """
    memory_path = resolve_skill_memory_path(skill_md_path)
    if memory_path is None:
        return None
    try:
        return memory_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None


def load_skill_from_path(path: Path) -> SkillDefinition:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_simple_frontmatter(raw)
    skill_id = (meta.get("id") or meta.get("skill_id") or path.stem).strip()
    name = (meta.get("name") or skill_id).strip()
    description = (meta.get("description") or meta.get("desc") or "").strip()
    extra = {k: v for k, v in meta.items() if k not in ("id", "skill_id", "name", "description", "desc")}
    try:
        relative = path.relative_to(Path(config.WORKER_DIR).resolve())
        relative_path = relative
    except ValueError:
        try:
            relative = path.relative_to(Path.cwd())
            relative_path = Path(*relative.parts[1:]) if len(relative.parts) > 1 else relative
        except ValueError:
            relative_path = path.name

    memory_content = load_skill_memory(path)

    return SkillDefinition(
        skill_id=skill_id,
        name=name,
        description=description,
        body=body.strip(),
        relative_path=relative_path,
        extra_meta=extra,
        memory_content=memory_content,
    )


def discover_skill_files(skills_dir: Path) -> list[Path]:
    """
    扫描 Skills 根目录：
    - 每个**一级子文件夹**视为一个 Skill 包，在其中解析主 .md（见 resolve_skill_markdown_in_package）；
    - 若根目录下仍有独立的 .md / .markdown / .txt，也会加载（兼容旧版平铺结构）。
    """
    if not skills_dir.is_dir():
        return []
    paths: list[Path] = []
    for child in sorted(skills_dir.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            md = resolve_skill_markdown_in_package(child)
            if md is not None:
                paths.append(md)
        elif child.is_file() and child.suffix.lower() in (".md", ".markdown", ".txt"):
            paths.append(child)
    return paths


def load_all_skills(skills_dir: Path) -> list[SkillDefinition]:
    return [load_skill_from_path(p) for p in discover_skill_files(skills_dir)]
