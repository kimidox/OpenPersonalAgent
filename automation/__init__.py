"""
UI Automation 模块

基于 Windows UI Automation API 的桌面自动化功能。
提供 Accessibility Tree 解析、元素查找、动作执行等能力。
包含失败计数、幻觉检测、状态验证等安全机制。
新增：内置工具注册、图片模板匹配

Skill执行引擎已移除，改为Markdown语义化编辑方案。
"""

from .uia_client import UIAClient
from .accessibility_tree import AccessibilityTreeParser, UIElementInfo
from .element_finder import ElementFinder
from .action_executor import ActionExecutor
from .task_controller import TaskController, FailureCounter, TaskTimer, get_controller, reset_controller
from .success_rate_tracker import SuccessRateTracker, get_tracker
from .builtin_tools import (
    BuiltinToolRegistry,
    get_registry,
    get_all_builtin_tools,
    generate_tool_reference_template,
    generate_all_tool_reference_templates,
    get_tools_markdown_catalog,
)
from .template_matcher import TemplateManager, TemplateMatcher, get_template_manager, get_template_matcher

__all__ = [
    "UIAClient",
    "AccessibilityTreeParser",
    "UIElementInfo",
    "ElementFinder",
    "ActionExecutor",
    "TaskController",
    "FailureCounter",
    "TaskTimer",
    "get_controller",
    "reset_controller",
    "SuccessRateTracker",
    "get_tracker",
    # 内置工具
    "BuiltinToolRegistry",
    "get_registry",
    "get_all_builtin_tools",
    "generate_tool_reference_template",
    "generate_all_tool_reference_templates",
    "get_tools_markdown_catalog",
    # 图片模板匹配
    "TemplateManager",
    "TemplateMatcher",
    "get_template_manager",
    "get_template_matcher",
]