"""
UI Automation 客户端封装

基于 uiautomation 库，提供对 Windows UI Automation API 的封装。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

try:
    import uiautomation as auto
except ImportError:
    auto = None

from logger import get_module_logger

logger = get_module_logger("UIAClient")


@dataclass
class UIElementInfo:
    """UI 元素信息结构"""
    name: str = ""
    control_type: str = ""
    automation_id: str = ""
    class_name: str = ""
    is_enabled: bool = True
    is_visible: bool = True
    is_focusable: bool = False
    has_keyboard_focus: bool = False
    bounding_rectangle: tuple[int, int, int, int] = (0, 0, 0, 0)  # (left, top, right, bottom)
    process_id: int = 0
    runtime_id: tuple[int, ...] = ()
    depth: int = 0
    children: list[UIElementInfo] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)  # 支持的 Control Patterns

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["runtime_id"] = list(self.runtime_id)  # tuple 转 list
        result["children"] = [child.to_dict() for child in self.children]
        return result

    def to_json(self) -> str:
        """转换为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class UIAClient:
    """UI Automation 客户端"""

    def __init__(self, timeout_ms: int = 5000):
        """
        初始化 UIA 客户端

        Args:
            timeout_ms: 操作超时时间（毫秒）
        """
        if auto is None:
            raise ImportError("uiautomation 库未安装，请运行: pip install uiautomation")
        self.timeout_ms = timeout_ms
        self._root = auto.GetRootControl()

    def is_available(self) -> bool:
        """检查 UIA 是否可用"""
        return auto is not None and self._root is not None

    def get_desktop_elements(self, max_depth: int = 1) -> list[UIElementInfo]:
        """
        获取桌面顶层元素（窗口列表）

        Args:
            max_depth: 最大遍历深度

        Returns:
            窗口元素信息列表
        """
        elements = []
        try:
            for child in self._root.GetChildren():
                info = self._element_to_info(child, depth=0, max_depth=max_depth)
                if info:
                    elements.append(info)
        except Exception as e:
            logger.error(f"获取桌面元素失败: {e}")
        return elements

    def get_window_by_title(self, title: str, exact: bool = False) -> Optional[UIElementInfo]:
        """
        通过窗口标题查找窗口

        Args:
            title: 窗口标题（支持部分匹配）
            exact: 是否精确匹配

        Returns:
            窗口元素信息，未找到返回 None
        """
        try:
            if exact:
                window = self._root.WindowControl(Name=title, searchDepth=1)
            else:
                # 部分匹配
                for child in self._root.GetChildren():
                    if child.ControlType == auto.ControlType.Window:
                        name = child.Name or ""
                        if title.lower() in name.lower():
                            return self._element_to_info(child, depth=0)
            if window and window.Exists(maxSearchSeconds=self.timeout_ms / 1000):
                return self._element_to_info(window, depth=0)
        except Exception as e:
            logger.error(f"查找窗口失败: {e}")
        return None

    def get_window_by_process_id(self, process_id: int) -> Optional[UIElementInfo]:
        """
        通过进程 ID 查找窗口

        Args:
            process_id: 进程 ID

        Returns:
            窗口元素信息，未找到返回 None
        """
        try:
            window = self._root.WindowControl(ProcessId=process_id, searchDepth=1)
            if window and window.Exists(maxSearchSeconds=self.timeout_ms / 1000):
                return self._element_to_info(window, depth=0)
        except Exception as e:
            logger.error(f"查找窗口失败: {e}")
        return None

    def get_focused_window(self) -> Optional[UIElementInfo]:
        """
        获取当前焦点窗口

        Returns:
            焦点窗口元素信息
        """
        try:
            focused = auto.GetFocusedControl()
            if focused:
                # 向上遍历找到窗口
                window = focused
                while window and window.ControlType != auto.ControlType.Window:
                    window = window.GetParentControl()
                if window:
                    return self._element_to_info(window, depth=0)
        except Exception as e:
            logger.error(f"获取焦点窗口失败: {e}")
        return None

    def get_element_tree(
        self,
        root_element: Optional[Any] = None,
        max_depth: int = 5,
        max_elements: int = 500,
    ) -> UIElementInfo:
        """
        获取元素的完整 Accessibility Tree

        Args:
            root_element: 根元素（None 表示桌面）
            max_depth: 最大遍历深度
            max_elements: 最大元素数量限制

        Returns:
            根元素信息（包含子元素树）
        """
        if root_element is None:
            root_element = self._root

        return self._build_tree(root_element, depth=0, max_depth=max_depth, max_elements=max_elements)

    def find_element_by_automation_id(
        self,
        automation_id: str,
        root: Optional[Any] = None,
    ) -> Optional[UIElementInfo]:
        """
        通过 AutomationId 查找元素

        Args:
            automation_id: AutomationId
            root: 搜索根元素（None 表示桌面）

        Returns:
            元素信息
        """
        search_root = root or self._root
        try:
            element = search_root.FindControl(
                lambda c: c.AutomationId == automation_id,
                searchDepth=10
            )
            if element:
                return self._element_to_info(element, depth=0)
        except Exception as e:
            logger.error(f"查找元素失败: {e}")
        return None

    def find_element_by_name(
        self,
        name: str,
        control_type: Optional[str] = None,
        root: Optional[Any] = None,
    ) -> Optional[UIElementInfo]:
        """
        通过名称查找元素

        Args:
            name: 元素名称
            control_type: 控件类型过滤（可选）
            root: 搜索根元素

        Returns:
            元素信息
        """
        search_root = root or self._root
        try:
            if control_type:
                ct = self._str_to_control_type(control_type)
                element = search_root.FindControl(
                    lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                    searchDepth=10
                )
            else:
                element = search_root.FindControl(
                    lambda c: name.lower() in (c.Name or "").lower(),
                    searchDepth=10
                )
            if element:
                return self._element_to_info(element, depth=0)
        except Exception as e:
            logger.error(f"查找元素失败: {e}")
        return None

    def find_elements_by_control_type(
        self,
        control_type: str,
        root: Optional[Any] = None,
        max_results: int = 100,
    ) -> list[UIElementInfo]:
        """
        通过控件类型查找所有匹配元素

        Args:
            control_type: 控件类型
            root: 搜索根元素
            max_results: 最大返回数量

        Returns:
            元素列表
        """
        search_root = root or self._root
        elements = []
        ct = self._str_to_control_type(control_type)
        try:
            for element in search_root.GetChildren():
                if element.ControlType == ct:
                    info = self._element_to_info(element, depth=0)
                    if info:
                        elements.append(info)
                    if len(elements) >= max_results:
                        break
        except Exception as e:
            logger.error(f"查找元素失败: {e}")
        return elements

    def activate_window(self, window_element: Any) -> bool:
        """
        激活窗口（置于前台）

        Args:
            window_element: 窗口元素

        Returns:
            是否成功
        """
        try:
            if hasattr(window_element, 'SetActive'):
                window_element.SetActive()
                return True
        except Exception as e:
            logger.error(f"激活窗口失败: {e}")
        return False

    def _element_to_info(
        self,
        element: Any,
        depth: int = 0,
        max_depth: int = 0,
    ) -> Optional[UIElementInfo]:
        """
        将 uiautomation 元素转换为 UIElementInfo

        Args:
            element: uiautomation 元素
            depth: 当前深度
            max_depth: 最大深度（用于限制子元素遍历）

        Returns:
            元素信息
        """
        try:
            # 获取边界矩形
            rect = element.BoundingRectangle
            bounding = (rect.left, rect.top, rect.right, rect.bottom) if rect else (0, 0, 0, 0)

            # 获取支持的 Control Patterns
            patterns = self._get_supported_patterns(element)

            info = UIElementInfo(
                name=element.Name or "",
                control_type=self._control_type_to_str(element.ControlType),
                automation_id=element.AutomationId or "",
                class_name=element.ClassName or "",
                is_enabled=element.IsEnabled if hasattr(element, 'IsEnabled') else True,
                is_visible=element.IsOffscreen == False if hasattr(element, 'IsOffscreen') else True,
                is_focusable=element.IsKeyboardFocusable if hasattr(element, 'IsKeyboardFocusable') else False,
                has_keyboard_focus=element.HasKeyboardFocus if hasattr(element, 'HasKeyboardFocus') else False,
                bounding_rectangle=bounding,
                process_id=element.ProcessId if hasattr(element, 'ProcessId') else 0,
                runtime_id=element.RuntimeId if hasattr(element, 'RuntimeId') else (),
                depth=depth,
                patterns=patterns,
            )

            return info
        except Exception as e:
            logger.error(f"转换元素信息失败: {e}")
            return None

    def _build_tree(
        self,
        element: Any,
        depth: int,
        max_depth: int,
        max_elements: int,
        count: list[int] = None,
    ) -> UIElementInfo:
        """
        构建元素树

        Args:
            element: 当前元素
            depth: 当前深度
            max_depth: 最大深度
            max_elements: 最大元素数量
            count: 计数器（用于限制）

        Returns:
            元素信息树
        """
        if count is None:
            count = [0]

        if count[0] >= max_elements:
            return UIElementInfo(name="(达到最大元素限制)", depth=depth)

        info = self._element_to_info(element, depth=depth)
        if info is None:
            return UIElementInfo(depth=depth)

        count[0] += 1

        # 递归获取子元素
        if depth < max_depth:
            try:
                children = element.GetChildren()
                for child in children:
                    child_info = self._build_tree(
                        child,
                        depth + 1,
                        max_depth,
                        max_elements,
                        count
                    )
                    info.children.append(child_info)
                    if count[0] >= max_elements:
                        break
            except Exception as e:
                logger.debug("获取窗口列表异常: %s", e)

    def _control_type_to_str(self, ct: int) -> str:
        """将 ControlType 整数转换为字符串"""
        type_map = {
            auto.ControlType.ButtonControl: "Button",
            auto.ControlType.CalendarControl: "Calendar",
            auto.ControlType.CheckBoxControl: "CheckBox",
            auto.ControlType.ComboBoxControl: "ComboBox",
            auto.ControlType.EditControl: "Edit",
            auto.ControlType.HyperlinkControl: "Hyperlink",
            auto.ControlType.ImageControl: "Image",
            auto.ControlType.ListItemControl: "ListItem",
            auto.ControlType.ListControl: "List",
            auto.ControlType.MenuControl: "Menu",
            auto.ControlType.MenuBarControl: "MenuBar",
            auto.ControlType.MenuItemControl: "MenuItem",
            auto.ControlType.ProgressBarControl: "ProgressBar",
            auto.ControlType.RadioButtonControl: "RadioButton",
            auto.ControlType.ScrollBarControl: "ScrollBar",
            auto.ControlType.SliderControl: "Slider",
            auto.ControlType.SpinnerControl: "Spinner",
            auto.ControlType.SplitButtonControl: "SplitButton",
            auto.ControlType.StatusBarControl: "StatusBar",
            auto.ControlType.TabControl: "Tab",
            auto.ControlType.TabItemControl: "TabItem",
            auto.ControlType.TextControl: "Text",
            auto.ControlType.ToolBarControl: "ToolBar",
            auto.ControlType.ToolTipControl: "ToolTip",
            auto.ControlType.TreeControl: "Tree",
            auto.ControlType.TreeItemControl: "TreeItem",
            auto.ControlType.CustomControl: "Custom",
            auto.ControlType.DataGridControl: "DataGrid",
            auto.ControlType.DataItemControl: "DataItem",
            auto.ControlType.DocumentControl: "Document",
            auto.ControlType.GroupControl: "Group",
            auto.ControlType.HeaderControl: "Header",
            auto.ControlType.HeaderItemControl: "HeaderItem",
            auto.ControlType.PaneControl: "Pane",
            auto.ControlType.SeparatorControl: "Separator",
            auto.ControlType.WindowControl: "Window",
            auto.ControlType.TitleBarControl: "TitleBar",
        }
        return type_map.get(ct, f"Unknown({ct})")

    def _str_to_control_type(self, type_str: str) -> int:
        """将字符串转换为 ControlType 整数"""
        str_map = {
            "Button": auto.ControlType.ButtonControl,
            "Calendar": auto.ControlType.CalendarControl,
            "CheckBox": auto.ControlType.CheckBoxControl,
            "ComboBox": auto.ControlType.ComboBoxControl,
            "Edit": auto.ControlType.EditControl,
            "Text": auto.ControlType.TextControl,
            "Hyperlink": auto.ControlType.HyperlinkControl,
            "Image": auto.ControlType.ImageControl,
            "ListItem": auto.ControlType.ListItemControl,
            "List": auto.ControlType.ListControl,
            "Menu": auto.ControlType.MenuControl,
            "MenuBar": auto.ControlType.MenuBarControl,
            "MenuItem": auto.ControlType.MenuItemControl,
            "ProgressBar": auto.ControlType.ProgressBarControl,
            "RadioButton": auto.ControlType.RadioButtonControl,
            "ScrollBar": auto.ControlType.ScrollBarControl,
            "Slider": auto.ControlType.SliderControl,
            "Spinner": auto.ControlType.SpinnerControl,
            "SplitButton": auto.ControlType.SplitButtonControl,
            "StatusBar": auto.ControlType.StatusBarControl,
            "Tab": auto.ControlType.TabControl,
            "TabItem": auto.ControlType.TabItemControl,
            "ToolBar": auto.ControlType.ToolBarControl,
            "ToolTip": auto.ControlType.ToolTipControl,
            "Tree": auto.ControlType.TreeControl,
            "TreeItem": auto.ControlType.TreeItemControl,
            "Custom": auto.ControlType.CustomControl,
            "DataGrid": auto.ControlType.DataGridControl,
            "DataItem": auto.ControlType.DataItemControl,
            "Document": auto.ControlType.DocumentControl,
            "Group": auto.ControlType.GroupControl,
            "Header": auto.ControlType.HeaderControl,
            "HeaderItem": auto.ControlType.HeaderItemControl,
            "Pane": auto.ControlType.PaneControl,
            "Separator": auto.ControlType.SeparatorControl,
            "Window": auto.ControlType.WindowControl,
            "TitleBar": auto.ControlType.TitleBarControl,
        }
        return str_map.get(type_str, auto.ControlType.CustomControl)

    def _get_supported_patterns(self, element: Any) -> list[str]:
        """获取元素支持的 Control Patterns"""
        patterns = []
        pattern_names = [
            "InvokePattern",
            "ExpandCollapsePattern",
            "TogglePattern",
            "SelectionPattern",
            "ValuePattern",
            "RangeValuePattern",
            "ScrollPattern",
            "ScrollItemPattern",
            "TextPattern",
            "WindowPattern",
            "TransformPattern",
            "DockPattern",
            "TablePattern",
            "TableItemPattern",
            "GridPattern",
            "GridItemPattern",
            "MultipleViewPattern",
            "WindowPattern",
        ]

        for pattern_name in pattern_names:
            try:
                pattern = element.GetPattern(pattern_name)
                if pattern:
                    patterns.append(pattern_name)
            except Exception as e:
                logger.debug("获取桌面元素异常: %s", e)

        return patterns


# 单例客户端
_client: Optional[UIAClient] = None


def get_uia_client(timeout_ms: int = 5000) -> UIAClient:
    """获取 UIA 客户端单例"""
    global _client
    if _client is None:
        _client = UIAClient(timeout_ms=timeout_ms)
    return _client