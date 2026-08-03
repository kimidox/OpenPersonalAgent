"""
元素查找器

多策略元素查找，支持按名称、AutomationId、角色、坐标等查找。
包含幻觉检测机制，验证元素是否真实存在。
"""

from __future__ import annotations

import time
from typing import Any, Optional, List

from logger import get_module_logger

from .uia_client import UIAClient, UIElementInfo, get_uia_client
from .success_rate_tracker import get_tracker

logger = get_module_logger("ElementFinder")


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
                except Exception as e:
                    logger.debug("元素查找回调异常: %s", e)

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
                except Exception as e:
                    logger.debug("元素查找回调异常: %s", e)

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
                except Exception as e:
                    logger.debug("元素查找回调异常: %s", e)

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

    def verify_element_exists(self, element_info: dict) -> dict:
        """
        【幻觉检测】验证元素是否真实存在
        
        Args:
            element_info: 元素信息字典
        
        Returns:
            验证结果
        """
        start_time = time.time()
        
        try:
            import uiautomation as auto
            
            # 提取元素信息
            name = element_info.get("name", "")
            automation_id = element_info.get("automation_id", "")
            control_type = element_info.get("control_type", "")
            
            # 尝试重新查找元素
            found = False
            element = None
            
            # 优先使用AutomationId查找（最精确）
            if automation_id:
                element = auto.FindControl(
                    lambda c: c.AutomationId == automation_id,
                    searchDepth=10
                )
                if element:
                    found = True
            
            # 使用名称查找
            if not found and name:
                ct = self.client._str_to_control_type(control_type) if control_type else None
                if ct:
                    element = auto.FindControl(
                        lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                        searchDepth=10
                    )
                else:
                    element = auto.FindControl(
                        lambda c: name.lower() in (c.Name or "").lower(),
                        searchDepth=10
                    )
                if element:
                    found = True
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            if found:
                return {
                    "success": True,
                    "verified": True,
                    "message": f"元素 '{name or automation_id}' 已验证存在",
                    "elapsed_ms": elapsed_ms,
                }
            else:
                return {
                    "success": False,
                    "verified": False,
                    "message": f"【幻觉检测】元素 '{name or automation_id}' 不存在，可能是幻觉操作",
                    "elapsed_ms": elapsed_ms,
                }
        
        except Exception as e:
            return {
                "success": False,
                "verified": False,
                "error": str(e),
                "message": f"验证元素存在时发生错误: {e}",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def find_element_with_retry(
        self,
        method: str,
        query: str,
        window_title: Optional[str] = None,
        max_retries: int = 3,
        element_name: str = None,
    ) -> dict[str, Any]:
        """
        【优化查找】带重试的元素查找，自动尝试多种方法
        
        Args:
            method: 主要查找方法
            query: 查询条件
            window_title: 窗口标题
            max_retries: 最大重试次数
            element_name: 元素名称（用于统计）
        
        Returns:
            查找结果
        """
        tracker = get_tracker()
        
        # 定义查找方法优先级
        methods_priority = ["by_name", "by_automation_id", "by_control_type", "by_coordinates"]
        
        # 如果指定了method，优先尝试该方法
        if method in methods_priority:
            methods_priority.remove(method)
            methods_priority.insert(0, method)
        
        results_list = []
        
        for i, m in enumerate(methods_priority[:max_retries]):
            try:
                if m == "by_name":
                    result = self.find_by_name(query, window_title=window_title)
                elif m == "by_automation_id":
                    result = self.find_by_automation_id(query, window_title=window_title)
                elif m == "by_control_type":
                    result = self.find_by_control_type(query, window_title=window_title)
                elif m == "by_coordinates":
                    # 解析坐标
                    coords = query.split(",")
                    if len(coords) == 2:
                        x, y = int(coords[0].strip()), int(coords[1].strip())
                        result = self.find_by_coordinates(x=x, y=y)
                    else:
                        continue
                
                # 记录统计
                tracker.record_find_attempt(m, result.get("success", False), element_name)
                
                if result.get("success"):
                    # 添加方法信息
                    result["used_method"] = m
                    result["retry_count"] = i
                    return result
                
                results_list.append({
                    "method": m,
                    "error": result.get("error", "未找到"),
                })
                
            except Exception as e:
                results_list.append({
                    "method": m,
                    "error": str(e),
                })
        
        # 所有方法都失败
        elapsed_ms = int((time.time() - results_list[0].get("start_time", time.time()) if results_list else time.time()) * 1000)
        
        return {
            "success": False,
            "error": f"尝试了 {len(results_list)} 种查找方法均失败",
            "tried_methods": results_list,
            "recommendation": tracker.get_recommendation("find_methods"),
            "elapsed_ms": elapsed_ms,
        }

    def find_and_verify(
        self,
        method: str,
        query: str,
        window_title: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        【组合操作】查找元素并验证存在
        
        Args:
            method: 查找方法
            query: 查询条件
            window_title: 窗口标题
        
        Returns:
            查找和验证结果
        """
        # 先查找
        result = self.find_element_with_retry(method, query, window_title)
        
        if not result.get("success"):
            return result
        
        # 获取元素信息
        element_info = None
        if "result" in result:
            element_info = result["result"]
        elif "results" in result and result["results"]:
            element_info = result["results"][0]
        
        if element_info:
            # 验证元素存在
            verify_result = self.verify_element_exists(element_info)
            result["verification"] = verify_result
            
            if not verify_result.get("verified"):
                result["success"] = False
                result["error"] = verify_result.get("message", "元素验证失败")
        
        return result


# 单例查找器
_finder: Optional[ElementFinder] = None


def get_finder() -> ElementFinder:
    """获取查找器单例"""
    global _finder
    if _finder is None:
        _finder = ElementFinder()
    return _finder