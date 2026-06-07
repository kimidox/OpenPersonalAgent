"""
UI Automation 模块

基于 Windows UI Automation API 的桌面自动化功能。
提供 Accessibility Tree 解析、元素查找、动作执行等能力。
"""

from .uia_client import UIAClient
from .accessibility_tree import AccessibilityTreeParser, UIElementInfo
from .element_finder import ElementFinder
from .action_executor import ActionExecutor

__all__ = [
    "UIAClient",
    "AccessibilityTreeParser",
    "UIElementInfo",
    "ElementFinder",
    "ActionExecutor",
]