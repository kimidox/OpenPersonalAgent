"""accessibility 工具处理器

包含 UI 自动化相关的6个Handler:
- GetAccessibilityTreeHandler
- FindElementHandler
- ClickElementHandler
- TypeTextHandler
- ScrollElementHandler
- GetElementStateHandler
"""
from __future__ import annotations

import json

from .base import ToolHandler
from ..context import ToolContext
from . import register_handler


class GetAccessibilityTreeHandler(ToolHandler):
    """获取 Accessibility Tree 工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "get_accessibility_tree"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """获取指定窗口的 Accessibility Tree，若未指定窗口则返回系统活跃窗口列表

        Args:
            args: 工具参数字典，支持 window_title、process_id、max_depth、max_elements
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia

        if not _ensure_uia():
            return "错误: UI Automation 模块不可用，请确保已安装 uiautomation 库"

        # 检查停止条件
        from ..dispatch import get_controller
        controller = get_controller()
        check_result = controller.check_before_operation("get_accessibility_tree")
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        window_title = args.get("window_title", None)
        process_id = args.get("process_id", None)
        max_depth = args.get("max_depth", 5)
        max_elements = args.get("max_elements", 500)

        try:
            import uiautomation as auto
            import time

            start_time = time.time()

            # 如果没有指定窗口，返回所有活跃窗口列表
            if window_title is None and process_id is None:
                windows = []

                # 方法1: 使用Win32 API获取所有顶层窗口（更可靠）
                try:
                    import ctypes
                    from ctypes import wintypes

                    # 定义Win32 API函数
                    user32 = ctypes.windll.user32

                    # EnumWindows回调函数
                    def enum_windows_callback(hwnd, lParam):
                        try:
                            # 获取窗口标题
                            length = user32.GetWindowTextLengthW(hwnd)
                            if length > 0:
                                buffer = ctypes.create_unicode_buffer(length + 1)
                                user32.GetWindowTextW(hwnd, buffer, length + 1)
                                title = buffer.value
                            else:
                                title = ""

                            # 获取窗口类名
                            buffer = ctypes.create_unicode_buffer(256)
                            user32.GetClassNameW(hwnd, buffer, 256)
                            class_name = buffer.value

                            # 获取进程ID
                            pid = wintypes.DWORD()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            process_id = pid.value

                            # 检查窗口是否可见
                            is_visible = user32.IsWindowVisible(hwnd)

                            # 获取窗口边界
                            rect = wintypes.RECT()
                            user32.GetWindowRect(hwnd, ctypes.byref(rect))

                            # 过滤：只保留有标题且可见的窗口
                            if title and is_visible:
                                windows.append({
                                    "name": title,
                                    "class_name": class_name,
                                    "process_id": process_id,
                                    "handle": hwnd,
                                    "is_visible": is_visible,
                                    "bounding_rect": f"({rect.left}, {rect.top}, {rect.right}, {rect.bottom})",
                                    "width": rect.right - rect.left,
                                    "height": rect.bottom - rect.top,
                                })
                        except Exception:
                            pass
                        return True  # 继续枚举

                    # 定义回调函数类型
                    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

                    # 枚举所有顶层窗口
                    user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)

                except Exception as e:
                    # 如果Win32 API失败，fallback到uiautomation
                    try:
                        root = auto.GetRootControl()
                        for child in root.GetChildren():
                            try:
                                if child.ControlType == auto.ControlType.Window:
                                    rect = child.BoundingRectangle
                                    windows.append({
                                        "name": child.Name or "",
                                        "class_name": child.ClassName or "",
                                        "process_id": child.ProcessId,
                                        "handle": child.NativeWindowHandle if hasattr(child, 'NativeWindowHandle') else 0,
                                        "is_visible": not child.IsOffscreen,
                                        "bounding_rect": f"({rect.left}, {rect.top}, {rect.right}, {rect.bottom})",
                                        "width": rect.right - rect.left,
                                        "height": rect.bottom - rect.top,
                                    })
                            except Exception:
                                pass
                    except Exception:
                        pass

                # 过滤掉太小或隐藏的窗口（如工具栏、通知区域等）
                filtered_windows = []
                for win in windows:
                    width = win.get("width", 0)
                    height = win.get("height", 0)
                    # 只保留宽度>100且高度>100的窗口（过滤掉小窗口）
                    if width > 100 and height > 100:
                        filtered_windows.append(win)

                elapsed_ms = int((time.time() - start_time) * 1000)

                # 格式化输出
                output_lines = [f"当前系统活跃窗口列表（共 {len(filtered_windows)} 个）:"]
                output_lines.append("")
                output_lines.append("【窗口列表】")
                for i, win in enumerate(filtered_windows, 1):
                    name = win.get("name", "")[:50]  # 截断长标题
                    pid = win.get("process_id", 0)
                    handle = win.get("handle", 0)
                    class_name = win.get("class_name", "")
                    bounding_rect = win.get("bounding_rect", "")

                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 进程ID: {pid}")
                    output_lines.append(f"   - 窗口句柄: {handle} (0x{handle:X})")
                    output_lines.append(f"   - 类名: {class_name}")
                    output_lines.append(f"   - 边界: {bounding_rect}")
                    output_lines.append(f"   - 尺寸: {win.get('width', 0)}x{win.get('height', 0)}")
                    output_lines.append("")

                output_lines.append("【建议】")
                output_lines.append("如需查看某个窗口的详细UI结构，请使用:")
                output_lines.append("get_accessibility_tree(window_title='窗口名称')")
                output_lines.append("或 get_accessibility_tree(process_id=进程ID)")

                # 添加任务状态信息
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")

                return "\n".join(output_lines) + f"\n\n耗时: {elapsed_ms}ms\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            # 如果指定了窗口，返回该窗口的详细Accessibility Tree
            from ..dispatch import AccessibilityTreeParser
            parser = AccessibilityTreeParser()
            result = parser.parse_window(
                window_title=window_title,
                process_id=process_id,
                max_depth=max_depth,
                max_elements=max_elements,
            )

            if result.get("success"):
                # 返回 LLM 易读格式
                llm_readable = parser.to_llm_readable(result)
                # 添加任务状态信息
                status_summary = controller.get_status_summary()
                return llm_readable + f"\n\n【任务状态】{status_summary}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                # 记录失败
                failure_info = controller.record_failure("get_accessibility_tree", result.get("error", "未知错误"))
                return f"错误: {result.get('error', '未知错误')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"
        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure("get_accessibility_tree", str(e))
            return f"错误: 获取 Accessibility Tree 失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"


