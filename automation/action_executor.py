"""
动作执行器

执行 UI Automation 动作，包括点击、输入、滚动等。
包含幻觉检测机制（验证操作可行性）和状态验证机制。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .uia_client import UIAClient, UIElementInfo, get_uia_client
from .success_rate_tracker import get_tracker


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

    def verify_operation_feasible(self, element: Any, operation: str) -> dict[str, Any]:
        """
        【幻觉检测】验证操作是否可行
        
        Args:
            element: 元素对象或元素信息
            operation: 操作类型（click, type, scroll等）
        
        Returns:
            验证结果
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
                        "feasible": False,
                        "reason": "元素信息不足，无法定位",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                target = element
            
            if not target:
                return {
                    "feasible": False,
                    "reason": "元素不存在",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }
            
            # 检查元素是否支持目标操作
            if operation == "click":
                # 检查是否支持InvokePattern或是否可点击
                try:
                    invoke_pattern = target.GetPattern(auto.PatternInvoke)
                    if invoke_pattern:
                        return {
                            "feasible": True,
                            "reason": "元素支持InvokePattern",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                    
                    # 检查是否可点击（有边界且可见）
                    rect = target.BoundingRectangle
                    if rect and target.IsEnabled and target.IsOffscreen == False:
                        return {
                            "feasible": True,
                            "reason": "元素可见且可用，可使用鼠标点击",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                    
                    return {
                        "feasible": False,
                        "reason": "【幻觉检测】元素不支持点击操作（无InvokePattern且不可见或不可用）",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
                except Exception as e:
                    return {
                        "feasible": False,
                        "reason": f"检查点击可行性时发生错误: {e}",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            
            elif operation == "type":
                # 检查是否支持ValuePattern或TextPattern
                try:
                    value_pattern = target.GetPattern(auto.PatternValue)
                    if value_pattern and value_pattern.IsReadOnly == False:
                        return {
                            "feasible": True,
                            "reason": "元素支持ValuePattern且非只读",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                    
                    # 检查控件类型是否是Edit
                    if target.ControlType == auto.ControlType.Edit:
                        return {
                            "feasible": True,
                            "reason": "元素是Edit控件，可使用SendKeys输入",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                    
                    return {
                        "feasible": False,
                        "reason": "【幻觉检测】元素不支持文本输入（无ValuePattern且不是Edit控件）",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
                except Exception as e:
                    return {
                        "feasible": False,
                        "reason": f"检查输入可行性时发生错误: {e}",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            
            elif operation == "scroll":
                # 检查是否支持ScrollPattern
                try:
                    scroll_pattern = target.GetPattern(auto.PatternScroll)
                    if scroll_pattern:
                        return {
                            "feasible": True,
                            "reason": "元素支持ScrollPattern",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                    
                    # 检查是否有边界（可以使用鼠标滚轮）
                    rect = target.BoundingRectangle
                    if rect:
                        return {
                            "feasible": True,
                            "reason": "元素有边界，可使用鼠标滚轮",
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                    
                    return {
                        "feasible": False,
                        "reason": "【幻觉检测】元素不支持滚动操作",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
                except Exception as e:
                    return {
                        "feasible": False,
                        "reason": f"检查滚动可行性时发生错误: {e}",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            
            return {
                "feasible": True,
                "reason": f"操作 '{operation}' 未进行可行性检查，默认允许",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }
        
        except Exception as e:
            return {
                "feasible": False,
                "reason": f"验证操作可行性时发生错误: {e}",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def verify_click_result(self, element: Any, before_state: dict) -> dict[str, Any]:
        """
        【状态验证】验证点击操作结果
        
        Args:
            element: 元素对象
            before_state: 操作前的状态
        
        Returns:
            验证结果
        """
        start_time = time.time()
        
        try:
            import uiautomation as auto
            
            # 获取当前窗口数量
            from .uia_client import get_uia_client
            client = get_uia_client()
            desktop_elements = client.get_desktop_elements(max_depth=1)
            current_window_count = len(desktop_elements)
            
            # 检查元素状态是否改变
            after_state = self.get_element_state(element)
            
            # 比较前后状态
            if current_window_count > before_state.get("window_count", 0):
                return {
                    "success": True,
                    "verified": True,
                    "reason": "新窗口已出现",
                    "window_change": current_window_count - before_state.get("window_count", 0),
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }
            
            if after_state.get("success") and after_state.get("state"):
                after_state_dict = after_state["state"]
                before_state_dict = before_state.get("element_state", {})
                
                # 检查状态变化
                if after_state_dict.get("toggle_state") != before_state_dict.get("toggle_state"):
                    return {
                        "success": True,
                        "verified": True,
                        "reason": "元素toggle状态已改变",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
                
                if after_state_dict.get("expand_state") != before_state_dict.get("expand_state"):
                    return {
                        "success": True,
                        "verified": True,
                        "reason": "元素expand状态已改变",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            
            # 无法验证，但操作可能已成功
            return {
                "success": True,
                "verified": False,
                "reason": "点击后无明显状态变化，但操作可能已成功",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }
        
        except Exception as e:
            return {
                "success": False,
                "verified": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def verify_type_result(self, element: Any, expected_text: str) -> dict[str, Any]:
        """
        【状态验证】验证输入操作结果
        
        Args:
            element: 元素对象
            expected_text: 期望输入的文本
        
        Returns:
            验证结果
        """
        start_time = time.time()
        
        try:
            # 使用get_element_state检查输入值
            state_result = self.get_element_state(element)
            
            if not state_result.get("success"):
                return {
                    "success": False,
                    "verified": False,
                    "error": state_result.get("error", "获取元素状态失败"),
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }
            
            state = state_result.get("state", {})
            actual_value = state.get("value", "")
            
            if actual_value == expected_text:
                return {
                    "success": True,
                    "verified": True,
                    "reason": "输入值正确",
                    "actual_value": actual_value,
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }
            
            # 检查是否包含期望文本（可能只是追加）
            if expected_text in actual_value:
                return {
                    "success": True,
                    "verified": True,
                    "reason": "输入值包含期望文本",
                    "actual_value": actual_value,
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }
            
            return {
                "success": False,
                "verified": False,
                "reason": f"输入值不正确，期望: '{expected_text}', 实际: '{actual_value}'",
                "expected": expected_text,
                "actual": actual_value,
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }
        
        except Exception as e:
            return {
                "success": False,
                "verified": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def verify_start_result(self, app_name: str, timeout: float = 5.0) -> dict[str, Any]:
        """
        【状态验证】验证启动程序结果
        
        Args:
            app_name: 程序名称
            timeout: 超时时间
        
        Returns:
            验证结果
        """
        start_time = time.time()
        
        try:
            from .uia_client import get_uia_client
            client = get_uia_client()
            
            check_start = time.time()
            while time.time() - check_start < timeout:
                desktop_elements = client.get_desktop_elements(max_depth=1)
                for window in desktop_elements:
                    if app_name.lower() in window.name.lower():
                        return {
                            "success": True,
                            "verified": True,
                            "reason": f"窗口 '{window.name}' 已出现",
                            "window_name": window.name,
                            "process_id": window.process_id,
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                time.sleep(0.5)
            
            return {
                "success": False,
                "verified": False,
                "reason": f"窗口 '{app_name}' 未在 {timeout} 秒内出现",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }
        
        except Exception as e:
            return {
                "success": False,
                "verified": False,
                "error": str(e),
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

    def execute_with_retry(
        self,
        operation: str,
        element: Any,
        max_retries: int = 3,
        element_name: str = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        【优化操作】带重试的操作执行，自动尝试多种方法
        
        Args:
            operation: 操作类型（click, type_text, scroll等）
            element: 元素对象
            max_retries: 最大重试次数
            element_name: 元素名称（用于统计）
            **kwargs: 其他参数
        
        Returns:
            执行结果
        """
        tracker = get_tracker()
        
        # 定义操作方法优先级
        methods_priority = {
            "click": ["invoke", "mouse"],
            "type": ["value", "sendkeys"],
            "scroll": ["pattern", "wheel"],
        }
        
        methods = methods_priority.get(operation, [operation])
        results_list = []
        
        for i, m in enumerate(methods[:max_retries]):
            try:
                if operation == "click":
                    result = self.click(element, method=m, **kwargs)
                    tracker.record_operation_attempt("click", m, result.get("success", False), element_name)
                elif operation == "type":
                    text = kwargs.get("text", "")
                    result = self.type_text(element, text=text, method=m, **kwargs)
                    tracker.record_operation_attempt("type_text", m, result.get("success", False), element_name)
                elif operation == "scroll":
                    result = self.scroll(element, **kwargs)
                    tracker.record_operation_attempt("scroll", "default", result.get("success", False), element_name)
                else:
                    result = {"success": False, "error": f"未知操作: {operation}"}
                
                if result.get("success"):
                    result["used_method"] = m
                    result["retry_count"] = i
                    return result
                
                results_list.append({
                    "method": m,
                    "error": result.get("error", "操作失败"),
                })
                
            except Exception as e:
                results_list.append({
                    "method": m,
                    "error": str(e),
                })
        
        # 所有方法都失败
        return {
            "success": False,
            "error": f"尝试了 {len(results_list)} 种操作方法均失败",
            "tried_methods": results_list,
            "recommendation": tracker.get_recommendation("operations"),
            "elapsed_ms": results_list[0].get("elapsed_ms", 0) if results_list else 0,
        }

    def click_with_verification(
        self,
        element: Any,
        method: str = "invoke",
        wait_time: float = 0.1,
    ) -> dict[str, Any]:
        """
        【组合操作】点击元素并验证结果
        
        Args:
            element: 元素对象
            method: 点击方法
            wait_time: 等待时间
        
        Returns:
            点击和验证结果
        """
        # 先验证操作可行性
        feasible_result = self.verify_operation_feasible(element, "click")
        if not feasible_result.get("feasible"):
            return {
                "success": False,
                "error": feasible_result.get("reason", "操作不可行"),
                "verification": feasible_result,
            }
        
        # 获取操作前状态
        from .uia_client import get_uia_client
        client = get_uia_client()
        desktop_elements = client.get_desktop_elements(max_depth=1)
        before_state = {
            "window_count": len(desktop_elements),
            "element_state": self.get_element_state(element).get("state", {}),
        }
        
        # 执行点击
        result = self.click(element, method=method, wait_time=wait_time)
        
        if not result.get("success"):
            return result
        
        # 验证点击结果
        verify_result = self.verify_click_result(element, before_state)
        result["verification"] = verify_result
        
        return result

    def type_with_verification(
        self,
        element: Any,
        text: str,
        method: str = "value",
        clear_first: bool = True,
        wait_time: float = 0.1,
    ) -> dict[str, Any]:
        """
        【组合操作】输入文本并验证结果
        
        Args:
            element: 元素对象
            text: 要输入的文本
            method: 输入方法
            clear_first: 是否先清空
            wait_time: 等待时间
        
        Returns:
            输入和验证结果
        """
        # 先验证操作可行性
        feasible_result = self.verify_operation_feasible(element, "type")
        if not feasible_result.get("feasible"):
            return {
                "success": False,
                "error": feasible_result.get("reason", "操作不可行"),
                "verification": feasible_result,
            }
        
        # 执行输入
        result = self.type_text(element, text=text, method=method, clear_first=clear_first, wait_time=wait_time)
        
        if not result.get("success"):
            return result
        
        # 验证输入结果
        verify_result = self.verify_type_result(element, text)
        result["verification"] = verify_result
        
        if not verify_result.get("verified"):
            result["success"] = False
            result["error"] = verify_result.get("reason", "输入验证失败")
        
        return result


# 单例执行器
_executor: Optional[ActionExecutor] = None


def get_executor() -> ActionExecutor:
    """获取执行器单例"""
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor