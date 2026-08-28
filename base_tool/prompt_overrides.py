from __future__ import annotations

"""
【工具提示词覆盖层模块】

将工具描述（description）从代码外部化到用户数据目录，
支持用户或 Agent 直接编辑 .md 文件实现提示词自优化。

覆盖文件位置:
    %APPDATA%/OpenPersonalAgent/PersonalData/prompts/tools/{tool_name}.md
    （可通过环境变量 PERSONAL_DATA_DIR 重定向，见 resource_path.py）

文件约定:
    1. 文件首部的 <!-- --> 注释块仅作说明，加载时自动剥离，不进入提示词
    2. 剥离注释后的正文即该工具的完整 description
    3. 正文第一行将作为「工具目录」中的简要描述（与内置默认行为一致）
    4. 删除文件即可恢复内置默认描述
    5. 文件为空或解析失败时自动回退内置默认值，不影响启动

快照与回滚:
    每次通过 save_tool_override() 保存修改前，会将当前版本快照为
    同目录下的 {tool_name}.md.bak（保存上一次修改前的内容）。
    rollback_tool_override() 可将 .bak 恢复为当前版本。
    .bak 文件不会被 load_tool_overrides() 加载（仅匹配 *.md）。
    reset_tool_override() 重置前同样会快照当前版本，重置后仍可通过
    rollback 找回用户的自定义版本。

覆盖边界（安全约束）:
    仅覆盖 description 文案；参数 schema（parameters）与工具实现由代码维护，
    覆盖文件无法修改，防止 Agent 自优化破坏工具契约。

加载时机:
    definitions.py 模块导入末尾自动调用 apply_tool_overrides()。
    修改覆盖文件后需重启后端进程，或显式再次调用 apply_tool_overrides()
    （注意：ToolRegistry 单例在首次构建时快照了描述，重建注册表需
    reset_tool_registry() 后重新触发加载）。
"""

import logging
from pathlib import Path
from typing import Optional

from resource_path import paths

logger = logging.getLogger(__name__)

# 覆盖文件首部的说明注释模板（加载时剥离）
_OVERRIDE_HEADER_TEMPLATE = """<!--
  工具描述覆盖文件: {tool_name}
  本文件正文将替换该工具在 LLM 请求中的 description（参数 schema 由代码维护，不可覆盖）。
  约定:
  1. 本注释块之外的正文即完整 description
  2. 正文第一行将作为「工具目录」中的简要描述
  3. 删除本文件即可恢复内置默认描述
  4. 修改后需重启后端生效
-->
"""


def get_tool_prompts_dir() -> Path:
    """
    获取工具描述覆盖文件目录。

    Returns:
        Path: PersonalData/prompts/tools/ 目录（不主动创建，由导出逻辑按需创建）。
    """
    return paths.personal_data_dir / "prompts" / "tools"


def _strip_header_comments(text: str) -> str:
    """
    剥离覆盖文件首部的 <!-- --> 注释块及首尾空白。

    Args:
        text: 覆盖文件的原始内容。

    Returns:
        str: 剥离后的正文；若正文为空则返回空字符串。
    """
    stripped = text.lstrip()
    if stripped.startswith("<!--"):
        end = stripped.find("-->")
        if end != -1:
            stripped = stripped[end + 3:]
    return stripped.strip()


def load_tool_overrides() -> dict[str, str]:
    """
    加载所有工具描述覆盖文件。

    Returns:
        dict[str, str]: 工具名到新 description 的映射。
        目录不存在或文件为空时返回空 dict（即全量使用内置默认值）。
    """
    overrides: dict[str, str] = {}
    prompts_dir = get_tool_prompts_dir()
    if not prompts_dir.is_dir():
        return overrides

    for md_file in sorted(prompts_dir.glob("*.md")):
        tool_name = md_file.stem
        try:
            raw = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("读取工具描述覆盖文件失败，跳过 %s: %s", md_file, exc)
            continue
        content = _strip_header_comments(raw)
        if content:
            overrides[tool_name] = content
        else:
            logger.warning("工具描述覆盖文件内容为空，跳过 %s", md_file)
    return overrides


def _iter_all_tool_definitions() -> list[dict]:
    """收集所有可被覆盖的工具定义（补发工具 + 控制工具 + 原子工具）。"""
    from .definitions import (
        ATOMIC_TOOL_DEFINITIONS,
        CONTROL_TOOL_DEFINITIONS,
        REQUEST_TOOL_DETAILS_DEFINITION,
    )

    return [
        REQUEST_TOOL_DETAILS_DEFINITION,
        *CONTROL_TOOL_DEFINITIONS,
        *ATOMIC_TOOL_DEFINITIONS,
    ]


