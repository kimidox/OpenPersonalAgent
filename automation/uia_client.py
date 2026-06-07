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
            print(f"获取桌面元素失败: {e}")
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
            print(f"查找窗口失败: {e}")
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
            print(f"查找窗口失败: {e}")
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
            print(f"获取焦点窗口失败: {e}")
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
            print(f"查找元素失败: {e}")
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
            print(f"查找元素失败: {e}")
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
            print(f"查找元素失败: {e}")
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
            print(f"激活窗口失败: {e}")
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
            print(f"转换元素信息失败: {e}")
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
            except Exception:
                pass

        return info

    def _control_type_to_str(self, ct: int) -> str:
        """将 ControlType 整数转换为字符串"""
        type_map = {
            auto.ControlType.Button: "Button",
            auto.ControlType.Calendar: "Calendar",
            auto.ControlType.CheckBox: "CheckBox",
            auto.ControlType.ComboBox: "ComboBox",
            auto.ControlType.Edit: "Edit",
            auto.ControlType.Hyperlink: "Hyperlink",
            auto.ControlType.Image: "Image",
            auto.ControlType.ListItem: "ListItem",
            auto.ControlType.List: "List",
            auto.ControlType.Menu: "Menu",
            auto.ControlType.MenuBar: "MenuBar",
            auto.ControlType.MenuItem: "MenuItem",
            auto.ControlType.ProgressBar: "ProgressBar",
            auto.ControlType.RadioButton: "RadioButton",
            auto.ControlType.ScrollBar: "ScrollBar",
            auto.ControlType.Slider: "Slider",
            auto.ControlType.Spinner: "Spinner",
            auto.ControlType.SplitButton: "SplitButton",
            auto.ControlType.StatusBar: "StatusBar",
            auto.ControlType.Tab: "Tab",
            auto.ControlType.TabItem: "TabItem",
            auto.ControlType.Text: "Text",
            auto.ControlType.ToolBar: "ToolBar",
            auto.ControlType.ToolTip: "ToolTip",
            auto.ControlType.Tree: "Tree",
            auto.ControlType.TreeItem: "TreeItem",
            auto.ControlType.Custom: "Custom",
            auto.ControlType.DataGrid: "DataGrid",
            auto.ControlType.DataItem: "DataItem",
            auto.ControlType.Document: "Document",
            auto.ControlType.Group: "Group",
            auto.ControlType.Header: "Header",
            auto.ControlType.HeaderItem: "HeaderItem",
            auto.ControlType.Pane: "Pane",
            auto.ControlType.ScrollBar: "ScrollBar",
            auto.ControlType.Separator: "Separator",
            auto.ControlType.Window: "Window",
            auto.ControlType.TitleBar: "TitleBar",
            auto.ControlType.ToolTip: "ToolTip",
        }
        return type_map.get(ct, f"Unknown({ct})")

    def _str_to_control_type(self, type_str: str) -> int:
        """将字符串转换为 ControlType 整数"""
        str_map = {
            "Button": auto.ControlType.Button,
            "Calendar": auto.ControlType.Calendar,
            "CheckBox": auto.ControlType.CheckBox,
            "ComboBox": auto.ControlType.ComboBox,
            "Edit": auto.ControlType.Edit,
            "Text": auto.ControlType.Text,
            "Hyperlink": auto.ControlType.Hyperlink,
            "Image": auto.ControlType.Image,
            "ListItem": auto.ControlType.ListItem,
            "List": auto.ControlType.List,
            "Menu": auto.ControlType.Menu,
            "MenuBar": auto.ControlType.MenuBar,
            "MenuItem": auto.ControlType.MenuItem,
            "ProgressBar": auto.ControlType.ProgressBar,
            "RadioButton": auto.ControlType.RadioButton,
            "ScrollBar": auto.ControlType.ScrollBar,
            "Slider": auto.ControlType.Slider,
            "Spinner": auto.ControlType.Spinner,
            "SplitButton": auto.ControlType.SplitButton,
            "StatusBar": auto.ControlType.StatusBar,
            "Tab": auto.ControlType.Tab,
            "TabItem": auto.ControlType.TabItem,
            "ToolBar": auto.ControlType.ToolBar,
            "ToolTip": auto.ControlType.ToolTip,
            "Tree": auto.ControlType.Tree,
            "TreeItem": auto.ControlType.TreeItem,
            "Custom": auto.ControlType.Custom,
            "DataGrid": auto.ControlType.DataGrid,
            "DataItem": auto.ControlType.DataItem,
            "Document": auto.ControlType.Document,
            "Group": auto.ControlType.Group,
            "Header": auto.ControlType.Header,
            "HeaderItem": auto.ControlType.HeaderItem,
            "Pane": auto.ControlType.Pane,
            "Separator": auto.ControlType.Separator,
            "Window": auto.ControlType.Window,
            "TitleBar": auto.ControlType.TitleBar,
        }
        return str_map.get(type_str, auto.ControlType.Custom)

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
            except Exception:
                pass

        return patterns


# 单例客户端
_client: Optional[UIAClient] = None


def get_uia_client(timeout_ms: int = 5000) -> UIAClient:
    """获取 UIA 客户端单例"""
    global _client
    if _client is None:
        _client = UIAClient(timeout_ms=timeout_ms)
    return _client