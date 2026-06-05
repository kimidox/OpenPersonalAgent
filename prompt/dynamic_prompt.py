from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Final, Optional

from .template import (
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
    DEFAULT_TEMPLATE_MAP,
    EMPTY_PLACEHOLDER_VALUES,
    PLACEHOLDER_NAMES,
    PlaceholderName,
    ConversationType,
    CONVERSATION_TYPES,
    UPLOADED_FILES_SECTION_TEMPLATE,
)


@dataclass
class DynamicSystemPrompt:
    _template: str = field(default=DEFAULT_SYSTEM_PROMPT_TEMPLATE)
    _placeholders: dict[str, str] = field(default_factory=dict)
    _conversation_type: str = field(default=ConversationType.AGENT_CONVERSATION.value)
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
    def conversation_type(self) -> str:
        with self._lock:
            return self._conversation_type

    @conversation_type.setter
    def conversation_type(self, value: str) -> None:
        with self._lock:
            if value not in CONVERSATION_TYPES:
                raise ValueError(f"Unknown conversation type: {value}. Valid types: {CONVERSATION_TYPES}")
            self._conversation_type = value

    @property
    def placeholders(self) -> dict[str, str]:
        with self._lock:
            return dict(self._placeholders)

    def __post_init__(self) -> None:
        self._placeholders = dict(EMPTY_PLACEHOLDER_VALUES)
        # 根据 conversation_type 加载对应的模板
        if self._conversation_type in CONVERSATION_TYPES:
            self._template = DEFAULT_TEMPLATE_MAP.get(self._conversation_type, DEFAULT_SYSTEM_PROMPT_TEMPLATE)

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

    def set_template_for_conversation_type(self, conversation_type: str) -> None:
        """
        根据会话类型设置模板

        Args:
            conversation_type: 会话类型
        """
        if conversation_type not in CONVERSATION_TYPES:
            raise ValueError(f"Unknown conversation type: {conversation_type}. Valid types: {CONVERSATION_TYPES}")

        with self._lock:
            self._conversation_type = conversation_type
            # 从配置文件加载模板，如果不存在则使用默认模板
            try:
                from prompt_template_config import get_template_for_conversation_type
                self._template = get_template_for_conversation_type(conversation_type)
            except Exception:
                # 如果加载失败，使用默认模板
                self._template = DEFAULT_TEMPLATE_MAP.get(conversation_type, DEFAULT_SYSTEM_PROMPT_TEMPLATE)

    def preview_with_sample_data(self) -> str:
        """
        使用示例数据预览模板填充后的效果

        Returns:
            str: 填充后的模板示例
        """
        with self._lock:
            sample_data = {
                PlaceholderName.BASE_INFO.value: "用户名：示例用户\n当前系统时间：2024-01-01 12:00:00",
                PlaceholderName.SKILL_CATALOG.value: "## 可用 Skill 目录\n- Skill 1: 示例技能",
                PlaceholderName.TOOL_CATALOG.value: "## 可用工具目录\n- Tool 1: 示例工具",
                PlaceholderName.ACTIVE_SKILLS.value: "## 当前已加载的 Skill\n已加载 Skill 1",
                PlaceholderName.UPLOADED_FILES.value: "## 用户上传的文件\n示例文件内容",
                PlaceholderName.USER_MEMORY.value: "## 用户长期记忆\n示例记忆内容",
                PlaceholderName.RECENT_MEMORY_SUMMARY.value: "## 近期记忆摘要\n示例摘要",
                PlaceholderName.CONVERSATION_CONSTRAINTS.value: "## 本次对话约束\n示例约束",
            }

            result = self._template
            for name in PLACEHOLDER_NAMES:
                placeholder_tag = f"{{{name}}}"
                value = sample_data.get(name, "")
                result = result.replace(placeholder_tag, value)
            return result.strip()

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

    def update_uploaded_files(self, files_content: str) -> None:
        if files_content and files_content.strip():
            section = UPLOADED_FILES_SECTION_TEMPLATE.format(files_content=files_content)
            self.update_placeholder(PlaceholderName.UPLOADED_FILES.value, section)
        else:
            self.clear_placeholder(PlaceholderName.UPLOADED_FILES.value)

    def clear_uploaded_files(self) -> None:
        self.clear_placeholder(PlaceholderName.UPLOADED_FILES.value)

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
                _conversation_type=self._conversation_type,
            )
            return new_instance

    def __repr__(self) -> str:
        with self._lock:
            return f"DynamicSystemPrompt(conversation_type={self._conversation_type}, placeholders={list(self._placeholders.keys())})"
