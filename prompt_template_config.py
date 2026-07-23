"""
系统提示词模板配置管理模块

管理三种会话类型的系统提示词模板配置：
- 智能体会话 (agent_conversation)
- 聊天会话 (human_chat_conversation)
- 录音会话 (record_conversation)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from prompt.template import (
    DEFAULT_TEMPLATE_MAP,
    PLACEHOLDER_NAMES,
    ConversationType,
    CONVERSATION_TYPES,
)
from resource_path import paths


def get_template_config_path() -> Path:
    """
    获取模板配置文件路径
    开发: PersonalData/config/prompt_templates.json
    打包: %APPDATA%/OpenPersonalAgent/PersonalData/config/prompt_templates.json
    """
    return paths.get_user_config_path("prompt_templates.json")


def load_template_config() -> dict[str, str]:
    """
    加载模板配置文件

    Returns:
        dict[str, str]: 会话类型到模板内容的映射
    """
    config_path = get_template_config_path()

    if not config_path.is_file():
        # 如果配置文件不存在，返回默认模板
        return dict(DEFAULT_TEMPLATE_MAP)

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 如果读取失败，返回默认模板
        return dict(DEFAULT_TEMPLATE_MAP)

    templates = raw.get("templates")
    if not isinstance(templates, dict):
        # 如果格式不正确，返回默认模板
        return dict(DEFAULT_TEMPLATE_MAP)

    # 验证并过滤模板
    result = {}
    for conv_type, template_content in templates.items():
        if conv_type in CONVERSATION_TYPES and isinstance(template_content, str):
            result[conv_type] = template_content

    # 如果某些会话类型缺失，使用默认模板补充
    for conv_type in CONVERSATION_TYPES:
        if conv_type not in result:
            result[conv_type] = DEFAULT_TEMPLATE_MAP.get(conv_type, "")

    return result


def save_template_config(templates: dict[str, str]) -> None:
    """
    保存模板配置到文件

    Args:
        templates: 会话类型到模板内容的映射
    """
    config_path = get_template_config_path()

    # 验证模板
    validated_templates = {}
    for conv_type, template_content in templates.items():
        if conv_type in CONVERSATION_TYPES and isinstance(template_content, str):
            # 验证模板中的占位符
            is_valid, invalid_placeholders = validate_template(template_content)
            if is_valid:
                validated_templates[conv_type] = template_content
            else:
                # 如果模板无效，使用默认模板
                validated_templates[conv_type] = DEFAULT_TEMPLATE_MAP.get(conv_type, "")

    # 补充缺失的会话类型
    for conv_type in CONVERSATION_TYPES:
        if conv_type not in validated_templates:
            validated_templates[conv_type] = DEFAULT_TEMPLATE_MAP.get(conv_type, "")

    data = {
        "templates": validated_templates,
        "version": "1.0",
        "description": "系统提示词模板配置文件"
    }

    text = json.dumps(data, ensure_ascii=False, indent=2)
    config_path.write_text(text + "\n", encoding="utf-8")


def get_template_for_conversation_type(conversation_type: str) -> str:
    """
    获取指定会话类型的模板

    Args:
        conversation_type: 会话类型

    Returns:
        str: 模板内容
    """
    templates = load_template_config()
    return templates.get(conversation_type, DEFAULT_TEMPLATE_MAP.get(conversation_type, ""))


def update_template_for_conversation_type(conversation_type: str, template: str) -> None:
    """
    更新指定会话类型的模板

    Args:
        conversation_type: 会话类型
        template: 新的模板内容
    """
    templates = load_template_config()
    templates[conversation_type] = template
    save_template_config(templates)


def reset_template_for_conversation_type(conversation_type: str) -> None:
    """
    重置指定会话类型的模板为默认模板

    Args:
        conversation_type: 会话类型
    """
    templates = load_template_config()
    templates[conversation_type] = DEFAULT_TEMPLATE_MAP.get(conversation_type, "")
    save_template_config(templates)


def reset_all_templates() -> None:
    """
    重置所有会话类型的模板为默认模板
    """
    save_template_config(dict(DEFAULT_TEMPLATE_MAP))


def validate_template(template: str) -> tuple[bool, list[str]]:
    """
    验证模板中的占位符是否有效

    Args:
        template: 模板内容

    Returns:
        tuple[bool, list[str]]: (是否有效, 无效的占位符列表)
    """
    # 提取模板中的占位符
    placeholder_pattern = re.compile(r"\{([A-Z_]+)\}")
    found_placeholders = placeholder_pattern.findall(template)

    # 检查占位符是否有效
    invalid_placeholders = []
    for placeholder in found_placeholders:
        if placeholder not in PLACEHOLDER_NAMES:
            invalid_placeholders.append(placeholder)

    return len(invalid_placeholders) == 0, invalid_placeholders


def get_placeholder_description(placeholder_name: str) -> str:
    """
    获取占位符的描述说明

    Args:
        placeholder_name: 占位符名称

    Returns:
        str: 占位符描述
    """
    descriptions = {
        "BASE_INFO": "基本信息（用户名、当前时间等）",
        "SKILL_CATALOG": "可用的 Skill 目录",
        "TOOL_CATALOG": "可用的工具目录",
        "ACTIVE_SKILLS": "当前已加载的 Skill",
        "UPLOADED_FILES": "用户上传的文件内容",
        "CONVERSATION_CONSTRAINTS": "本次对话约束",
    }
    return descriptions.get(placeholder_name, f"未知占位符: {placeholder_name}")


def get_all_placeholder_descriptions() -> dict[str, str]:
    """
    获取所有占位符的描述说明

    Returns:
        dict[str, str]: 占位符名称到描述的映射
    """
    return {
        placeholder: get_placeholder_description(placeholder)
        for placeholder in PLACEHOLDER_NAMES
    }


def get_conversation_type_display_name(conversation_type: str) -> str:
    """
    获取会话类型的显示名称

    Args:
        conversation_type: 会话类型

    Returns:
        str: 显示名称
    """
    display_names = {
        ConversationType.AGENT_CONVERSATION.value: "智能体会话",
        ConversationType.CHAT_CONVERSATION.value: "聊天会话",
        ConversationType.RECORD_CONVERSATION.value: "录音会话",
    }
    return display_names.get(conversation_type, conversation_type)


def get_all_conversation_types_with_display_names() -> dict[str, str]:
    """
    获取所有会话类型及其显示名称

    Returns:
        dict[str, str]: 会话类型到显示名称的映射
    """
    return {
        conv_type: get_conversation_type_display_name(conv_type)
        for conv_type in CONVERSATION_TYPES
    }