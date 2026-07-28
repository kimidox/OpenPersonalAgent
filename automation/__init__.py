"""
UI Automation 模块

基于 Windows UI Automation API 的桌面自动化功能。
提供 Accessibility Tree 解析、元素查找、动作执行等能力。
包含失败计数、幻觉检测、状态验证等安全机制。
新增：内置工具注册、图片模板匹配

Skill执行引擎已移除，改为Markdown语义化编辑方案。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅供静态分析/IDE 跳转，运行时不执行（运行时由下方 __getattr__ 懒加载）
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

# 符号名 -> 子模块映射（PEP 562 懒加载：避免启动时同步加载 template_matcher 的
# cv2/numpy/pyautogui 等重依赖，首次访问符号时才导入对应子模块）
_SYMBOL_TO_MODULE = {
    "UIAClient": ".uia_client",
    "AccessibilityTreeParser": ".accessibility_tree",
    "UIElementInfo": ".accessibility_tree",
    "ElementFinder": ".element_finder",
    "ActionExecutor": ".action_executor",
    "TaskController": ".task_controller",
    "FailureCounter": ".task_controller",
    "TaskTimer": ".task_controller",
    "get_controller": ".task_controller",
    "reset_controller": ".task_controller",
    "SuccessRateTracker": ".success_rate_tracker",
    "get_tracker": ".success_rate_tracker",
    # 内置工具
    "BuiltinToolRegistry": ".builtin_tools",
    "get_registry": ".builtin_tools",
    "get_all_builtin_tools": ".builtin_tools",
    "generate_tool_reference_template": ".builtin_tools",
    "generate_all_tool_reference_templates": ".builtin_tools",
    "get_tools_markdown_catalog": ".builtin_tools",
    # 图片模板匹配
    "TemplateManager": ".template_matcher",
    "TemplateMatcher": ".template_matcher",
    "get_template_manager": ".template_matcher",
    "get_template_matcher": ".template_matcher",
}


def __getattr__(name: str):
    """PEP 562 模块级懒加载：首次访问符号时才导入对应子模块。"""
    module_rel = _SYMBOL_TO_MODULE.get(name)
    if module_rel is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_rel, __name__)
    value = getattr(module, name)
    # 缓存到模块全局，后续访问不再触发 __getattr__
    globals()[name] = value
    return value


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