def _get_known_tools() -> dict[str, dict]:
    """返回工具名到工具定义的映射（用于覆盖校验与内存更新）。"""
    return {
        tool_def.get("name", ""): tool_def
        for tool_def in _iter_all_tool_definitions()
        if tool_def.get("name")
    }


def get_known_tool_names() -> list[str]:
    """
    获取所有支持描述覆盖的工具名。

    Returns:
        list[str]: 工具名列表（含补发工具、控制工具、原子工具）。
    """
    return list(_get_known_tools().keys())


def _apply_override_to_memory(tool_name: str, content: str) -> bool:
    """
    将覆盖内容应用到内存中的工具定义（含 TOOL_CATALOG 简要描述）。

    Args:
        tool_name: 工具名称。
        content: 新的 description 正文。

    Returns:
        bool: 工具是否已知并成功更新。
    """
    from .definitions import TOOL_CATALOG

    tool_def = _get_known_tools().get(tool_name)
    if tool_def is None:
        return False
    tool_def["description"] = content
    # 同步系统提示词中「工具目录」的简要描述（与内置行为一致：取正文第一行）
    if tool_name in TOOL_CATALOG:
        TOOL_CATALOG[tool_name] = content.split("\n")[0]
    return True


def export_default_tool_prompts() -> list[str]:
    """
    将内置默认工具描述导出为可编辑的 .md 覆盖文件。

    仅在目标文件不存在时写入（不覆盖用户已有修改）。

    Returns:
        list[str]: 本次导出的工具名列表。
    """
    exported: list[str] = []
    prompts_dir = get_tool_prompts_dir()
    prompts_dir.mkdir(parents=True, exist_ok=True)

    for tool_def in _iter_all_tool_definitions():
        tool_name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        if not tool_name or not description:
            continue
        target = prompts_dir / f"{tool_name}.md"
        if target.exists():
            continue
        try:
            header = _OVERRIDE_HEADER_TEMPLATE.format(tool_name=tool_name)
            target.write_text(header + "\n" + description + "\n", encoding="utf-8")
            exported.append(tool_name)
        except OSError as exc:
            logger.warning("导出工具描述覆盖文件失败 %s: %s", target, exc)
    return exported


# 内置默认描述快照（首次 apply 时捕获，供 reset_tool_override 恢复）
_default_description_snapshot: dict[str, str] | None = None


def _capture_default_snapshot(known_tools: dict[str, dict]) -> None:
    """捕获当前描述作为默认值快照（仅首次调用有效）。"""
    global _default_description_snapshot
    if _default_description_snapshot is not None:
        return
    _default_description_snapshot = {
        name: tool_def.get("description", "")
        for name, tool_def in known_tools.items()
    }


def apply_tool_overrides() -> dict:
    """
    加载覆盖文件并就地更新各工具定义的 description。

    就地修改 list/dict 中的字段，所有持有 definitions 模块级常量引用的
    消费方（BaseChatModel / stream_parser / dispatch / registry 等）自动生效。

    首次调用时若覆盖目录不存在，会先将内置默认描述导出为可编辑的
    .md 文件（文档化），再应用覆盖。

    Returns:
        dict: {"exported": [...], "applied": [...], "skipped": [...]}
            - exported: 首次导出的工具名列表
            - applied: 成功应用覆盖的工具名列表
            - skipped: 覆盖文件存在但工具未知的工具名列表
    """
    result: dict[str, list[str]] = {"exported": [], "applied": [], "skipped": []}

    try:
        if not get_tool_prompts_dir().is_dir():
            result["exported"] = export_default_tool_prompts()
    except Exception as exc:  # 导出失败不应阻断启动
        logger.warning("导出默认工具描述失败: %s", exc)

    known_tools = _get_known_tools()
    _capture_default_snapshot(known_tools)

    overrides = load_tool_overrides()
    for tool_name, content in overrides.items():
        if tool_name not in known_tools:
            logger.warning("工具描述覆盖文件指向未知工具，跳过: %s", tool_name)
            result["skipped"].append(tool_name)
            continue
        _apply_override_to_memory(tool_name, content)
        result["applied"].append(tool_name)

    if result["applied"]:
        logger.info("已应用工具描述覆盖: %s", ", ".join(result["applied"]))
    return result


def _snapshot_override_file(tool_name: str) -> bool:
    """
    将当前覆盖文件快照为 .bak（保存修改前的版本）。

    Args:
        tool_name: 工具名称。

    Returns:
        bool: 是否存在可快照的文件并成功复制。
    """
    import shutil

    target = get_tool_prompts_dir() / f"{tool_name}.md"
    if not target.is_file():
        return False
    try:
        shutil.copy2(target, target.with_name(f"{tool_name}.md.bak"))
        return True
    except OSError as exc:
        logger.warning("快照工具描述覆盖文件失败 %s: %s", target, exc)
        return False


