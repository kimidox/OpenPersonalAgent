from __future__ import annotations

import json
from pathlib import Path

from resource_path import paths


def _get_state_path() -> Path:
    return paths.personal_data_dir / "skill_agent_disabled_skills.json"


_STATE_PATH = _get_state_path()


def load_disabled_skill_ids() -> set[str]:
    if not _STATE_PATH.is_file():
        return set()
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = raw.get("disabled_skill_ids")
    if not isinstance(ids, list):
        return set()
    return {str(x).strip() for x in ids if str(x).strip()}


def save_disabled_skill_ids(ids: set[str]) -> None:
    data = {"disabled_skill_ids": sorted(ids)}
    text = json.dumps(data, ensure_ascii=False, indent=2)
    _STATE_PATH.write_text(text + "\n", encoding="utf-8")


def _get_skill_bindings_path() -> Path:
    return paths.personal_data_dir / "skill_agent_skill_bindings.json"


_SKILL_BINDINGS_PATH = _get_skill_bindings_path()


def load_skill_bindings() -> dict[str, list[str]]:
    """加载会话类型 → 默认技能绑定（conversation_type -> [skill_id]）。"""
    if not _SKILL_BINDINGS_PATH.is_file():
        return {}
    try:
        raw = json.loads(_SKILL_BINDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    bindings = raw.get("skill_bindings")
    if not isinstance(bindings, dict):
        return {}
    result = {}
    for conv_type, skill_ids in bindings.items():
        if isinstance(conv_type, str) and isinstance(skill_ids, list):
            ct = conv_type.strip()
            if not ct:
                # 过滤持久化数据中残留的空会话类型
                continue
            result[ct] = [str(s).strip() for s in skill_ids if str(s).strip()]
    return result


def save_skill_bindings(bindings: dict[str, list[str]]) -> None:
    data = {"skill_bindings": bindings}
    text = json.dumps(data, ensure_ascii=False, indent=2)
    _SKILL_BINDINGS_PATH.write_text(text + "\n", encoding="utf-8")


def get_default_skills_for_type(conversation_type: str) -> list[str]:
    """获取指定会话类型默认启用的 skill_id 列表（剔除已禁用项）。"""
    bindings = load_skill_bindings()
    disabled = load_disabled_skill_ids()
    result = []
    for conv_type, skill_ids in bindings.items():
        if conv_type != conversation_type:
            continue
        for skill_id in skill_ids:
            if skill_id not in disabled:
                result.append(skill_id)
    return result