class FindElementHandler(ToolHandler):
    """查找元素工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "find_element"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """通过指定方法查找 UI 元素，支持带重试的查找策略

        Args:
            args: 工具参数字典，支持 method、query、window_title、max_results
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia

        if not _ensure_uia():
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
        from ..dispatch import get_controller
        controller = get_controller()
        check_result = controller.check_before_operation("find_element")
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        method = args.get("method", "")
        query = args.get("query", "")
        window_title = args.get("window_title", None)
        max_results = args.get("max_results", 50)

        if not method or not query:
            return "错误: 缺少 method 或 query 参数"

        try:
            from ..dispatch import ElementFinder, get_tracker
            finder = ElementFinder()
            tracker = get_tracker()

            # 使用带重试的查找方法
            result = finder.find_element_with_retry(
                method=method,
                query=query,
                window_title=window_title,
                max_retries=3,
                element_name=query,
            )

            if result.get("success"):
                # 格式化输出
                output_lines = []

                if "results" in result:
                    elements = result["results"]
                    output_lines.append(f"找到 {len(elements)} 个元素:")
                    for elem in elements:
                        output_lines.append(
                            f"- [{elem.get('control_type', 'Unknown')}] {elem.get('name', '')}"
                            f" (id: {elem.get('automation_id', '')})"
                        )
                elif "result" in result:
                    elem = result["result"]
                    output_lines.append("找到元素:")
                    output_lines.append(f"- 类型: {elem.get('control_type', 'Unknown')}")
                    output_lines.append(f"- 名称: {elem.get('name', '')}")
                    output_lines.append(f"- AutomationId: {elem.get('automation_id', '')}")
                    output_lines.append(f"- 边界: {elem.get('bounding_rectangle', (0, 0, 0, 0))}")
                    output_lines.append(f"- Patterns: {', '.join(elem.get('patterns', []))}")

                # 添加方法信息
                output_lines.append("")
                output_lines.append(f"使用方法: {result.get('used_method', method)}")
                if result.get('retry_count', 0) > 0:
                    output_lines.append(f"重试次数: {result.get('retry_count', 0)}")

                # 添加历史统计推荐
                recommendation = tracker.get_recommendation("find_methods")
                if recommendation:
                    output_lines.append("")
                    output_lines.append(recommendation)

                # 添加任务状态信息
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")

                return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                # 记录失败
                failure_info = controller.record_failure(f"find_element_{query}", result.get("error", "未找到元素"))

                output_lines = [f"错误: {result.get('error', '未找到元素')}"]

                # 显示尝试的方法
                if result.get("tried_methods"):
                    output_lines.append("")
                    output_lines.append("尝试的方法:")
                    for m in result["tried_methods"]:
                        output_lines.append(f"- {m['method']}: {m['error']}")

                # 添加推荐
                if result.get("recommendation"):
                    output_lines.append("")
                    output_lines.append(result["recommendation"])

                # 添加停止原因和失败统计
                if failure_info.get("stop_reason"):
                    output_lines.append("")
                    output_lines.append(failure_info["stop_reason"])

                output_lines.append("")
                output_lines.append(f"【失败统计】{controller.failure_counter.get_status_summary()}")

                return "\n".join(output_lines)
        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure("find_element", str(e))
            return f"错误: 查找元素失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"


