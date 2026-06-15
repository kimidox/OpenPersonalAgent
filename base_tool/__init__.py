from __future__ import annotations

from .context import ToolContext
from .definitions import (
    ATOMIC_TOOL_DEFINITIONS,
    CONTROL_TOOL_DEFINITIONS,
    REQUEST_TOOL_DETAILS_DEFINITION,
    TOOL_CATALOG,
    get_all_tool_definitions_from_registry,
)
from .dispatch import (
    execute_atomic_tool,
    check_skill_dependencies,
    install_skill_dependencies,
    splice_skill_path,
)
from .schema import tools_for_model
from .registry import ToolRegistry, get_tool_registry
from .decorators import (
    ToolMetadata,
    extract_parameters_from_func,
    atomic_tool,
    control_tool,
)


def all_definition_dicts() -> list[dict]:
    """供 Skill 侧与 Agent 侧合并工具 schema 时使用的原子工具定义（canonical）。"""
    return list(ATOMIC_TOOL_DEFINITIONS)


__all__ = [
    "ToolContext",
    "ATOMIC_TOOL_DEFINITIONS",
    "CONTROL_TOOL_DEFINITIONS",
    "REQUEST_TOOL_DETAILS_DEFINITION",
    "TOOL_CATALOG",
    "get_all_tool_definitions_from_registry",
    "execute_atomic_tool",
    "tools_for_model",
    "all_definition_dicts",
    "check_skill_dependencies",
    "install_skill_dependencies",
    "splice_skill_path",
    "ToolRegistry",
    "ToolMetadata",
    "get_tool_registry",
    "extract_parameters_from_func",
    "atomic_tool",
    "control_tool",
]