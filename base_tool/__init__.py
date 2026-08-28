from __future__ import annotations

from .context import ToolContext
from .definitions import (
    ATOMIC_TOOL_DEFINITIONS,
    CONTROL_TOOL_DEFINITIONS,
    REQUEST_TOOL_DETAILS_DEFINITION,
    TOOL_CATALOG,
    get_all_tool_definitions_from_registry,
)
from .prompt_overrides import (
    apply_tool_overrides,
    export_default_tool_prompts,
    get_known_tool_names,
    get_tool_prompts_dir,
    list_tool_override_status,
    load_tool_overrides,
    read_tool_override,
    rollback_tool_override,
    reset_tool_override,
    save_tool_override,
)
from .dispatch import (
    execute_atomic_tool,
    check_skill_dependencies,
    install_skill_dependencies,
    install_skill_from_zip,
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
    "apply_tool_overrides",
    "export_default_tool_prompts",
    "get_known_tool_names",
    "get_tool_prompts_dir",
    "list_tool_override_status",
    "load_tool_overrides",
    "read_tool_override",
    "rollback_tool_override",
    "reset_tool_override",
    "save_tool_override",
    "execute_atomic_tool",
    "tools_for_model",
    "all_definition_dicts",
    "check_skill_dependencies",
    "install_skill_dependencies",
    "install_skill_from_zip",
    "splice_skill_path",
    "ToolRegistry",
    "ToolMetadata",
    "get_tool_registry",
    "extract_parameters_from_func",
    "atomic_tool",
    "control_tool",
]