class ClickElementHandler(ToolHandler):
    """点击元素工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "click_element"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """点击指定 UI 元素，支持幻觉检测和操作后验证

        Args:
            args: 工具参数字典，支持 element、method、wait_time、window_title
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia

        if not _ensure_uia():
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
        from ..dispatch import get_controller
        controller = get_controller()
        step_id = f"click_{args.get('element', '')}"
        check_result = controller.check_before_operation(step_id)
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        element = args.get("element", "")
        method = args.get("method", "invoke")
        wait_time = args.get("wait_time", 0.1)
        window_title = args.get("window_title", None)

        if not element:
            return "错误: 缺少 element 参数"

        try:
            from ..dispatch import ActionExecutor, get_tracker
            executor = ActionExecutor()
            tracker = get_tracker()

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                # JSON 格式
                element_info = json.loads(element)

            # 【幻觉检测】先验证操作可行性
            feasible_result = executor.verify_operation_feasible(element_info, "click")
            if not feasible_result.get("feasible"):
                failure_info = controller.record_failure(step_id, feasible_result.get("reason", "操作不可行"))
                return f"【幻觉检测】{feasible_result.get('reason', '操作不可行')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"

            # 使用带验证的点击方法
            result = executor.click_with_verification(element_info, method=method, wait_time=wait_time)

            # 记录统计
            tracker.record_operation_attempt("click", method, result.get("success", False), element)

            if result.get("success"):
                output_lines = [f"点击成功 (方法: {method})"]

                # 显示验证结果
                if result.get("verification"):
                    verify = result["verification"]
                    if verify.get("verified"):
                        output_lines.append(f"验证: {verify.get('reason', '已验证')}")
                    else:
                        output_lines.append(f"验证: {verify.get('reason', '无法验证，但操作可能已成功')}")

                # 添加历史统计推荐
                recommendation = tracker.get_recommendation("operations")
                if recommendation:
                    output_lines.append("")
                    output_lines.append(recommendation)

                # 添加任务状态信息
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")

                return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                # 记录失败
                failure_info = controller.record_failure(step_id, result.get("error", "点击失败"))

                output_lines = [f"错误: {result.get('error', '点击失败')}"]

                # 显示验证结果
                if result.get("verification"):
                    output_lines.append(f"验证: {result['verification'].get('reason', '')}")

                # 添加停止原因和失败统计
                if failure_info.get("stop_reason"):
                    output_lines.append("")
                    output_lines.append(failure_info["stop_reason"])

                output_lines.append("")
                output_lines.append(f"【失败统计】{controller.failure_counter.get_status_summary()}")

                return "\n".join(output_lines)
        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure(step_id, str(e))
            return f"错误: 点击元素失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"


