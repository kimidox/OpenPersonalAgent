"""
ActionExecutor 单元测试

覆盖 _resolve_element、click、type_text、scroll、get_element_state 方法。
使用 unittest.mock 模拟 uiautomation 库，避免真实 UI 依赖。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from automation.action_executor import ActionExecutor


# ── 通用 fixture ──────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """创建一个 mock UIAClient，包含 _str_to_control_type 方法。"""
    client = MagicMock()
    client._str_to_control_type = MagicMock(return_value=50004)  # 任意 ControlType int
    return client


@pytest.fixture
def executor(mock_client):
    """创建使用 mock_client 的 ActionExecutor 实例。"""
    return ActionExecutor(client=mock_client)


@pytest.fixture
def mock_auto():
    """
    创建 mock uiautomation 模块。
    通过 patch.dict('sys.modules') 注入，让 `import uiautomation as auto` 返回此 mock。
    """
    auto = MagicMock()

    # Pattern 常量
    auto.PatternInvoke = 10000
    auto.PatternValue = 10002
    auto.PatternScroll = 10005
    auto.PatternToggle = 10008
    auto.PatternExpandCollapse = 10006

    # ControlType 常量
    auto.ControlType = MagicMock()
    auto.ControlType.Edit = 50004
    auto.ControlType.ButtonControl = 50000
    auto.ControlType.CustomControl = 50025

    # ExpandCollapseState
    auto.ExpandCollapseState = MagicMock()
    auto.ExpandCollapseState.Collapsed = 0
    auto.ExpandCollapseState.Expanded = 1

    return auto


@pytest.fixture(autouse=True)
def inject_mock_auto(mock_auto):
    """将 mock uiautomation 注入 sys.modules，使 `import uiautomation as auto` 返回 mock。"""
    with patch.dict("sys.modules", {"uiautomation": mock_auto}):
        yield mock_auto


# ── _resolve_element 逻辑测试 ─────────────────────────────────
# ActionExecutor 内部直接在 click/type_text/scroll 等方法中解析 element，
# 没有独立的 _resolve_element 方法。我们通过调用 click 等方法来间接测试解析逻辑。
# 为此，我们使用一个最小化的辅助函数来直接测试解析分支。


class TestResolveElement:
    """测试元素解析逻辑（dict -> target 的转换）。

    由于解析逻辑内联在每个方法中，我们通过 click 方法来间接测试，
    但使用 mock_auto.FindControl 返回 None 的方式隔离后续点击逻辑。
    """

    def test_dict_with_automation_id(self, executor, mock_auto):
        """dict 元素包含 automation_id → 应调用 FindControl 并以 AutomationId 匹配。"""
        mock_auto.FindControl.return_value = None  # 找不到，但我们要验证调用参数

        element = {"automation_id": "btnOK", "name": "OK", "control_type": "Button"}
        result = executor.click(element)

        # 验证 FindControl 被调用
        mock_auto.FindControl.assert_called_once()
        # 验证结果：因为 FindControl 返回 None → "未找到目标元素"
        assert result["success"] is False
        assert "未找到目标元素" in result["error"]

    def test_dict_with_name_only(self, executor, mock_auto):
        """dict 元素有 name 但无 automation_id → 应走 name 分支（无 control_type）。"""
        mock_auto.FindControl.return_value = None

        element = {"name": "OK"}
        result = executor.click(element)

        mock_auto.FindControl.assert_called_once()
        assert result["success"] is False
        assert "未找到目标元素" in result["error"]

    def test_dict_with_name_and_control_type(self, executor, mock_auto):
        """dict 元素有 name + control_type → 应调用 _str_to_control_type 并传给 FindControl。"""
        mock_auto.FindControl.return_value = None

        element = {"name": "Submit", "control_type": "Button"}
        result = executor.click(element)

        # _str_to_control_type 应被调用
        executor.client._str_to_control_type.assert_called_once_with("Button")
        mock_auto.FindControl.assert_called_once()
        assert result["success"] is False

    def test_dict_insufficient_info(self, executor, mock_auto):
        """dict 元素既无 automation_id 也无 name → 返回"元素信息不足"。"""
        element = {"control_type": "Button"}
        result = executor.click(element)

        # 不应调用 FindControl
        mock_auto.FindControl.assert_not_called()
        assert result["success"] is False
        assert "元素信息不足" in result["error"]

    def test_non_dict_passthrough(self, executor, mock_auto):
        """非 dict 元素直接作为 target 使用（pass-through）。"""
        mock_target = MagicMock()
        # 让 invoke 路径成功
        invoke_pattern = MagicMock()
        mock_target.GetPattern.return_value = invoke_pattern

        result = executor.click(mock_target, wait_time=0)

        # FindControl 不应被调用
        mock_auto.FindControl.assert_not_called()
        # 应直接使用传入的 mock_target
        mock_target.GetPattern.assert_called_once_with(mock_auto.PatternInvoke)
        invoke_pattern.Invoke.assert_called_once()
        assert result["success"] is True

    def test_dict_findcontrol_returns_none(self, executor, mock_auto):
        """dict 元素通过 FindControl 查找但返回 None → 返回"未找到目标元素"。"""
        mock_auto.FindControl.return_value = None

        element = {"automation_id": "missing_id"}
        result = executor.click(element)

        assert result["success"] is False
        assert "未找到目标元素" in result["error"]


# ── click 测试 ─────────────────────────────────────────────────


class TestClick:
    """测试 click 方法。"""

    def _make_target(self, mock_auto, has_invoke=True, has_rect=True):
        """创建 mock target 元素。"""
        target = MagicMock()

        if has_invoke:
            invoke_pattern = MagicMock()
            target.GetPattern.return_value = invoke_pattern
        else:
            target.GetPattern.return_value = None

        if has_rect:
            rect = MagicMock()
            rect.left = 100
            rect.top = 200
            rect.right = 300
            rect.bottom = 400
            target.BoundingRectangle = rect
        else:
            target.BoundingRectangle = None

        return target

    def test_click_invoke_method(self, executor, mock_auto):
        """invoke 方法 → 使用 InvokePattern.Invoke()。"""
        target = self._make_target(mock_auto, has_invoke=True)
        result = executor.click(target, method="invoke", wait_time=0)

        assert result["success"] is True
        assert result["action"] == "click"
        assert result["method"] == "invoke"
        target.GetPattern.assert_called_once_with(mock_auto.PatternInvoke)

    def test_click_invoke_fallback_to_mouse(self, executor, mock_auto):
        """invoke 方法但无 InvokePattern → 回退到鼠标点击。"""
        target = self._make_target(mock_auto, has_invoke=False, has_rect=True)
        result = executor.click(target, method="invoke", wait_time=0)

        assert result["success"] is True
        # 验证 Click 被调用（坐标为中心点）
        mock_auto.Click.assert_called_once_with(200, 300)

    def test_click_invoke_no_pattern_no_rect(self, executor, mock_auto):
        """invoke 方法、无 InvokePattern 且无坐标 → 返回失败。"""
        target = self._make_target(mock_auto, has_invoke=False, has_rect=False)
        result = executor.click(target, method="invoke", wait_time=0)

        assert result["success"] is False
        assert "InvokePattern" in result["error"]

    def test_click_mouse_method(self, executor, mock_auto):
        """mouse 方法 → 使用 BoundingRectangle 计算中心点并点击。"""
        target = self._make_target(mock_auto, has_invoke=True, has_rect=True)
        result = executor.click(target, method="mouse", wait_time=0)

        assert result["success"] is True
        assert result["method"] == "mouse"
        mock_auto.Click.assert_called_once_with(200, 300)

    def test_click_mouse_no_rect(self, executor, mock_auto):
        """mouse 方法但无 BoundingRectangle → 返回失败。"""
        target = self._make_target(mock_auto, has_invoke=True, has_rect=False)
        result = executor.click(target, method="mouse", wait_time=0)

        assert result["success"] is False
        assert "无法获取元素坐标" in result["error"]

    def test_click_unknown_method(self, executor, mock_auto):
        """未知点击方法 → 返回失败。"""
        target = self._make_target(mock_auto)
        result = executor.click(target, method="unknown", wait_time=0)

        assert result["success"] is False
        assert "未知的点击方法" in result["error"]

    def test_click_target_is_none(self, executor, mock_auto):
        """target 为 None → 返回"未找到目标元素"。"""
        result = executor.click(None, wait_time=0)

        assert result["success"] is False
        assert "未找到目标元素" in result["error"]

    def test_click_exception_handling(self, executor, mock_auto):
        """执行过程中抛出异常 → 返回 success=False 并包含 error 信息。"""
        target = MagicMock()
        target.GetPattern.side_effect = RuntimeError("UIA error")

        result = executor.click(target, wait_time=0)

        assert result["success"] is False
        assert "UIA error" in result["error"]


# ── type_text 测试 ─────────────────────────────────────────────


class TestTypeText:
    """测试 type_text 方法。"""

    def _make_target(self, mock_auto, has_value=True, has_rect=True):
        """创建 mock target 元素。"""
        target = MagicMock()

        if has_value:
            value_pattern = MagicMock()
            value_pattern.IsReadOnly = False
            target.GetPattern.return_value = value_pattern
        else:
            target.GetPattern.return_value = None

        if has_rect:
            rect = MagicMock()
            rect.left = 100
            rect.top = 200
            rect.right = 300
            rect.bottom = 400
            target.BoundingRectangle = rect
        else:
            target.BoundingRectangle = None

        return target

    def test_type_value_method(self, executor, mock_auto):
        """value 方法 → 使用 ValuePattern.SetValue。"""
        target = self._make_target(mock_auto, has_value=True)
        result = executor.type_text(target, text="hello", method="value", clear_first=True, wait_time=0)

        assert result["success"] is True
        assert result["action"] == "type_text"
        assert result["method"] == "value"
        assert result["text_length"] == 5

        # 验证 SetValue 被调用：先清空，再设置
        value_pattern = target.GetPattern.return_value
        assert value_pattern.SetValue.call_count == 2
        value_pattern.SetValue.assert_any_call("")
        value_pattern.SetValue.assert_any_call("hello")

    def test_type_value_no_clear(self, executor, mock_auto):
        """value 方法、clear_first=False → 不应调用 SetValue("")。"""
        target = self._make_target(mock_auto, has_value=True)
        result = executor.type_text(target, text="hello", method="value", clear_first=False, wait_time=0)

        assert result["success"] is True
        value_pattern = target.GetPattern.return_value
        # 只调用一次 SetValue（设置文本），不调用 SetValue("")
        value_pattern.SetValue.assert_called_once_with("hello")

    def test_type_value_fallback_to_sendkeys(self, executor, mock_auto):
        """value 方法但无 ValuePattern → 回退到 SendKeys。"""
        target = self._make_target(mock_auto, has_value=False)
        result = executor.type_text(target, text="hi", method="value", clear_first=True, wait_time=0)

        assert result["success"] is True
        # 验证 SendKeys 被调用
        target.SendKeys.assert_called()

    def test_type_sendkeys_method(self, executor, mock_auto):
        """sendkeys 方法 → 使用 SendKeys。"""
        target = self._make_target(mock_auto, has_value=True)
        result = executor.type_text(target, text="abc", method="sendkeys", clear_first=True, wait_time=0)

        assert result["success"] is True
        assert result["method"] == "sendkeys"
        # 应有两次 SendKeys 调用：清空 + 输入
        assert target.SendKeys.call_count == 2

    def test_type_sendkeys_no_clear(self, executor, mock_auto):
        """sendkeys 方法、clear_first=False → 只调用一次 SendKeys。"""
        target = self._make_target(mock_auto, has_value=True)
        result = executor.type_text(target, text="abc", method="sendkeys", clear_first=False, wait_time=0)

        assert result["success"] is True
        target.SendKeys.assert_called_once()

    def test_type_unknown_method(self, executor, mock_auto):
        """未知输入方法 → 返回失败。"""
        target = self._make_target(mock_auto)
        result = executor.type_text(target, text="x", method="unknown", wait_time=0)

        assert result["success"] is False
        assert "未知的输入方法" in result["error"]

    def test_type_target_none(self, executor, mock_auto):
        """target 为 None → 返回失败。"""
        result = executor.type_text(None, text="x", wait_time=0)

        assert result["success"] is False
        assert "未找到目标元素" in result["error"]

    def test_type_dict_insufficient_info(self, executor, mock_auto):
        """dict 元素信息不足 → 返回"元素信息不足"。"""
        element = {"control_type": "Edit"}
        result = executor.type_text(element, text="x", wait_time=0)

        assert result["success"] is False
        assert "元素信息不足" in result["error"]


# ── scroll 测试 ────────────────────────────────────────────────


class TestScroll:
    """测试 scroll 方法。"""

    def _make_target_with_scroll(self, mock_auto):
        """创建带 ScrollPattern 的 mock target。"""
        target = MagicMock()
        scroll_pattern = MagicMock()
        target.GetPattern.return_value = scroll_pattern
        return target, scroll_pattern

    def _make_target_without_scroll(self, mock_auto, has_rect=True):
        """创建无 ScrollPattern 的 mock target（回退到鼠标滚轮）。"""
        target = MagicMock()
        target.GetPattern.return_value = None

        if has_rect:
            rect = MagicMock()
            rect.left = 100
            rect.top = 200
            rect.right = 300
            rect.bottom = 400
            target.BoundingRectangle = rect
        else:
            target.BoundingRectangle = None

        return target

    # ── ScrollPattern 路径：4 方向 x small/large ──

    def test_scroll_down_small(self, executor, mock_auto):
        """向下小幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="down", amount="small", count=1)

        assert result["success"] is True
        assert result["action"] == "scroll"
        assert result["direction"] == "down"
        assert result["amount"] == "small"
        sp.ScrollSmallDown.assert_called_once()

    def test_scroll_down_large(self, executor, mock_auto):
        """向下大幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="down", amount="large", count=1)

        assert result["success"] is True
        sp.ScrollLargeDown.assert_called_once()

    def test_scroll_up_small(self, executor, mock_auto):
        """向上小幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="up", amount="small", count=1)

        assert result["success"] is True
        sp.ScrollSmallUp.assert_called_once()

    def test_scroll_up_large(self, executor, mock_auto):
        """向上大幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="up", amount="large", count=1)

        assert result["success"] is True
        sp.ScrollLargeUp.assert_called_once()

    def test_scroll_left_small(self, executor, mock_auto):
        """向左小幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="left", amount="small", count=1)

        assert result["success"] is True
        sp.ScrollSmallLeft.assert_called_once()

    def test_scroll_left_large(self, executor, mock_auto):
        """向左大幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="left", amount="large", count=1)

        assert result["success"] is True
        sp.ScrollLargeLeft.assert_called_once()

    def test_scroll_right_small(self, executor, mock_auto):
        """向右小幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="right", amount="small", count=1)

        assert result["success"] is True
        sp.ScrollSmallRight.assert_called_once()

    def test_scroll_right_large(self, executor, mock_auto):
        """向右大幅滚动。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="right", amount="large", count=1)

        assert result["success"] is True
        sp.ScrollLargeRight.assert_called_once()

    def test_scroll_count_greater_than_one(self, executor, mock_auto):
        """count > 1 → 应调用对应方法 count 次。"""
        target, sp = self._make_target_with_scroll(mock_auto)
        result = executor.scroll(target, direction="down", amount="small", count=3)

        assert result["success"] is True
        assert result["count"] == 3
        assert sp.ScrollSmallDown.call_count == 3

    # ── 回退到鼠标滚轮 ──

    def test_scroll_fallback_mouse_wheel_down(self, executor, mock_auto):
        """无 ScrollPattern，回退到鼠标滚轮向下。"""
        target = self._make_target_without_scroll(mock_auto, has_rect=True)
        result = executor.scroll(target, direction="down", amount="small", count=1)

        assert result["success"] is True
        mock_auto.MoveTo.assert_called_once_with(200, 300)
        # ScrollWheel 第二个参数 isHorizontal=False
        mock_auto.ScrollWheel.assert_called_once_with(120, isHorizontal=False)

    def test_scroll_fallback_mouse_wheel_up(self, executor, mock_auto):
        """无 ScrollPattern，回退到鼠标滚轮向上（负值）。"""
        target = self._make_target_without_scroll(mock_auto, has_rect=True)
        result = executor.scroll(target, direction="up", amount="small", count=1)

        assert result["success"] is True
        mock_auto.ScrollWheel.assert_called_once_with(-120, isHorizontal=False)

    def test_scroll_fallback_mouse_wheel_left(self, executor, mock_auto):
        """无 ScrollPattern，回退到鼠标滚轮向左（负值、水平）。"""
        target = self._make_target_without_scroll(mock_auto, has_rect=True)
        result = executor.scroll(target, direction="left", amount="large", count=1)

        assert result["success"] is True
        mock_auto.ScrollWheel.assert_called_once_with(-360, isHorizontal=True)

    def test_scroll_fallback_mouse_wheel_right(self, executor, mock_auto):
        """无 ScrollPattern，回退到鼠标滚轮向右（正值、水平）。"""
        target = self._make_target_without_scroll(mock_auto, has_rect=True)
        result = executor.scroll(target, direction="right", amount="large", count=1)

        assert result["success"] is True
        mock_auto.ScrollWheel.assert_called_once_with(360, isHorizontal=True)

    def test_scroll_no_pattern_no_rect(self, executor, mock_auto):
        """无 ScrollPattern 且无坐标 → 返回失败。"""
        target = self._make_target_without_scroll(mock_auto, has_rect=False)
        result = executor.scroll(target, direction="down", amount="small", count=1)

        assert result["success"] is False
        assert "ScrollPattern" in result["error"]

    def test_scroll_target_none(self, executor, mock_auto):
        """target 为 None → 返回失败。"""
        result = executor.scroll(None, direction="down", amount="small", count=1)

        assert result["success"] is False
        assert "未找到目标元素" in result["error"]


# ── get_element_state 测试 ────────────────────────────────────


class TestGetElementState:
    """测试 get_element_state 方法。"""

    def _make_target(self, mock_auto, has_toggle=True, has_expand=True, has_value=True):
        """创建 mock target 元素。"""
        target = MagicMock()
        target.Name = "TestButton"
        target.IsEnabled = True
        target.IsOffscreen = False
        target.IsKeyboardFocusable = True
        target.HasKeyboardFocus = False

        # GetPattern 返回值根据调用参数不同
        pattern_map = {}
        if has_toggle:
            toggle_pattern = MagicMock()
            toggle_pattern.ToggleState = 0
            pattern_map[mock_auto.PatternToggle] = toggle_pattern
        if has_expand:
            expand_pattern = MagicMock()
            expand_pattern.ExpandCollapseState = 1
            pattern_map[mock_auto.PatternExpandCollapse] = expand_pattern
        if has_value:
            value_pattern = MagicMock()
            value_pattern.Value = "test_value"
            pattern_map[mock_auto.PatternValue] = value_pattern

        def get_pattern_side_effect(pattern_id):
            return pattern_map.get(pattern_id)

        target.GetPattern.side_effect = get_pattern_side_effect
        return target

    def test_get_state_basic(self, executor, mock_auto):
        """获取基本元素状态。"""
        target = self._make_target(mock_auto)
        result = executor.get_element_state(target)

        assert result["success"] is True
        state = result["state"]
        assert state["name"] == "TestButton"
        assert state["is_enabled"] is True
        assert state["is_visible"] is True
        assert state["is_focusable"] is True
        assert state["has_focus"] is False

    def test_get_state_with_patterns(self, executor, mock_auto):
        """获取包含 Toggle/Expand/Value Pattern 的状态。"""
        target = self._make_target(mock_auto, has_toggle=True, has_expand=True, has_value=True)
        result = executor.get_element_state(target)

        assert result["success"] is True
        state = result["state"]
        assert "toggle_state" in state
        assert "expand_state" in state
        assert "value" in state
        assert state["value"] == "test_value"

    def test_get_state_no_patterns(self, executor, mock_auto):
        """元素无任何 Pattern → 不应包含 toggle_state/expand_state/value。"""
        target = self._make_target(mock_auto, has_toggle=False, has_expand=False, has_value=False)
        result = executor.get_element_state(target)

        assert result["success"] is True
        state = result["state"]
        assert "toggle_state" not in state
        assert "expand_state" not in state
        assert "value" not in state

    def test_get_state_target_none(self, executor, mock_auto):
        """target 为 None → 返回失败。"""
        result = executor.get_element_state(None)

        assert result["success"] is False
        assert "未找到目标元素" in result["error"]

    def test_get_state_dict_with_automation_id(self, executor, mock_auto):
        """dict 元素有 automation_id → 应通过 FindControl 查找。"""
        mock_target = self._make_target(mock_auto)
        mock_auto.FindControl.return_value = mock_target

        element = {"automation_id": "btn1"}
        result = executor.get_element_state(element)

        assert result["success"] is True
        mock_auto.FindControl.assert_called_once()

    def test_get_state_dict_with_name(self, executor, mock_auto):
        """dict 元素有 name 但无 automation_id → 应通过 name 查找。"""
        mock_target = self._make_target(mock_auto)
        mock_auto.FindControl.return_value = mock_target

        element = {"name": "OK"}
        result = executor.get_element_state(element)

        assert result["success"] is True
        mock_auto.FindControl.assert_called_once()

    def test_get_state_dict_insufficient_info(self, executor, mock_auto):
        """dict 元素信息不足 → 返回"元素信息不足"。"""
        element = {"control_type": "Button"}
        result = executor.get_element_state(element)

        assert result["success"] is False
        assert "元素信息不足" in result["error"]

    def test_get_state_dict_findcontrol_returns_none(self, executor, mock_auto):
        """dict 元素通过 FindControl 查找但返回 None → 返回"未找到目标元素"。"""
        mock_auto.FindControl.return_value = None

        element = {"automation_id": "missing"}
        result = executor.get_element_state(element)

        assert result["success"] is False
        assert "未找到目标元素" in result["error"]

    def test_get_state_exception_handling(self, executor, mock_auto):
        """获取状态时抛出异常 → 返回 success=False。"""
        target = MagicMock()
        type(target).Name = PropertyMock(side_effect=RuntimeError("access denied"))

        result = executor.get_element_state(target)

        assert result["success"] is False
        assert "access denied" in result["error"]

    def test_get_state_pattern_exception_is_swallowed(self, executor, mock_auto):
        """获取 Pattern 状态时抛出异常 → 应被吞掉，不影响整体结果。"""
        target = MagicMock()
        target.Name = "TestButton"
        target.IsEnabled = True
        target.IsOffscreen = False
        target.IsKeyboardFocusable = False
        target.HasKeyboardFocus = False

        # GetPattern 对于 PatternToggle 抛出异常
        def get_pattern_side_effect(pattern_id):
            if pattern_id == mock_auto.PatternToggle:
                raise RuntimeError("pattern error")
            return None

        target.GetPattern.side_effect = get_pattern_side_effect

        result = executor.get_element_state(target)

        # 应该成功，toggle_state 被忽略
        assert result["success"] is True
        assert "toggle_state" not in result["state"]
