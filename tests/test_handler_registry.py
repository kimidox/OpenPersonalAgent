"""
Handler 注册表单元测试

覆盖 base_tool/handlers 的核心功能：
- Handler 注册和查找
- 18 个 Handler 全部注册验证
- execute_atomic_tool 分发逻辑
- 未知工具名处理
"""
import sys
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from base_tool.handlers import (
    register_handler,
    get_handler,
    get_all_handlers,
    ensure_registered,
    _HANDLER_REGISTRY,
)
from base_tool.handlers.base import ToolHandler
from base_tool.context import ToolContext
from base_tool.dispatch import execute_atomic_tool


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="class")
def _ensure_handlers_registered():
    """确保所有 handler 已注册（替代 setUpClass）"""
    ensure_registered()


@pytest.fixture
def tool_context():
    """创建测试上下文（替代 setUp）"""
    return ToolContext(work_dir=str(Path.home()))


class TestHandlerRegistry:
    """Handler 注册表核心功能测试"""

    def test_all_18_handlers_registered(self):
        """验证 18 个 Handler 全部注册"""
        handlers = get_all_handlers()
        assert len(handlers) == 18, f"期望 18 个 Handler，实际 {len(handlers)}"

    def test_expected_handler_names(self):
        """验证所有预期的 Handler 名称都已注册"""
        expected_names = {
            "file_operation",
            "edit",
            "run_command",
            "create_scheduled_task",
            "list_scheduled_tasks",
            "delete_scheduled_task",
            "uploaded_files",
            "get_accessibility_tree",
            "find_element",
            "click_element",
            "type_text",
            "scroll_element",
            "get_element_state",
            "start_application",
            "list_installed_apps",
            "send_hotkey",
            "install_skill_from_zip",
            "manage_skill",
        }
        actual_names = set(get_all_handlers().keys())
        assert actual_names == expected_names, (
            f"缺少: {expected_names - actual_names}, 多余: {actual_names - expected_names}"
        )

    def test_get_handler_returns_correct_instance(self):
        """验证 get_handler 返回正确类型的 Handler"""
        handler = get_handler("file_operation")
        assert handler is not None
        assert handler.name == "file_operation"

    def test_get_handler_unknown_returns_none(self):
        """验证未知工具名返回 None"""
        handler = get_handler("nonexistent_tool")
        assert handler is None

    def test_handler_is_toolhandler_subclass(self):
        """验证所有 Handler 都是 ToolHandler 子类"""
        for name, handler in get_all_handlers().items():
            assert isinstance(handler, ToolHandler), f"{name} 不是 ToolHandler 的实例"


class TestDispatchRegistry:
    """execute_atomic_tool 注册表分发测试"""

    def test_file_operation_dispatch(self, tool_context):
        """验证 file_operation 工具正确分发"""
        result = execute_atomic_tool("file_operation", {"action": "list", "path": "."}, tool_context, None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_edit_missing_params(self, tool_context):
        """验证 edit 工具缺少参数时返回错误"""
        result = execute_atomic_tool("edit", {"path": ".", "old_str": "", "new_str": "x"}, tool_context, None)
        assert isinstance(result, str)
        assert "错误" in result

    def test_unknown_tool_returns_error(self, tool_context):
        """验证未知工具返回错误信息"""
        result = execute_atomic_tool("unknown_tool_xyz", {}, tool_context, None)
        assert result == "未知原子工具: unknown_tool_xyz"

    def test_dispatch_result_is_string(self, tool_context):
        """验证所有 Handler 返回字符串结果"""
        # 测试几个代表性工具
        test_cases = [
            ("file_operation", {"action": "list", "path": "."}),
        ]
        for name, args in test_cases:
            result = execute_atomic_tool(name, args, tool_context, None)
            assert isinstance(result, str), f"{name} 返回类型不是 str"


class TestToolContext:
    """ToolContext 数据类测试"""

    def test_default_values(self):
        """验证默认值"""
        ctx = ToolContext(work_dir="/tmp")
        assert ctx.work_dir == "/tmp"
        assert ctx.executor is None
        assert ctx.memory is None
        assert ctx.user_id == "default"
        assert ctx.conversation_id is None
        assert ctx.file_upload_controller is None

    def test_skip_ask_user_flag(self):
        """验证 run_command 跳过确认标志"""
        ctx = ToolContext(work_dir="/tmp")
        assert not ctx.should_skip_ask_user_for_run_command()
        ctx.set_skip_ask_user_for_run_command(True)
        assert ctx.should_skip_ask_user_for_run_command()
        ctx.set_skip_ask_user_for_run_command(False)
        assert not ctx.should_skip_ask_user_for_run_command()


class TestToolHandlerBase:
    """ToolHandler 抽象基类测试"""

    def test_cannot_instantiate_base(self):
        """验证 ToolHandler 不能直接实例化"""
        with pytest.raises(TypeError):
            ToolHandler()
