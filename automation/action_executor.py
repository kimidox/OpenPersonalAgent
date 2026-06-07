"""
动作执行器

执行 UI Automation 动作，包括点击、输入、滚动等。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .uia_client import UIAClient, UIElementInfo, get_uia_client


class ActionExecutor:
    """动作执行器"""

    def __init__(self, client: Optional[UIAClient] = None):
        """
        初始化执行器

        Args:
            client: UIA 客户端
        """
        self.client = client or get_uia_client()

    def click(
        self,
        element: Any,
        method: str = "invoke",
        wait_time: float = 0.1,
    ) -> dict[str, Any]:
        """
        点击元素

        Args:
            element: 元素对象或元素信息
            method: 点击方法（invoke=InvokePattern, mouse=鼠标点击）
            wait_time: 点击后等待时间

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            if isinstance(element, dict):
                # 从元素信息重建元素对象
                automation_id = element.get("automation_id", "")
                name = element.get("name", "")
                control_type = element.get("control_type", "")

                if automation_id:
                    target = auto.FindControl(lambda c: c.AutomationId == automation_id, searchDepth=10)
                elif name:
                    ct = self.client._str_to_control_type(control_type) if control_type else None
                    if ct:
                        target = auto.FindControl(
                            lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                    else:
                        target = auto.FindControl(
                            lambda c: name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                else:
                    return {
                        "success": False,
                        "error": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element

            if not target:
                return {
                    "success": False,
                    "error": "未找到目标元素",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            # 执行点击
            if method == "invoke":
                # 使用 InvokePattern
                invoke_pattern = target.GetPattern(auto.PatternInvoke)
                if invoke_pattern:
                    invoke_pattern.Invoke()
                else:
                    # fallback 到鼠标点击
                    rect = target.BoundingRectangle
                    if rect:
                        center_x = (rect.left + rect.right) // 2
                        center_y = (rect.top + rect.bottom) // 2
                        auto.Click(center_x, center_y)
                    else:
                        return {
                            "success": False,
                            "error": "元素不支持 InvokePattern 且无法获取坐标",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
            elif method == "mouse":
                # 鼠标点击
                rect = target.BoundingRectangle
                if rect:
                    center_x = (rect.left + rect.right) // 2
                    center_y = (rect.top + rect.bottom) // 2
                    auto.Click(center_x, center_y)
                else:
                    return {
                        "success": False,
                        "error": "无法获取元素坐标",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
            else:
                return {
                    "success": False,
                    "error": f"未知的点击方法: {method}",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            if wait_time > 0:
                time.sleep(wait_time)

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "action": "click",
                "method": method,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def type_text(
        self,
        element: Any,
        text: str,
        method: str = "value",
        clear_first: bool = True,
        wait_time: float = 0.1,
    ) -> dict[str, Any]:
        """
        输入文本

        Args:
            element: 元素对象
            text: 要输入的文本
            method: 输入方法（value=ValuePattern, sendkeys=SendKeys）
            clear_first: 是否先清空
            wait_time: 输入后等待时间

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            if isinstance(element, dict):
                automation_id = element.get("automation_id", "")
                name = element.get("name", "")
                control_type = element.get("control_type", "")

                if automation_id:
                    target = auto.FindControl(lambda c: c.AutomationId == automation_id, searchDepth=10)
                elif name:
                    ct = self.client._str_to_control_type(control_type) if control_type else None
                    if ct:
                        target = auto.FindControl(
                            lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                    else:
                        target = auto.FindControl(
                            lambda c: name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                else:
                    return {
                        "success": False,
                        "error": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element

            if not target:
                return {
                    "success": False,
                    "error": "未找到目标元素",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            # 确保元素有焦点
            try:
                target.SetFocus()
                time.sleep(0.05)
            except Exception:
                pass

            # 执行输入
            if method == "value":
                # 使用 ValuePattern
                value_pattern = target.GetPattern(auto.PatternValue)
                if value_pattern:
                    if clear_first:
                        value_pattern.SetValue("")
                    value_pattern.SetValue(text)
                else:
                    # fallback 到 SendKeys
                    if clear_first:
                        target.SendKeys("{Ctrl}{A}{Delete}", waitTime=0.05)
                    target.SendKeys(text, waitTime=0.05)
            elif method == "sendkeys":
                # 使用 SendKeys
                if clear_first:
                    target.SendKeys("{Ctrl}{A}{Delete}", waitTime=0.05)
                target.SendKeys(text, waitTime=0.05)
            else:
                return {
                    "success": False,
                    "error": f"未知的输入方法: {method}",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            if wait_time > 0:
                time.sleep(wait_time)

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "action": "type_text",
                "method": method,
                "text_length": len(text),
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def scroll(
        self,
        element: Any,
        direction: str = "down",
        amount: str = "small",
        count: int = 1,
    ) -> dict[str, Any]:
        """
        滚动元素

        Args:
            element: 元素对象
            direction: 滚动方向（up/down/left/right）
            amount: 滚动量（small/large）
            count: 滚动次数

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            if isinstance(element, dict):
                automation_id = element.get("automation_id", "")
                name = element.get("name", "")
                control_type = element.get("control_type", "")

                if automation_id:
                    target = auto.FindControl(lambda c: c.AutomationId == automation_id, searchDepth=10)
                elif name:
                    ct = self.client._str_to_control_type(control_type) if control_type else None
                    if ct:
                        target = auto.FindControl(
                            lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                    else:
                        target = auto.FindControl(
                            lambda c: name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                else:
                    return {
                        "success": False,
                        "error": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element

            if not target:
                return {
                    "success": False,
                    "error": "未找到目标元素",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            # 使用 ScrollPattern
            scroll_pattern = target.GetPattern(auto.PatternScroll)
            if scroll_pattern:
                for _ in range(count):
                    if direction == "up":
                        if amount == "small":
                            scroll_pattern.ScrollSmallUp()
                        else:
                            scroll_pattern.ScrollLargeUp()
                    elif direction == "down":
                        if amount == "small":
                            scroll_pattern.ScrollSmallDown()
                        else:
                            scroll_pattern.ScrollLargeDown()
                    elif direction == "left":
                        if amount == "small":
                            scroll_pattern.ScrollSmallLeft()
                        else:
                            scroll_pattern.ScrollLargeLeft()
                    elif direction == "right":
                        if amount == "small":
                            scroll_pattern.ScrollSmallRight()
                        else:
                            scroll_pattern.ScrollLargeRight()
                    time.sleep(0.05)
            else:
                # fallback 到鼠标滚轮
                rect = target.BoundingRectangle
                if rect:
                    center_x = (rect.left + rect.right) // 2
                    center_y = (rect.top + rect.bottom) // 2
                    auto.MoveTo(center_x, center_y)
                    scroll_amount = 120 if amount == "small" else 360
                    if direction in ("up", "left"):
                        scroll_amount = -scroll_amount
                    for _ in range(count):
                        if direction in ("up", "down"):
                            auto.ScrollWheel(scroll_amount, isHorizontal=False)
                        else:
                            auto.ScrollWheel(scroll_amount, isHorizontal=True)
                        time.sleep(0.05)
                else:
                    return {
                        "success": False,
                        "error": "元素不支持 ScrollPattern 且无法获取坐标",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "action": "scroll",
                "direction": direction,
                "amount": amount,
                "count": count,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def expand_collapse(
        self,
        element: Any,
        action: str = "expand",
    ) -> dict[str, Any]:
        """
        展开/折叠元素

        Args:
            element: 元素对象
            action: 动作（expand/collapse/toggle）

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            if isinstance(element, dict):
                automation_id = element.get("automation_id", "")
                name = element.get("name", "")
                control_type = element.get("control_type", "")

                if automation_id:
                    target = auto.FindControl(lambda c: c.AutomationId == automation_id, searchDepth=10)
                elif name:
                    ct = self.client._str_to_control_type(control_type) if control_type else None
                    if ct:
                        target = auto.FindControl(
                            lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                    else:
                        target = auto.FindControl(
                            lambda c: name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                else:
                    return {
                        "success": False,
                        "error": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element

            if not target:
                return {
                    "success": False,
                    "error": "未找到目标元素",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            # 使用 ExpandCollapsePattern
            expand_pattern = target.GetPattern(auto.PatternExpandCollapse)
            if expand_pattern:
                if action == "expand":
                    expand_pattern.Expand()
                elif action == "collapse":
                    expand_pattern.Collapse()
                elif action == "toggle":
                    state = expand_pattern.ExpandCollapseState
                    if state == auto.ExpandCollapseState.Collapsed:
                        expand_pattern.Expand()
                    else:
                        expand_pattern.Collapse()
                else:
                    return {
                        "success": False,
                        "error": f"未知的动作: {action}",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                return {
                    "success": False,
                    "error": "元素不支持 ExpandCollapsePattern",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "action": "expand_collapse",
                "operation": action,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def toggle(
        self,
        element: Any,
    ) -> dict[str, Any]:
        """
        切换元素状态（CheckBox、RadioButton 等）

        Args:
            element: 元素对象

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            if isinstance(element, dict):
                automation_id = element.get("automation_id", "")
                name = element.get("name", "")
                control_type = element.get("control_type", "")

                if automation_id:
                    target = auto.FindControl(lambda c: c.AutomationId == automation_id, searchDepth=10)
                elif name:
                    ct = self.client._str_to_control_type(control_type) if control_type else None
                    if ct:
                        target = auto.FindControl(
                            lambda c: c.ControlType == ct and name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                    else:
                        target = auto.FindControl(
                            lambda c: name.lower() in (c.Name or "").lower(),
                            searchDepth=10
                        )
                else:
                    return {
                        "success": False,
                        "error": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element

            if not target:
                return {
                    "success": False,
                    "error": "未找到目标元素",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            # 使用 TogglePattern
            toggle_pattern = target.GetPattern(auto.PatternToggle)
            if toggle_pattern:
                toggle_pattern.Toggle()
            else:
                # fallback 到点击
                return self.click(target, method="invoke")

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "action": "toggle",
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def get_element_state(self, element: Any) -> dict[str, Any]:
        """
        获取元素状态

        Args:
            element: 元素对象

        Returns:
            元素状态信息
        """
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            if isinstance(element, dict):
                automation_id = element.get("automation_id", "")
                name = element.get("name", "")

                if automation_id:
                    target = auto.FindControl(lambda c: c.AutomationId == automation_id, searchDepth=10)
                elif name:
                    target = auto.FindControl(
                        lambda c: name.lower() in (c.Name or "").lower(),
                        searchDepth=10
                    )
                else:
                    return {
                        "success": False,
                        "error": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element

            if not target:
                return {
                    "success": False,
                    "error": "未找到目标元素",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            # 获取状态
            state = {
                "name": target.Name or "",
                "is_enabled": target.IsEnabled if hasattr(target, 'IsEnabled') else True,
                "is_visible": target.IsOffscreen == False if hasattr(target, 'IsOffscreen') else True,
                "is_focusable": target.IsKeyboardFocusable if hasattr(target, 'IsKeyboardFocusable') else False,
                "has_focus": target.HasKeyboardFocus if hasattr(target, 'HasKeyboardFocus') else False,
            }

            # 获取特定 Pattern 的状态
            try:
                toggle_pattern = target.GetPattern(auto.PatternToggle)
                if toggle_pattern:
                    state["toggle_state"] = str(toggle_pattern.ToggleState)
            except Exception:
                pass

            try:
                expand_pattern = target.GetPattern(auto.PatternExpandCollapse)
                if expand_pattern:
                    state["expand_state"] = str(expand_pattern.ExpandCollapseState)
            except Exception:
                pass

            try:
                value_pattern = target.GetPattern(auto.PatternValue)
                if value_pattern:
                    state["value"] = value_pattern.Value
            except Exception:
                pass

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "state": state,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }


# 单例执行器
_executor: Optional[ActionExecutor] = None


def get_executor() -> ActionExecutor:
    """获取执行器单例"""
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor