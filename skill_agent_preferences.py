from __future__ import annotations

import json
from pathlib import Path

from resource_path import paths


def _get_state_path() -> Path:
    if paths.is_frozen:
        return paths.user_data_dir / "skill_agent_disabled_skills.json"
    return paths.project_root / "skill_agent_disabled_skills.json"


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
