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

from logger import get_module_logger, generate_trace_id

logger = get_module_logger("ActionExecutor")


class ActionExecutor:
    """动作执行器"""

    def __init__(self, client: Optional[UIAClient] = None):
        """
        初始化执行器

        Args:
            client: UIA 客户端
        """
        self.client = client or get_uia_client()

    def _resolve_element(
        self,
        element: Any,
        auto_module,
        error_key: str = "success",
        error_label: str = "error",
    ) -> tuple[Any, dict[str, Any] | None]:
        """从元素信息字典或元素对象解析为 UI 元素对象。

        将 7 个操作方法中重复的 isinstance(element, dict) 判断和 FindControl
        搜索逻辑统一提取到此方法，消除代码重复。

        Args:
            element: 元素对象（直接传入）或元素信息字典（含 automation_id/name/control_type）。
            auto_module: uiautomation 模块，由调用方在其 try 块内 import 后传入。
            error_key: 失败时返回字典的主键名，默认 "success"；
                verify_operation_feasible 传 "feasible"。
            error_label: 失败时返回字典的错误描述键名，默认 "error"；
                verify_operation_feasible 传 "reason"。

        Returns:
            (target, None)  — 成功解析到 UI 元素对象。
            (None, error_dict) — 解析失败，error_dict 包含错误信息。
        """
        if isinstance(element, dict):
            automation_id = element.get("automation_id", "")
            name = element.get("name", "")
            control_type = element.get("control_type", "")

            target = None
            if automation_id:
                target = auto_module.FindControl(
                    lambda c: c.AutomationId == automation_id, searchDepth=10
                )
            elif name:
                ct = self.client._str_to_control_type(control_type) if control_type else None
                if ct:
                    target = auto_module.FindControl(
                        lambda c: c.ControlType == ct
                        and name.lower() in (c.Name or "").lower(),
                        searchDepth=10,
                    )
                else:
                    target = auto_module.FindControl(
                        lambda c: name.lower() in (c.Name or "").lower(),
                        searchDepth=10,
                    )
            else:
                return None, {
                    error_key: False,
                    error_label: "元素信息不足，无法定位",
                    "elapsed_ms": 0,
                }
        else:
            target = element

        if not target:
            return None, {
                error_key: False,
                error_label: "未找到目标元素",
                "elapsed_ms": 0,
            }

        return target, None

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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context(f"click: method={method}, wait_time={wait_time}", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto)
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("click: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error

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
                        logger.debug_with_context("click: no InvokePattern and no coords", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="no_pattern_no_coords")
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
                    logger.debug_with_context("click: no coords for mouse click", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="no_coords")
                    return {
                        "success": False,
                        "error": "无法获取元素坐标",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                logger.debug_with_context(f"click: unknown method {method}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="unknown_method")
                return {
                    "success": False,
                    "error": f"未知的点击方法: {method}",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            if wait_time > 0:
                time.sleep(wait_time)

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug_with_context(f"click: success, elapsed_ms={elapsed_ms}", trace_id=trace_id, operation_type="ui_action", phase="complete")

            return {
                "success": True,
                "action": "click",
                "method": method,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.debug_with_context(f"click: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context(f"type_text: method={method}, clear_first={clear_first}", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto)
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("type_text: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error

            # 确保元素有焦点
            try:
                target.SetFocus()
                time.sleep(0.05)
            except Exception as e: logger.debug("SetFocus 失败（非关键）: %s", e)

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
                logger.debug_with_context(f"type_text: unknown method {method}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="unknown_method")
                return {
                    "success": False,
                    "error": f"未知的输入方法: {method}",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            if wait_time > 0:
                time.sleep(wait_time)

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug_with_context(f"type_text: success, elapsed_ms={elapsed_ms}", trace_id=trace_id, operation_type="ui_action", phase="complete")

            return {
                "success": True,
                "action": "type_text",
                "method": method,
                "text_length": len(text),
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.debug_with_context(f"type_text: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context(f"scroll: direction={direction}, amount={amount}", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto)
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("scroll: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error

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
                    logger.debug_with_context("scroll: no ScrollPattern and no coords", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="no_pattern_no_coords")
                    return {
                        "success": False,
                        "error": "元素不支持 ScrollPattern 且无法获取坐标",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug_with_context(f"scroll: success, elapsed_ms={elapsed_ms}", trace_id=trace_id, operation_type="ui_action", phase="complete")

            return {
                "success": True,
                "action": "scroll",
                "direction": direction,
                "amount": amount,
                "count": count,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.debug_with_context(f"scroll: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context(f"expand_collapse: action={action}", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto)
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("expand_collapse: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error

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
                    logger.debug_with_context(f"expand_collapse: unknown action {action}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="unknown_action")
                    return {
                        "success": False,
                        "error": f"未知的动作: {action}",
                        "elapsed_ms": int((time.time() - start_time) * 1000),
                    }
            else:
                logger.debug_with_context("expand_collapse: no ExpandCollapsePattern", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="no_pattern")
                return {
                    "success": False,
                    "error": "元素不支持 ExpandCollapsePattern",
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                }

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug_with_context(f"expand_collapse: success, elapsed_ms={elapsed_ms}", trace_id=trace_id, operation_type="ui_action", phase="complete")

            return {
                "success": True,
                "action": "expand_collapse",
                "operation": action,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.debug_with_context(f"expand_collapse: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context("toggle", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto)
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("toggle: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error

            # 使用 TogglePattern
            toggle_pattern = target.GetPattern(auto.PatternToggle)
            if toggle_pattern:
                toggle_pattern.Toggle()
            else:
                # fallback 到点击
                return self.click(target, method="invoke")

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug_with_context(f"toggle: success, elapsed_ms={elapsed_ms}", trace_id=trace_id, operation_type="ui_action", phase="complete")

            return {
                "success": True,
                "action": "toggle",
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.debug_with_context(f"toggle: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context("get_element_state", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto)
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("get_element_state: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error

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
            except Exception as e: logger.debug("获取 TogglePattern 失败: %s", e)

            try:
                expand_pattern = target.GetPattern(auto.PatternExpandCollapse)
                if expand_pattern:
                    state["expand_state"] = str(expand_pattern.ExpandCollapseState)
            except Exception as e: logger.debug("获取 ExpandCollapsePattern 失败: %s", e)

            try:
                value_pattern = target.GetPattern(auto.PatternValue)
                if value_pattern:
                    state["value"] = value_pattern.Value
            except Exception as e: logger.debug("获取 ValuePattern 失败: %s", e)

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug_with_context(f"get_element_state: success, elapsed_ms={elapsed_ms}", trace_id=trace_id, operation_type="ui_action", phase="complete")

            return {
                "success": True,
                "state": state,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.debug_with_context(f"get_element_state: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
        trace_id = generate_trace_id("action_executor")
        logger.debug_with_context(f"verify_operation_feasible: operation={operation}", trace_id=trace_id, operation_type="ui_action", phase="start")
        start_time = time.time()

        try:
            import uiautomation as auto

            # 获取元素对象
            target, resolve_error = self._resolve_element(element, auto, error_key="feasible", error_label="reason")
            if resolve_error is not None:
                resolve_error["elapsed_ms"] = int((time.time() - start_time) * 1000)
                logger.debug_with_context("verify_operation_feasible: resolve element failed", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="resolve_failed")
                return resolve_error
            
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
            
            logger.debug_with_context(f"verify_operation_feasible: default allow for operation={operation}", trace_id=trace_id, operation_type="ui_action", phase="complete")
            return {
                "feasible": True,
                "reason": f"操作 '{operation}' 未进行可行性检查，默认允许",
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }

        except Exception as e:
            logger.debug_with_context(f"verify_operation_feasible: exception {e}", trace_id=trace_id, operation_type="ui_action", phase="error", error_code="exception")
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
                    operation_result = self.click(element, method=m, **kwargs)
                    tracker.record_operation_attempt("click", m, operation_result.get("success", False), element_name)
                elif operation == "type":
                    text = kwargs.get("text", "")
                    operation_result = self.type_text(element, text=text, method=m, **kwargs)
                    tracker.record_operation_attempt("type_text", m, operation_result.get("success", False), element_name)
                elif operation == "scroll":
                    operation_result = self.scroll(element, **kwargs)
                    tracker.record_operation_attempt("scroll", "default", operation_result.get("success", False), element_name)
                else:
                    operation_result = {"success": False, "error": f"未知操作: {operation}"}
                
                if operation_result.get("success"):
                    operation_result["used_method"] = m
                    operation_result["retry_count"] = i
                    return operation_result
                
                results_list.append({
                    "method": m,
                    "error": operation_result.get("error", "操作失败"),
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
        click_result = self.click(element, method=method, wait_time=wait_time)
        
        if not click_result.get("success"):
            return click_result
        
        # 验证点击结果
        verify_result = self.verify_click_result(element, before_state)
        click_result["verification"] = verify_result
        
        return click_result

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
        input_result = self.type_text(element, text=text, method=method, clear_first=clear_first, wait_time=wait_time)
        
        if not input_result.get("success"):
            return input_result
        
        # 验证输入结果
        verify_result = self.verify_type_result(element, text)
        input_result["verification"] = verify_result
        
        if not verify_result.get("verified"):
            input_result["success"] = False
            input_result["error"] = verify_result.get("reason", "输入验证失败")
        
        return input_result


# 单例执行器
_executor: Optional[ActionExecutor] = None


def get_executor() -> ActionExecutor:
    """获取执行器单例"""
    global _executor
    if _executor is None:
        _executor = ActionExecutor()
    return _executor