"""
Accessibility Tree 解析器

解析 Windows UI Automation Tree，提供结构化的元素信息。
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from .uia_client import UIAClient, UIElementInfo, get_uia_client


class AccessibilityTreeParser:
    """Accessibility Tree 解析器"""

    def __init__(self, client: Optional[UIAClient] = None):
        """
        初始化解析器

        Args:
            client: UIA 客户端（None 则使用默认客户端）
        """
        self.client = client or get_uia_client()

    def parse_window(
        self,
        window_title: Optional[str] = None,
        process_id: Optional[int] = None,
        max_depth: int = 5,
        max_elements: int = 500,
    ) -> dict[str, Any]:
        """
        解析指定窗口的 Accessibility Tree

        Args:
            window_title: 窗口标题（部分匹配）
            process_id: 进程 ID
            max_depth: 最大遍历深度
            max_elements: 最大元素数量

        Returns:
            结构化的 Accessibility Tree（JSON 格式）
        """
        start_time = time.time()

        # 获取目标窗口
        if process_id:
            window_info = self.client.get_window_by_process_id(process_id)
        elif window_title:
            window_info = self.client.get_window_by_title(window_title)
        else:
            # 获取焦点窗口
            window_info = self.client.get_focused_window()

        if window_info is None:
            return {
                "success": False,
                "error": "未找到目标窗口",
                "window_title": window_title,
                "process_id": process_id,
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

        # 获取窗口元素对象
        try:
            import uiautomation as auto
            if process_id:
                window_element = auto.WindowControl(ProcessId=process_id, searchDepth=1)
            elif window_title:
                window_element = auto.WindowControl(Name=window_title, searchDepth=1)
            else:
                window_element = auto.GetFocusedControl()
                while window_element and window_element.ControlType != auto.ControlType.Window:
                    window_element = window_element.GetParentControl()
        except Exception as e:
            return {
                "success": False,
                "error": f"获取窗口元素失败: {e}",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

        # 构建完整树
        tree = self.client.get_element_tree(
            root_element=window_element,
            max_depth=max_depth,
            max_elements=max_elements,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "window": window_info.to_dict(),
            "tree": tree.to_dict(),
            "element_count": self._count_elements(tree),
            "max_depth": max_depth,
            "elapsed_ms": elapsed_ms,
        }

    def parse_desktop(self, max_depth: int = 2) -> dict[str, Any]:
        """
        解析桌面顶层元素

        Args:
            max_depth: 最大遍历深度

        Returns:
            桌面元素列表
        """
        start_time = time.time()

        elements = self.client.get_desktop_elements(max_depth=max_depth)

        elapsed_ms = int((time.time() - start_time * 1000))

        return {
            "success": True,
            "desktop_elements": [elem.to_dict() for elem in elements],
            "window_count": len(elements),
            "elapsed_ms": elapsed_ms,
        }

    def parse_focused_element(self) -> dict[str, Any]:
        """
        解析当前焦点元素

        Returns:
            焦点元素信息
        """
        start_time = time.time()

        try:
            import uiautomation as auto
            focused = auto.GetFocusedControl()
            if focused:
                info = self.client._element_to_info(focused, depth=0)
                elapsed_ms = int((time.time() - start_time) * 1000)
                return {
                    "success": True,
                    "focused_element": info.to_dict() if info else None,
                    "elapsed_ms": elapsed_ms,
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"获取焦点元素失败: {e}",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

        return {
            "success": False,
            "error": "未找到焦点元素",
            "elapsed_ms": int((time.time() - start_time) * 1000),
        }

    def find_interactable_elements(
        self,
        window_title: Optional[str] = None,
        process_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        查找窗口中所有可交互元素

        Args:
            window_title: 窗口标题
            process_id: 进程 ID

        Returns:
            可交互元素列表
        """
        start_time = time.time()

        # 解析窗口树
        tree_result = self.parse_window(
            window_title=window_title,
            process_id=process_id,
            max_depth=10,
            max_elements=1000,
        )

        if not tree_result.get("success"):
            return tree_result

        # 过滤可交互元素
        interactable = self._filter_interactable(tree_result.get("tree", {}))

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "interactable_elements": interactable,
            "count": len(interactable),
            "elapsed_ms": elapsed_ms,
        }

    def _count_elements(self, tree: UIElementInfo) -> int:
        """计算元素数量"""
        count = 1
        for child in tree.children:
            count += self._count_elements(child)
        return count

    def _filter_interactable(self, element: dict[str, Any]) -> list[dict[str, Any]]:
        """过滤可交互元素"""
        interactable_types = [
            "Button", "CheckBox", "ComboBox", "Edit", "Hyperlink",
            "ListItem", "MenuItem", "RadioButton", "TabItem", "TreeItem",
            "Slider", "Spinner", "SplitButton", "Text",  # Text 可能可编辑
        ]

        interactable_patterns = [
            "InvokePattern", "TogglePattern", "ExpandCollapsePattern",
            "ValuePattern", "SelectionPattern", "ScrollPattern",
        ]

        results = []

        # 检查当前元素
        control_type = element.get("control_type", "")
        patterns = element.get("patterns", [])
        is_enabled = element.get("is_enabled", True)
        is_visible = element.get("is_visible", True)

        if is_enabled and is_visible:
            # 检查类型或 Pattern
            if control_type in interactable_types:
                results.append(self._simplify_element(element))
            elif any(p in interactable_patterns for p in patterns):
                results.append(self._simplify_element(element))

        # 递归检查子元素
        for child in element.get("children", []):
            results.extend(self._filter_interactable(child))

        return results

    def _simplify_element(self, element: dict[str, Any]) -> dict[str, Any]:
        """简化元素信息（只保留关键属性）"""
        return {
            "name": element.get("name", ""),
            "control_type": element.get("control_type", ""),
            "automation_id": element.get("automation_id", ""),
            "bounding_rectangle": element.get("bounding_rectangle", (0, 0, 0, 0)),
            "patterns": element.get("patterns", []),
            "is_enabled": element.get("is_enabled", True),
            "depth": element.get("depth", 0),
        }

    def to_llm_readable(self, tree_result: dict[str, Any]) -> str:
        """
        将 Accessibility Tree 转换为 LLM 易读的文本格式

        Args:
            tree_result: parse_window 返回的结果

        Returns:
            LLM 易读的文本描述
        """
        if not tree_result.get("success"):
            return f"解析失败: {tree_result.get('error', '未知错误')}"

        tree = tree_result.get("tree", {})
        window = tree_result.get("window", {})

        lines = []
        lines.append(f"# 窗口: {window.get('name', '未知')}")
        lines.append(f"类型: {window.get('control_type', 'Window')}")
        lines.append(f"进程ID: {window.get('process_id', 0)}")
        lines.append(f"边界: {window.get('bounding_rectangle', (0, 0, 0, 0))}")
        lines.append("")
        lines.append("# UI 元素树:")
        lines.append(self._format_tree(tree, indent=0))

        return "\n".join(lines)

    def _format_tree(self, element: dict[str, Any], indent: int) -> str:
        """格式化元素树"""
        prefix = "  " * indent
        name = element.get("name", "")[:50]  # 截断长名称
        control_type = element.get("control_type", "Unknown")
        automation_id = element.get("automation_id", "")
        patterns = element.get("patterns", [])

        line = f"{prefix}[{control_type}] {name}"
        if automation_id:
            line += f" (id: {automation_id})"
        if patterns:
            line += f" [patterns: {', '.join(patterns[:3])}]"  # 只显示前3个

        lines = [line]
        for child in element.get("children", []):
            lines.append(self._format_tree(child, indent + 1))

        return "\n".join(lines)


# 单例解析器
_parser: Optional[AccessibilityTreeParser] = None


def get_parser() -> AccessibilityTreeParser:
    """获取解析器单例"""
    global _parser
    if _parser is None:
        _parser = AccessibilityTreeParser()
    return _parser