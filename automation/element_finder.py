"""
元素查找器

多策略元素查找，支持按名称、AutomationId、角色、坐标等查找。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .uia_client import UIAClient, UIElementInfo, get_uia_client


class ElementFinder:
    """元素查找器"""

    def __init__(self, client: Optional[UIAClient] = None):
        """
        初始化查找器

        Args:
            client: UIA 客户端
        """
        self.client = client or get_uia_client()

    def find_by_name(
        self,
        name: str,
        control_type: Optional[str] = None,
        window_title: Optional[str] = None,
        exact: bool = False,
    ) -> dict[str, Any]:
        """
        按名称查找元素

        Args:
            name: 元素名称
            control_type: 控件类型过滤
            window_title: 窗口标题（限制搜索范围）
            exact: 是否精确匹配

        Returns:
            查找结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 确定搜索根
            search_root = auto.GetRootControl()
            if window_title:
                window = search_root.WindowControl(Name=window_title, searchDepth=1)
                if window and window.Exists(maxSearchSeconds=2):
                    search_root = window

            # 查找元素
            results = []
            search_func = lambda c: (
                (c.Name == name if exact else name.lower() in (c.Name or "").lower())
                and (self.client._str_to_control_type(control_type) == c.ControlType if control_type else True)
            )

            for element in search_root.GetChildren():
                try:
                    if search_func(element):
                        info = self.client._element_to_info(element, depth=0)
                        if info:
                            results.append(info.to_dict())
                except Exception:
                    pass

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "query": {"name": name, "control_type": control_type, "exact": exact},
                "results": results,
                "count": len(results),
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def find_by_automation_id(
        self,
        automation_id: str,
        window_title: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        按 AutomationId 查找元素

        Args:
            automation_id: AutomationId
            window_title: 窗口标题

        Returns:
            查找结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            search_root = auto.GetRootControl()
            if window_title:
                window = search_root.WindowControl(Name=window_title, searchDepth=1)
                if window and window.Exists(maxSearchSeconds=2):
                    search_root = window

            element = search_root.FindControl(
                lambda c: c.AutomationId == automation_id,
                searchDepth=10
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            if element:
                info = self.client._element_to_info(element, depth=0)
                return {
                    "success": True,
                    "query": {"automation_id": automation_id},
                    "result": info.to_dict() if info else None,
                    "elapsed_ms": elapsed_ms,
                }

            return {
                "success": False,
                "error": "未找到元素",
                "query": {"automation_id": automation_id},
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def find_by_control_type(
        self,
        control_type: str,
        window_title: Optional[str] = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """
        按控件类型查找元素

        Args:
            control_type: 控件类型
            window_title: 窗口标题
            max_results: 最大结果数

        Returns:
            查找结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            search_root = auto.GetRootControl()
            if window_title:
                window = search_root.WindowControl(Name=window_title, searchDepth=1)
                if window and window.Exists(maxSearchSeconds=2):
                    search_root = window

            ct = self.client._str_to_control_type(control_type)
            results = []

            for element in search_root.GetChildren():
                try:
                    if element.ControlType == ct:
                        info = self.client._element_to_info(element, depth=0)
                        if info:
                            results.append(info.to_dict())
                        if len(results) >= max_results:
                            break
                except Exception:
                    pass

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "query": {"control_type": control_type},
                "results": results,
                "count": len(results),
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def find_by_coordinates(
        self,
        x: int,
        y: int,
    ) -> dict[str, Any]:
        """
        按坐标查找元素

        Args:
            x: X 坐标
            y: Y 坐标

        Returns:
            该坐标处的元素信息
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            element = auto.ControlFromPoint(x, y)

            elapsed_ms = int((time.time() - start_time) * 1000)

            if element:
                info = self.client._element_to_info(element, depth=0)
                return {
                    "success": True,
                    "query": {"x": x, "y": y},
                    "result": info.to_dict() if info else None,
                    "elapsed_ms": elapsed_ms,
                }

            return {
                "success": False,
                "error": "该坐标无元素",
                "query": {"x": x, "y": y},
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def find_by_pattern(
        self,
        pattern: str,
        window_title: Optional[str] = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """
        按支持的 Pattern 查找元素

        Args:
            pattern: Pattern 名称（如 InvokePattern）
            window_title: 窗口标题
            max_results: 最大结果数

        Returns:
            查找结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            search_root = auto.GetRootControl()
            if window_title:
                window = search_root.WindowControl(Name=window_title, searchDepth=1)
                if window and window.Exists(maxSearchSeconds=2):
                    search_root = window

            results = []

            # 遍历查找
            for element in search_root.GetChildren():
                try:
                    p = element.GetPattern(pattern)
                    if p:
                        info = self.client._element_to_info(element, depth=0)
                        if info:
                            results.append(info.to_dict())
                        if len(results) >= max_results:
                            break
                except Exception:
                    pass

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "query": {"pattern": pattern},
                "results": results,
                "count": len(results),
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }


# 单例查找器
_finder: Optional[ElementFinder] = None


def get_finder() -> ElementFinder:
    """获取查找器单例"""
    global _finder
    if _finder is None:
        _finder = ElementFinder()
    return _finder