def read_tool_override(tool_name: str) -> Optional[str]:
    """
    读取指定工具当前生效的 description（含覆盖与默认值回退）。

    Args:
        tool_name: 工具名称。

    Returns:
        Optional[str]: 当前生效的 description；工具未知时返回 None。
    """
    tool_def = _get_known_tools().get(tool_name)
    if tool_def is None:
        return None
    return tool_def.get("description", "")


def save_tool_override(tool_name: str, content: str) -> bool:
    """
    保存工具描述覆盖（写文件 + 立即更新内存中的定义）。

    保存前自动将当前版本快照为 {tool_name}.md.bak，可随时通过
    rollback_tool_override() 恢复。

    Args:
        tool_name: 工具名称（必须是已知工具）。
        content: 新的 description 正文（首行将作为工具目录简要描述）。

    Returns:
        bool: 是否保存成功。
    """
    if tool_name not in _get_known_tools():
        logger.warning("拒绝保存未知工具的描述覆盖: %s", tool_name)
        return False
    content = content.strip() if content else ""
    if not content:
        logger.warning("拒绝保存空的工具描述覆盖: %s", tool_name)
        return False

    prompts_dir = get_tool_prompts_dir()
    try:
        prompts_dir.mkdir(parents=True, exist_ok=True)
        _snapshot_override_file(tool_name)
        header = _OVERRIDE_HEADER_TEMPLATE.format(tool_name=tool_name)
        target = prompts_dir / f"{tool_name}.md"
        target.write_text(header + "\n" + content + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("保存工具描述覆盖失败 %s: %s", tool_name, exc)
        return False

    return _apply_override_to_memory(tool_name, content)


def rollback_tool_override(tool_name: str) -> bool:
    """
    将指定工具的描述回滚为上一次修改前的版本（.bak 快照）。

    Args:
        tool_name: 工具名称。

    Returns:
        bool: 是否回滚成功（无 .bak 快照时返回 False）。
    """
    import shutil

    prompts_dir = get_tool_prompts_dir()
    bak_file = prompts_dir / f"{tool_name}.md.bak"
    if not bak_file.is_file():
        return False

    try:
        shutil.copy2(bak_file, prompts_dir / f"{tool_name}.md")
    except OSError as exc:
        logger.warning("回滚工具描述覆盖失败 %s: %s", bak_file, exc)
        return False

    restored = _strip_header_comments(bak_file.read_text(encoding="utf-8"))
    if not restored:
        logger.warning("回滚快照内容为空，回退内置默认: %s", tool_name)
        restored = (_default_description_snapshot or {}).get(tool_name, "")
    return _apply_override_to_memory(tool_name, restored)


def list_tool_override_status() -> list[dict]:
    """
    列出所有工具的描述覆盖状态。

    Returns:
        list[dict]: 每项包含:
            - tool_name: 工具名
            - customized: 覆盖文件内容是否区别于内置默认值
            - has_backup: 是否存在可回滚的 .bak 快照
    """
    prompts_dir = get_tool_prompts_dir()
    statuses: list[dict] = []
    for tool_name in get_known_tool_names():
        md_file = prompts_dir / f"{tool_name}.md"
        customized = False
        if md_file.is_file():
            content = _strip_header_comments(md_file.read_text(encoding="utf-8"))
            default = (_default_description_snapshot or {}).get(tool_name)
            customized = bool(content) and content != default
        statuses.append({
            "tool_name": tool_name,
            "customized": customized,
            "has_backup": (prompts_dir / f"{tool_name}.md.bak").is_file(),
        })
    return statuses


def reset_tool_override(tool_name: str) -> bool:
    """
    重置指定工具的描述为内置默认值（重置前快照当前版本，删除覆盖文件并恢复内存描述）。

    Args:
        tool_name: 工具名称。

    Returns:
        bool: 是否成功重置。
    """
    tool_def = _get_known_tools().get(tool_name)
    if tool_def is None:
        return False

    # 重置前快照当前版本（若存在），便于通过 rollback 找回
    _snapshot_override_file(tool_name)

    # 删除覆盖文件（若存在）
    override_file = get_tool_prompts_dir() / f"{tool_name}.md"
    try:
        override_file.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("删除工具描述覆盖文件失败 %s: %s", override_file, exc)
        return False

    # 恢复内存中的默认描述
    if _default_description_snapshot and tool_name in _default_description_snapshot:
        tool_def["description"] = _default_description_snapshot[tool_name]
        from .definitions import TOOL_CATALOG

        if tool_name in TOOL_CATALOG:
            default_brief = _default_description_snapshot[tool_name].split("\n")[0]
            TOOL_CATALOG[tool_name] = default_brief
    return True
