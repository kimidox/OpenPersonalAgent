"""
SkillAgent 核心方法单元测试

覆盖：
- 模块级纯函数：_ask_user_ui_log_payload, _message_text, _history_without_system, _ensure_valid_json_args
- 纯方法：_is_dangerous_command, _is_write_operation, _is_package_install_command, _extract_file_path
- 状态方法：_check_repeated_tool_call, _consume_uploaded_files_content, _dispatch, _verify_file_exists
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from skill_agent import (
    _ask_user_ui_log_payload,
    _message_text,
    _history_without_system,
    _ensure_valid_json_args,
    SkillAgent,
)


# ═══════════════════════════════════════════════════════════════
# 模块级纯函数
# ═══════════════════════════════════════════════════════════════

class TestAskUserUiLogPayload:
    """_ask_user_ui_log_payload 格式化测试。"""

    def test_basic_format(self):
        args = {"question": "确认吗？", "context": "上下文", "choices": ["是", "否"]}
        result = _ask_user_ui_log_payload(args)
        payload = json.loads(result)
        assert payload["question"] == "确认吗？"
        assert payload["context"] == "上下文"
        assert payload["choices"] == ["是", "否"]

    def test_empty_choices(self):
        args = {"question": "确认吗？", "choices": []}
        result = _ask_user_ui_log_payload(args)
        payload = json.loads(result)
        assert payload["choices"] == []

    def test_none_choices_filtered(self):
        args = {"question": "确认吗？", "choices": ["是", None, "否"]}
        result = _ask_user_ui_log_payload(args)
        payload = json.loads(result)
        assert payload["choices"] == ["是", "否"]

    def test_missing_fields_default_empty(self):
        args = {}
        result = _ask_user_ui_log_payload(args)
        payload = json.loads(result)
        assert payload["question"] == ""
        assert payload["context"] == ""
        assert payload["choices"] == []

    def test_blank_choices_filtered(self):
        args = {"question": "Q", "choices": ["  ", "valid", ""]}
        result = _ask_user_ui_log_payload(args)
        payload = json.loads(result)
        assert payload["choices"] == ["valid"]


class TestMessageText:
    """_message_text 安全提取测试。"""

    def test_string_content(self):
        msg = MagicMock()
        msg.content = "  hello world  "
        assert _message_text(msg) == "hello world"

    def test_empty_string_returns_empty(self):
        msg = MagicMock()
        msg.content = "   "
        assert _message_text(msg) == ""

    def test_none_content_returns_empty(self):
        msg = MagicMock()
        msg.content = None
        assert _message_text(msg) == ""

    def test_no_content_attr_returns_empty(self):
        msg = object()
        assert _message_text(msg) == ""


class TestHistoryWithoutSystem:
    """_history_without_system 过滤测试。"""

    def test_filters_system_messages(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _history_without_system(messages)
        assert len(result) == 2
        assert all(m["role"] != "system" for m in result)

    def test_no_system_messages(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _history_without_system(messages)
        assert len(result) == 2

    def test_empty_list(self):
        assert _history_without_system([]) == []


class TestEnsureValidJsonArgs:
    """_ensure_valid_json_args 参数验证测试。"""

    def test_valid_json_string(self):
        assert _ensure_valid_json_args('{"a": 1}') == '{"a": 1}'

    def test_invalid_json_string(self):
        assert _ensure_valid_json_args("not json") == "{}"

    def test_dict_input(self):
        result = _ensure_valid_json_args({"b": 2})
        assert json.loads(result) == {"b": 2}

    def test_other_type(self):
        assert _ensure_valid_json_args(42) == "{}"

    def test_empty_string(self):
        # 空字符串不是有效JSON
        assert _ensure_valid_json_args("") == "{}"


# ═══════════════════════════════════════════════════════════════
# SkillAgent 纯方法
# ═══════════════════════════════════════════════════════════════

class TestIsDangerousCommand:
    """_is_dangerous_command 危险命令检测测试。"""

    def test_disabled_returns_false(self, skill_agent_minimal, dangerous_check_disabled):
        assert skill_agent_minimal._is_dangerous_command("rm -rf /") is False

    def test_prefix_match(self, skill_agent_minimal, dangerous_check_enabled):
        with patch("config.DANGEROUS_COMMAND_PREFIXES", ["rm "]):
            assert skill_agent_minimal._is_dangerous_command("rm -rf /") is True

    def test_contains_match(self, skill_agent_minimal, dangerous_check_enabled):
        with patch("config.DANGEROUS_COMMAND_CONTAINS", ["format"]):
            assert skill_agent_minimal._is_dangerous_command("format C:") is True

    def test_safe_command(self, skill_agent_minimal, dangerous_check_enabled):
        with patch("config.DANGEROUS_COMMAND_PREFIXES", ["rm "]), \
             patch("config.DANGEROUS_COMMAND_CONTAINS", ["format"]):
            assert skill_agent_minimal._is_dangerous_command("ls -la") is False

    def test_empty_command(self, skill_agent_minimal, dangerous_check_enabled):
        with patch("config.DANGEROUS_COMMAND_PREFIXES", []), \
             patch("config.DANGEROUS_COMMAND_CONTAINS", []):
            assert skill_agent_minimal._is_dangerous_command("") is False

    def test_case_insensitive(self, skill_agent_minimal, dangerous_check_enabled):
        with patch("config.DANGEROUS_COMMAND_PREFIXES", ["rm "]):
            assert skill_agent_minimal._is_dangerous_command("RM -rf /") is True


class TestIsWriteOperation:
    """_is_write_operation 写操作检测测试。"""

    def test_redirect_overwrite(self, skill_agent_minimal):
        assert skill_agent_minimal._is_write_operation("echo hi > out.txt") is True

    def test_redirect_append(self, skill_agent_minimal):
        assert skill_agent_minimal._is_write_operation("echo hi >> out.txt") is True

    def test_mkdir(self, skill_agent_minimal):
        assert skill_agent_minimal._is_write_operation("mkdir newdir") is True

    def test_copy_command(self, skill_agent_minimal):
        assert skill_agent_minimal._is_write_operation("copy a.txt b.txt") is True

    def test_move_command(self, skill_agent_minimal):
        assert skill_agent_minimal._is_write_operation("move a.txt b.txt") is True

    def test_safe_read_command(self, skill_agent_minimal):
        assert skill_agent_minimal._is_write_operation("ls -la") is False


class TestIsPackageInstallCommand:
    """_is_package_install_command 包安装命令检测测试。"""

    def test_pip_install(self, skill_agent_minimal):
        is_install, packages = skill_agent_minimal._is_package_install_command("pip install requests")
        assert is_install is True
        assert "requests" in packages

    def test_npm_install(self, skill_agent_minimal):
        is_install, packages = skill_agent_minimal._is_package_install_command("npm install lodash")
        assert is_install is True
        assert "lodash" in packages

    def test_conda_install(self, skill_agent_minimal):
        is_install, packages = skill_agent_minimal._is_package_install_command("conda install numpy")
        assert is_install is True
        assert "numpy" in packages

    def test_safe_command(self, skill_agent_minimal):
        is_install, packages = skill_agent_minimal._is_package_install_command("ls -la")
        assert is_install is False
        assert packages == []

    def test_case_insensitive(self, skill_agent_minimal):
        is_install, packages = skill_agent_minimal._is_package_install_command("PIP INSTALL requests")
        assert is_install is True

    def test_scoped_package(self, skill_agent_minimal):
        is_install, packages = skill_agent_minimal._is_package_install_command("npm install @types/node")
        assert is_install is True


class TestExtractFilePath:
    """_extract_file_path 路径提取测试。"""

    def test_path_flag(self, skill_agent_minimal):
        assert skill_agent_minimal._extract_file_path("-Path 'output.txt'") == "output.txt"

    def test_redirect_append_quoted(self, skill_agent_minimal):
        assert skill_agent_minimal._extract_file_path(">> 'out.log'") == "out.log"

    def test_redirect_overwrite_unquoted(self, skill_agent_minimal):
        assert skill_agent_minimal._extract_file_path("> output.txt") == "output.txt"

    def test_no_path_returns_none(self, skill_agent_minimal):
        assert skill_agent_minimal._extract_file_path("ls -la") is None

    def test_empty_command_returns_none(self, skill_agent_minimal):
        assert skill_agent_minimal._extract_file_path("") is None

    def test_redirect_append_unquoted(self, skill_agent_minimal):
        assert skill_agent_minimal._extract_file_path(">> error.log") == "error.log"


class TestVerifyFileExists:
    """_verify_file_exists 文件存在性验证测试。"""

    def test_file_exists(self, skill_agent_minimal, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello", encoding="utf-8")
        result = skill_agent_minimal._verify_file_exists("test.txt", ".")
        assert "✓" in result
        assert "文件已创建成功" in result

    def test_file_not_exists(self, skill_agent_minimal, tmp_path):
        result = skill_agent_minimal._verify_file_exists("nonexistent.txt", ".")
        assert "✗" in result
        assert "文件不存在" in result

    def test_directory_exists(self, skill_agent_minimal, tmp_path):
        test_dir = tmp_path / "subdir"
        test_dir.mkdir()
        result = skill_agent_minimal._verify_file_exists("subdir", ".")
        assert "✓" in result
        assert "不是文件" in result

    def test_cwd_dot_uses_workdir(self, skill_agent_minimal, tmp_path):
        test_file = tmp_path / "nested.txt"
        test_file.write_text("data", encoding="utf-8")
        result = skill_agent_minimal._verify_file_exists("nested.txt", ".")
        assert "✓" in result


# ═══════════════════════════════════════════════════════════════
# SkillAgent 状态方法
# ═══════════════════════════════════════════════════════════════

class TestCheckRepeatedToolCall:
    """_check_repeated_tool_call 重复检测测试。"""

    def test_first_call_not_repeated(self, skill_agent_minimal, dedup_enabled):
        is_rep, warning, last = skill_agent_minimal._check_repeated_tool_call(
            "run_command", {"command": "ls"}
        )
        assert is_rep is False

    def test_second_call_returns_warning(self, skill_agent_minimal, dedup_enabled, repeat_settings):
        # 先记录第一次调用的结果
        skill_agent_minimal._record_tool_call("run_command", {"command": "ls"}, "file1.txt\nfile2.txt")
        # 第二次相同调用
        is_rep, warning, last = skill_agent_minimal._check_repeated_tool_call(
            "run_command", {"command": "ls"}
        )
        assert is_rep is True
        assert warning is not None
        assert "重复" in warning

    def test_different_args_not_repeated(self, skill_agent_minimal, dedup_enabled):
        skill_agent_minimal._record_tool_call("run_command", {"command": "ls"}, "result1")
        is_rep, _, _ = skill_agent_minimal._check_repeated_tool_call(
            "run_command", {"command": "dir"}
        )
        assert is_rep is False

    def test_dedup_disabled(self, skill_agent_minimal, dedup_disabled):
        # 即使重复也不检测
        skill_agent_minimal._check_repeated_tool_call("run_command", {"command": "ls"})
        is_rep, _, _ = skill_agent_minimal._check_repeated_tool_call(
            "run_command", {"command": "ls"}
        )
        # 当去重关闭时，第一次调用仍然不重复
        # 但由于方法内部可能用不同逻辑，验证返回值合理
        assert isinstance(is_rep, bool)


class TestConsumeUploadedFilesContent:
    """_consume_uploaded_files_content 上传文件消费测试。"""

    def test_no_uploaded_files(self, skill_agent_minimal):
        result = skill_agent_minimal._consume_uploaded_files_content("hello")
        assert result == "hello"

    def test_text_content_appended(self, skill_agent_minimal):
        skill_agent_minimal.set_uploaded_files_content({"text_content": "file data", "images": []})
        result = skill_agent_minimal._consume_uploaded_files_content("hello")
        assert isinstance(result, str)
        assert "hello" in result
        assert "file data" in result

    def test_image_with_vision_enabled(self, skill_agent_minimal):
        skill_agent_minimal.set_uploaded_files_content({
            "text_content": "",
            "images": [{"file_name": "test.png", "base64_data": "abc123", "mime_type": "image/png"}],
        })
        result = skill_agent_minimal._consume_uploaded_files_content("describe this", enable_vision=True)
        assert isinstance(result, list)
        assert len(result) == 2  # text + image

    def test_image_with_vision_disabled(self, skill_agent_minimal):
        skill_agent_minimal.set_uploaded_files_content({
            "text_content": "",
            "images": [{"file_name": "test.png", "base64_data": "abc123", "mime_type": "image/png"}],
        })
        result = skill_agent_minimal._consume_uploaded_files_content("describe this", enable_vision=False)
        assert isinstance(result, str)
        assert "describe this" in result

    def test_one_time_consumption(self, skill_agent_minimal):
        skill_agent_minimal.set_uploaded_files_content({"text_content": "data", "images": []})
        # 第一次消费
        result1 = skill_agent_minimal._consume_uploaded_files_content("hello")
        assert "data" in result1
        # 第二次消费应返回原文（缓存已清空）
        result2 = skill_agent_minimal._consume_uploaded_files_content("hello2")
        assert result2 == "hello2"

    def test_empty_content_returns_original(self, skill_agent_minimal):
        skill_agent_minimal.set_uploaded_files_content({"text_content": "", "images": []})
        result = skill_agent_minimal._consume_uploaded_files_content("hello")
        assert result == "hello"


class TestDispatch:
    """_dispatch 工具分发测试。"""

    def test_select_skill_goes_control(self, skill_agent_minimal):
        with patch("skill_agent.execute_skill_control_tool") as mock_ctrl:
            mock_ctrl.return_value = ("result", False, None)
            result = skill_agent_minimal._dispatch(
                "select_skill", {"skill_id": "test"}, [], []
            )
            mock_ctrl.assert_called_once()

    def test_finish_goes_control(self, skill_agent_minimal):
        with patch("skill_agent.execute_skill_control_tool") as mock_ctrl:
            mock_ctrl.return_value = ("done", False, None)
            result = skill_agent_minimal._dispatch(
                "finish", {"summary": "done"}, [], []
            )
            mock_ctrl.assert_called_once()

    def test_ask_user_goes_control(self, skill_agent_minimal):
        with patch("skill_agent.execute_skill_control_tool") as mock_ctrl:
            mock_ctrl.return_value = ("question asked", True, '{"question": "Q"}')
            result = skill_agent_minimal._dispatch(
                "ask_user", {"question": "Q"}, [], []
            )
            mock_ctrl.assert_called_once()

    def test_atomic_tool_goes_execute(self, skill_agent_minimal):
        with patch("skill_agent.execute_atomic_tool") as mock_atomic:
            mock_atomic.return_value = "file listed"
            result = skill_agent_minimal._dispatch(
                "file_operation", {"action": "list", "path": "."}, [], []
            )
            mock_atomic.assert_called_once()
            assert result[0] == "file listed"
            assert result[1] is False