class TypeTextHandler(ToolHandler):
    """输入文本工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "type_text"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """向指定 UI 元素输入文本，支持幻觉检测和输入后验证

        Args:
            args: 工具参数字典，支持 element、text、method、clear_first、wait_time、window_title
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia

        if not _ensure_uia():
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
        from ..dispatch import get_controller
        controller = get_controller()
        step_id = f"type_{args.get('element', '')}"
        check_result = controller.check_before_operation(step_id)
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        element = args.get("element", "")
        text = args.get("text", "")
        method = args.get("method", "value")
        clear_first = args.get("clear_first", True)
        wait_time = args.get("wait_time", 0.1)
        window_title = args.get("window_title", None)

        if not element or not text:
            return "错误: 缺少 element 或 text 参数"

        try:
            from ..dispatch import ActionExecutor, get_tracker
            executor = ActionExecutor()
            tracker = get_tracker()

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                element_info = json.loads(element)

            # 【幻觉检测】先验证操作可行性
            feasible_result = executor.verify_operation_feasible(element_info, "type")
            if not feasible_result.get("feasible"):
                failure_info = controller.record_failure(step_id, feasible_result.get("reason", "操作不可行"))
                return f"【幻觉检测】{feasible_result.get('reason', '操作不可行')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"

            # 使用带验证的输入方法
            result = executor.type_with_verification(
                element=element_info,
                text=text,
                method=method,
                clear_first=clear_first,
                wait_time=wait_time,
            )

            # 记录统计
            tracker.record_operation_attempt("type_text", method, result.get("success", False), element)

            if result.get("success"):
                output_lines = [f"输入成功 (方法: {method}, 文本长度: {len(text)})"]

                # 显示验证结果
                if result.get("verification"):
                    verify = result["verification"]
                    if verify.get("verified"):
                        output_lines.append(f"验证: {verify.get('reason', '已验证')}")
                        if verify.get("actual_value"):
                            output_lines.append(f"实际值: {verify['actual_value']}")

                # 添加历史统计推荐
                recommendation = tracker.get_recommendation("operations")
                if recommendation:
                    output_lines.append("")
                    output_lines.append(recommendation)

                # 添加任务状态信息
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")

                return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                # 记录失败
                failure_info = controller.record_failure(step_id, result.get("error", "输入失败"))

                output_lines = [f"错误: {result.get('error', '输入失败')}"]

                # 显示验证结果
                if result.get("verification"):
                    verify = result["verification"]
                    output_lines.append(f"验证: {verify.get('reason', '')}")
                    if verify.get("expected"):
                        output_lines.append(f"期望值: {verify['expected']}")
                    if verify.get("actual"):
                        output_lines.append(f"实际值: {verify['actual']}")

                # 添加停止原因和失败统计
                if failure_info.get("stop_reason"):
                    output_lines.append("")
                    output_lines.append(failure_info["stop_reason"])

                output_lines.append("")
                output_lines.append(f"【失败统计】{controller.failure_counter.get_status_summary()}")

                return "\n".join(output_lines)
        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure(step_id, str(e))
            return f"错误: 输入文本失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"


class ScrollElementHandler(ToolHandler):
    """滚动元素工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "scroll_element"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """滚动指定 UI 元素，支持方向、幅度和次数控制

        Args:
            args: 工具参数字典，支持 element、direction、amount、count、window_title
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia

        if not _ensure_uia():
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
        from ..dispatch import get_controller
        controller = get_controller()
        step_id = f"scroll_{args.get('element', '')}"
        check_result = controller.check_before_operation(step_id)
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        element = args.get("element", "")
        direction = args.get("direction", "down")
        amount = args.get("amount", "small")
        count = args.get("count", 1)
        window_title = args.get("window_title", None)

        if not element or not direction:
            return "错误: 缺少 element 或 direction 参数"

        try:
            from ..dispatch import ActionExecutor, get_tracker
            executor = ActionExecutor()
            tracker = get_tracker()

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                element_info = json.loads(element)

            # 【幻觉检测】先验证操作可行性
            feasible_result = executor.verify_operation_feasible(element_info, "scroll")
            if not feasible_result.get("feasible"):
                failure_info = controller.record_failure(step_id, feasible_result.get("reason", "操作不可行"))
                return f"【幻觉检测】{feasible_result.get('reason', '操作不可行')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"

            result = executor.scroll(
                element=element_info,
                direction=direction,
                amount=amount,
                count=count,
            )

            # 记录统计
            tracker.record_operation_attempt("scroll", "default", result.get("success", False), element)

            if result.get("success"):
                output_lines = [f"滚动成功 (方向: {direction}, 次数: {count})"]

                # 添加任务状态信息
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")

                return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                # 记录失败
                failure_info = controller.record_failure(step_id, result.get("error", "滚动失败"))
                return f"错误: {result.get('error', '滚动失败')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"
        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure(step_id, str(e))
            return f"错误: 滚动元素失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"


class GetElementStateHandler(ToolHandler):
    """获取元素状态工具处理器"""

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "get_element_state"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """获取指定 UI 元素的当前状态信息

        Args:
            args: 工具参数字典，支持 element、window_title
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        from ..dispatch import _ensure_uia

        if not _ensure_uia():
            return "错误: UI Automation 模块不可用"

        element = args.get("element", "")
        window_title = args.get("window_title", None)

        if not element:
            return "错误: 缺少 element 参数"

        try:
            from ..dispatch import ActionExecutor
            executor = ActionExecutor()

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                element_info = json.loads(element)

            result = executor.get_element_state(element=element_info)

            if result.get("success"):
                state = result.get("state", {})
                output_lines = ["元素状态:"]
                for key, value in state.items():
                    output_lines.append(f"- {key}: {value}")

                # 添加任务状态信息
                from ..dispatch import get_controller
                controller = get_controller()
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")

                return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: {result.get('error', '获取状态失败')}"
        except Exception as e:
            return f"错误: 获取元素状态失败: {e}"


# 注册所有 Handler
register_handler(GetAccessibilityTreeHandler())
register_handler(FindElementHandler())
register_handler(ClickElementHandler())
register_handler(TypeTextHandler())
register_handler(ScrollElementHandler())
register_handler(GetElementStateHandler())
