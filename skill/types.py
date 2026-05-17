from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillDefinition:
    """磁盘上的 Skill 文档解析结果。"""

    skill_id: str
    name: str
    description: str
    body: str
    relative_path: Path | None = None
    extra_meta: dict[str, str] = field(default_factory=dict)
    memory_content: str | None = None
    memory_loaded: bool = False
