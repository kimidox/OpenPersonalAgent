from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Final, Optional

from .template import (
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    EMPTY_PLACEHOLDER_VALUES,
    PLACEHOLDER_NAMES,
    PlaceholderName,
)


@dataclass
class DynamicSystemPrompt:
    _template: str = field(default=DEFAULT_SYSTEM_PROMPT_TEMPLATE)
    _placeholders: dict[str, str] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\{([A-Z_]+)\}")

    @property
    def template(self) -> str:
        with self._lock:
            return self._template

    @template.setter
    def template(self, value: str) -> None:
        with self._lock:
            self._template = value

    @property
    def placeholders(self) -> dict[str, str]:
        with self._lock:
            return dict(self._placeholders)

    def __post_init__(self) -> None:
        self._placeholders = dict(EMPTY_PLACEHOLDER_VALUES)

    def update_placeholder(self, name: str, value: str) -> None:
        if name not in PLACEHOLDER_NAMES:
            raise ValueError(f"Unknown placeholder name: {name}. Valid names: {PLACEHOLDER_NAMES}")
        with self._lock:
            self._placeholders[name] = value

    def clear_placeholder(self, name: str) -> None:
        if name not in PLACEHOLDER_NAMES:
            raise ValueError(f"Unknown placeholder name: {name}. Valid names: {PLACEHOLDER_NAMES}")
        with self._lock:
            self._placeholders[name] = EMPTY_PLACEHOLDER_VALUES.get(name, "")

    def clear_all_placeholders(self) -> None:
        with self._lock:
            self._placeholders = dict(EMPTY_PLACEHOLDER_VALUES)

    def get_placeholder(self, name: str) -> Optional[str]:
        if name not in PLACEHOLDER_NAMES:
            raise ValueError(f"Unknown placeholder name: {name}. Valid names: {PLACEHOLDER_NAMES}")
        with self._lock:
            return self._placeholders.get(name)
    def update_base_info(self, base_info: str) -> None:
        self.update_placeholder(PlaceholderName.BASE_INFO.value, base_info)
    def update_skill_catalog(self, catalog: str) -> None:
        self.update_placeholder(PlaceholderName.SKILL_CATALOG.value, catalog)

    def update_active_skills(self, skills: str) -> None:
        self.update_placeholder(PlaceholderName.ACTIVE_SKILLS.value, skills)

    def update_user_memory(self, memory: str) -> None:
        self.update_placeholder(PlaceholderName.USER_MEMORY.value, memory)

    def update_conversation_constraints(self, constraints: str) -> None:
        self.update_placeholder(PlaceholderName.CONVERSATION_CONSTRAINTS.value, constraints)

    def update_recent_memory_summary(self, summary: str) -> None:
        self.update_placeholder(PlaceholderName.RECENT_MEMORY_SUMMARY.value, summary)

    def update_tool_catalog(self, catalog: str) -> None:
        self.update_placeholder(PlaceholderName.TOOL_CATALOG.value, catalog)

    def clear_active_skills(self) -> None:
        self.clear_placeholder(PlaceholderName.ACTIVE_SKILLS.value)

    def clear_user_memory(self) -> None:
        self.clear_placeholder(PlaceholderName.USER_MEMORY.value)

    def clear_conversation_constraints(self) -> None:
        self.clear_placeholder(PlaceholderName.CONVERSATION_CONSTRAINTS.value)

    def clear_recent_memory_summary(self) -> None:
        self.clear_placeholder(PlaceholderName.RECENT_MEMORY_SUMMARY.value)

    def build(self) -> str:
        with self._lock:
            result = self._template
            for name in PLACEHOLDER_NAMES:
                placeholder_tag = f"{{{name}}}"
                value = self._placeholders.get(name, "")
                result = result.replace(placeholder_tag, value)
            return result.strip()

    def extract_placeholders_from_template(self) -> list[str]:
        matches = self.PLACEHOLDER_PATTERN.findall(self._template)
        return list(set(matches))

    def validate_template(self) -> tuple[bool, list[str]]:
        found = self.extract_placeholders_from_template()
        unknown = [p for p in found if p not in PLACEHOLDER_NAMES]
        return len(unknown) == 0, unknown

    def batch_update(self, updates: dict[str, str]) -> None:
        with self._lock:
            for name, value in updates.items():
                if name not in PLACEHOLDER_NAMES:
                    raise ValueError(f"Unknown placeholder name: {name}. Valid names: {PLACEHOLDER_NAMES}")
                self._placeholders[name] = value

    def copy(self) -> "DynamicSystemPrompt":
        with self._lock:
            new_instance = DynamicSystemPrompt(
                _template=self._template,
                _placeholders=dict(self._placeholders),
            )
            return new_instance

    def __repr__(self) -> str:
        with self._lock:
            return f"DynamicSystemPrompt(placeholders={list(self._placeholders.keys())})"
