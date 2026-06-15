from __future__ import annotations

from .execution import SKILL_CONTROL_TOOL_DEFINITIONS, execute_skill_control_tool
from .loader import (
    discover_skill_files,
    load_all_skills,
    load_skill_from_path,
    resolve_skill_markdown_in_package,
)
from .processing import (
    build_skills_catalog_text,
    format_skill_for_prompt,
    normalize_skill_id,
    skills_auto_matched_for_query,
    user_query_matches_skill_description,
)
from .registry import SkillRegistry
from .types import SkillDefinition
from .skill_manager import SkillManager, SkillMetadata, SkillData, get_manager

__all__ = [
    "SkillDefinition",
    "SkillRegistry",
    "load_skill_from_path",
    "load_all_skills",
    "discover_skill_files",
    "resolve_skill_markdown_in_package",
    "build_skills_catalog_text",
    "format_skill_for_prompt",
    "normalize_skill_id",
    "skills_auto_matched_for_query",
    "user_query_matches_skill_description",
    "SKILL_CONTROL_TOOL_DEFINITIONS",
    "execute_skill_control_tool",
    # Markdown格式Skill管理
    "SkillManager",
    "SkillMetadata",
    "SkillData",
    "get_manager",
]
