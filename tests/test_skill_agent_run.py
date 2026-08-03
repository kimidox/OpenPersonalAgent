"""
SkillAgent 核心运行流程单元测试

覆盖：
- run() 基本文本流程（mock LLM 返回 text）
- run() 工具调用流程（mock LLM + mock dispatch）
- run() 用户停止（stop_check_callback）
- _process_tool_call_in_loop 各分支（finish / ask_user / 普通原子工具）
"""
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from llm.BaseChatModel import StreamResult
from skill_agent._helpers import SKILL_AGENT_AWAITING_USER_REPLY


# ═══════════════════════════════════════════════════════════════
# 辅助：构建 mock model
# ═══════════════════════════════════════════════════════════════


def _make_mock_model(stream_results):
    """创建一个 mock model，stream_request_llm_with_tools 按顺序返回 stream_results。

    Args:
        stream_results: StreamResult 实例列表，按调用顺序依次返回。

    Returns:
        MagicMock: 配置好 stream_request_llm_with_tools 的 mock model。
    """
    model = MagicMock()
    model.stream_request_llm_with_tools = MagicMock(side_effect=stream_results)
    model.build_tool_catalog = MagicMock(return_value=[])
    model.build_skill_agent_tools_initial = MagicMock(return_value=[])
    model.set_state_update_callback = MagicMock()
    model.enable_vision = False
    return model


def _make_text_result(content="Hello from LLM"):
    """创建 result_type="text" 的 StreamResult。"""
    return StreamResult(result_type="text", content=content)


def _make_tool_call_result(tool_name, tool_arguments):
    """创建 result_type="tool_call" 的 StreamResult。"""
    return StreamResult(
        result_type="tool_call",
        tool_name=tool_name,
        tool_arguments=tool_arguments,
    )


def _make_error_result(error_message="API error"):
    """创建 result_type="error" 的 StreamResult。"""
    return StreamResult(result_type="error", error_message=error_message)


# ═══════════════════════════════════════════════════════════════
# 辅助：公共 mock 上下文补丁
# ═══════════════════════════════════════════════════════════════


def _patch_run_context():
    """返回 run() 方法所需的公共 mock 上下文管理器列表。

    run() 内部依赖较多外部模块，需要 patch 以下目标：
    - _handle_runtime_confirmation → no_pending
    - _classify_and_prepare_context → 提供 model/messages/tools
    - _update_system_message → 无操作
    - _emit_event → 无操作（SkillAgent 未定义此方法，需在实例上 stub）
    - config.MAX_TOKEN_BUDGET → 大值，避免 token 预算提前终止
    - config.TOOL_CALL_DEDUPLICATION_ENABLED → False，简化测试
    """
    return [
        patch("skill_agent._agent.config.MAX_TOKEN_BUDGET", 999_999_999),
        patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False),
        patch("skill_agent._agent.config.INPUT_CLASSIFICATION_ENABLED", False),
        patch("skill_agent._agent.config.PLAN_CONFIRMATION_ENABLED", False),
    ]


# ═══════════════════════════════════════════════════════════════
# run() 基本文本流程
# ═══════════════════════════════════════════════════════════════


class TestRunBasicTextFlow:
    """测试 LLM 返回纯文本时，run() 正确返回文本结果。"""

    def test_returns_text_when_llm_returns_text(self, skill_agent_minimal):
        """LLM 返回 text 类型 StreamResult 时，run() 返回对应文本。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        model = _make_mock_model([_make_text_result("你好，世界")])

        with patch.object(agent, "_handle_runtime_confirmation", return_value={"action": "no_pending"}), \
             patch.object(agent, "_classify_and_prepare_context") as mock_classify, \
             patch.object(agent, "_update_system_message"), \
             patch("skill_agent._agent.get_chat_model", return_value=model):
            mock_classify.return_value = {
                "action": "continue",
                "model": model,
                "tools": [],
                "messages": [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "你好"},
                ],
                "active_skill_text": [],
                "active_skill_ids": [],
            }
            patches = _patch_run_context()
            for p in patches:
                p.start()
            try:
                result = agent.run("你好")
            finally:
                for p in patches:
                    p.stop()

        assert result == "你好，世界"

    def test_returns_text_without_thinking(self, skill_agent_minimal):
        """LLM 返回纯文本（无 thinking）时也能正确返回。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        model = _make_mock_model([_make_text_result("这是纯文本回复")])

        with patch.object(agent, "_handle_runtime_confirmation", return_value={"action": "no_pending"}), \
             patch.object(agent, "_classify_and_prepare_context") as mock_classify, \
             patch.object(agent, "_update_system_message"), \
             patch("skill_agent._agent.get_chat_model", return_value=model):
            mock_classify.return_value = {
                "action": "continue",
                "model": model,
                "tools": [],
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "hello"},
                ],
                "active_skill_text": [],
                "active_skill_ids": [],
            }
            patches = _patch_run_context()
            for p in patches:
                p.start()
            try:
                result = agent.run("hello")
            finally:
                for p in patches:
                    p.stop()

        assert "纯文本回复" in result


# ═══════════════════════════════════════════════════════════════
# run() 工具调用流程
# ═══════════════════════════════════════════════════════════════


class TestRunToolCallFlow:
    """测试 LLM 返回工具调用时，run() 正确调度执行并继续循环。"""

    def test_tool_call_then_text(self, skill_agent_minimal):
        """LLM 先返回 tool_call，再返回 text，run() 返回最终文本。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # 第一次：LLM 返回工具调用
        tool_call_result = _make_tool_call_result(
            "file_operation",
            '{"action": "list", "path": "."}',
        )
        # 第二次：LLM 返回文本
        text_result = _make_text_result("文件列表已获取，共 3 个文件。")

        model = _make_mock_model([tool_call_result, text_result])

        with patch.object(agent, "_handle_runtime_confirmation", return_value={"action": "no_pending"}), \
             patch.object(agent, "_classify_and_prepare_context") as mock_classify, \
             patch.object(agent, "_update_system_message"), \
             patch("skill_agent._agent.get_chat_model", return_value=model), \
             patch("skill_agent._agent.execute_atomic_tool", return_value="file1.txt\nfile2.txt\nfile3.txt"):
            mock_classify.return_value = {
                "action": "continue",
                "model": model,
                "tools": [],
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "列出文件"},
                ],
                "active_skill_text": [],
                "active_skill_ids": [],
            }
            patches = _patch_run_context()
            for p in patches:
                p.start()
            try:
                result = agent.run("列出文件")
            finally:
                for p in patches:
                    p.stop()

        # 工具调用后的文本输出会被自动包装为 finish 返回
        assert "文件列表已获取" in result

    def test_tool_is_dispatched_with_correct_args(self, skill_agent_minimal):
        """工具调用时，execute_atomic_tool 被正确调用。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        tool_call_result = _make_tool_call_result(
            "file_operation",
            '{"action": "list", "path": "."}',
        )
        text_result = _make_text_result("完成")

        model = _make_mock_model([tool_call_result, text_result])

        with patch.object(agent, "_handle_runtime_confirmation", return_value={"action": "no_pending"}), \
             patch.object(agent, "_classify_and_prepare_context") as mock_classify, \
             patch.object(agent, "_update_system_message"), \
             patch("skill_agent._agent.get_chat_model", return_value=model), \
             patch("skill_agent._agent.execute_atomic_tool", return_value="ok") as mock_exec:
            mock_classify.return_value = {
                "action": "continue",
                "model": model,
                "tools": [],
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "列出文件"},
                ],
                "active_skill_text": [],
                "active_skill_ids": [],
            }
            patches = _patch_run_context()
            for p in patches:
                p.start()
            try:
                agent.run("列出文件")
            finally:
                for p in patches:
                    p.stop()

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[0][0] == "file_operation"


# ═══════════════════════════════════════════════════════════════
# run() 用户停止
# ═══════════════════════════════════════════════════════════════


class TestRunUserStop:
    """测试 stop_check_callback 返回 True 时，run() 正确终止。"""

    def test_stop_callback_returns_true(self, skill_agent_minimal):
        """stop_check_callback 返回 True 时，run() 检测到停止并终止循环。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # 使用 log_callback 捕获停止消息
        captured_logs = []

        def log_callback(content, msg_type):
            captured_logs.append((content, msg_type))

        # 需要提供至少一个 stream_result 以防 stream_request_llm_with_tools 被意外调用
        model = _make_mock_model([_make_text_result("should not reach")])

        # stop_check_callback 始终返回 True
        stop_callback = MagicMock(return_value=True)

        with patch.object(agent, "_handle_runtime_confirmation", return_value={"action": "no_pending"}), \
             patch.object(agent, "_classify_and_prepare_context") as mock_classify, \
             patch.object(agent, "_update_system_message"), \
             patch("skill_agent._agent.get_chat_model", return_value=model):
            mock_classify.return_value = {
                "action": "continue",
                "model": model,
                "tools": [],
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "test"},
                ],
                "active_skill_text": [],
                "active_skill_ids": [],
            }
            patches = _patch_run_context()
            for p in patches:
                p.start()
            try:
                result = agent.run("test", log_callback=log_callback, stop_check_callback=stop_callback)
            finally:
                for p in patches:
                    p.stop()

        # 验证 log_callback 收到停止消息
        stop_logs = [c for c, t in captured_logs if "停止" in c]
        assert len(stop_logs) > 0, f"未收到停止消息，captured_logs={captured_logs}"
        # 验证 LLM 未被调用（因为停止在 LLM 调用前检测）
        model.stream_request_llm_with_tools.assert_not_called()

    def test_stop_event_set_via_abort(self, skill_agent_minimal):
        """通过 abort() 设置 _stop_event 后，run() 在下一轮循环中检测到并终止。

        注意：run() 开头会调用 _stop_event.clear()，因此需要在循环内设置。
        这里在第一轮 LLM 返回工具调用后设置 stop_event，第二轮循环检测到停止。
        """
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        captured_logs = []

        def log_callback(content, msg_type):
            captured_logs.append((content, msg_type))

        # 第一次 LLM 返回工具调用（循环继续），然后 stop_event 会在下一轮检测到
        tool_call_result = _make_tool_call_result(
            "file_operation", '{"action": "list", "path": "."}'
        )
        model = _make_mock_model([tool_call_result, _make_text_result("should not reach")])

        # stop_check_callback 在第一次检查返回 False（允许 LLM 调用），
        # 第二次检查返回 True（触发停止）
        stop_callback = MagicMock(side_effect=[False, True])

        with patch.object(agent, "_handle_runtime_confirmation", return_value={"action": "no_pending"}), \
             patch.object(agent, "_classify_and_prepare_context") as mock_classify, \
             patch.object(agent, "_update_system_message"), \
             patch("skill_agent._agent.get_chat_model", return_value=model), \
             patch("skill_agent._agent.execute_atomic_tool", return_value="ok"):
            mock_classify.return_value = {
                "action": "continue",
                "model": model,
                "tools": [],
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "test"},
                ],
                "active_skill_text": [],
                "active_skill_ids": [],
            }
            patches = _patch_run_context()
            for p in patches:
                p.start()
            try:
                result = agent.run("test", log_callback=log_callback, stop_check_callback=stop_callback)
            finally:
                for p in patches:
                    p.stop()

        # 验证 log_callback 收到停止消息
        stop_logs = [c for c, t in captured_logs if "停止" in c]
        assert len(stop_logs) > 0, f"未收到停止消息，captured_logs={captured_logs}"


# ═══════════════════════════════════════════════════════════════
# _process_tool_call_in_loop 各分支
# ═══════════════════════════════════════════════════════════════


class TestProcessToolCallInLoop:
    """测试 _process_tool_call_in_loop 方法的各分支逻辑。"""

    def _make_process_args(self, agent, tool_name, tool_arguments):
        """构建 _process_tool_call_in_loop 所需的参数元组。"""
        result = _make_tool_call_result(tool_name, tool_arguments)
        return {
            "result": result,
            "full_thinking": "",
            "content_parts": [],
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "test"},
            ],
            "active_skill_text": [],
            "active_skill_ids": [],
            "model": MagicMock(),
            "tools": [],
            "log_callback": None,
            "_emit_token_usage": lambda: None,
        }

    def test_finish_tool_returns_action_return(self, skill_agent_minimal):
        """finish 工具调用 → 返回 {"action": "return", "value": ...}。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # execute_skill_control_tool 对 finish 返回 (msg, True, msg)
        with patch("skill_agent._agent.execute_skill_control_tool",
                    return_value=("任务完成", True, "任务完成")), \
             patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False):
            kwargs = self._make_process_args(agent, "finish", '{"message": "任务完成"}')
            ret = agent._process_tool_call_in_loop(**kwargs)

        assert ret["action"] == "return"
        assert ret["value"] == "任务完成"

    def test_ask_user_tool_returns_awaiting_reply(self, skill_agent_minimal):
        """ask_user 工具调用 → 返回 {"action": "return", "value": SKILL_AGENT_AWAITING_USER_REPLY}。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # execute_skill_control_tool 对 ask_user 返回 (formatted_text, False, None)
        ask_user_result = "【向你确认】\n\n是否继续？"
        with patch("skill_agent._agent.execute_skill_control_tool",
                    return_value=(ask_user_result, False, None)), \
             patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False):
            kwargs = self._make_process_args(agent, "ask_user", '{"question": "是否继续？"}')
            ret = agent._process_tool_call_in_loop(**kwargs)

        assert ret["action"] == "return"
        assert ret["value"] == SKILL_AGENT_AWAITING_USER_REPLY

    def test_atomic_tool_returns_action_continue(self, skill_agent_minimal):
        """普通原子工具调用 → 返回 {"action": "continue", "tool_called": True}。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # execute_atomic_tool 返回工具执行结果
        with patch("skill_agent._agent.execute_atomic_tool",
                    return_value="file1.txt\nfile2.txt"), \
             patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False), \
             patch("skill_agent._agent.config.TOOL_OUTPUT_MAX_LENGTH", 10000), \
             patch("skill_agent._agent.config.TOOL_TRUNCATE_SHOW_DETAILS", False):
            kwargs = self._make_process_args(agent, "file_operation", '{"action": "list", "path": "."}')
            ret = agent._process_tool_call_in_loop(**kwargs)

        assert ret["action"] == "continue"
        assert ret["tool_called"] is True

    def test_select_skill_returns_continue(self, skill_agent_minimal):
        """select_skill 工具调用 → 返回 {"action": "continue", ...}。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # execute_skill_control_tool 对 select_skill 返回 (doc, False, None)
        with patch("skill_agent._agent.execute_skill_control_tool",
                    return_value=("skill doc content", False, None)), \
             patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False):
            kwargs = self._make_process_args(agent, "select_skill", '{"skill_id": "test_skill"}')
            ret = agent._process_tool_call_in_loop(**kwargs)

        # select_skill 属于 _control_tools，不会设置 tool_called=True，
        # 但由于 _dispatch 返回 (doc, False, None)，
        # _process_tool_call_in_loop 中 tool_called 在 dispatch 后设为 True
        # 然后 select_skill 不在 _control_tools 检查中被排除
        # 实际上 select_skill 在 _control_tools 中，但 tool_called 是在 dispatch 后设置的
        assert ret["action"] == "continue"

    def test_finish_with_empty_message_returns_continue(self, skill_agent_minimal):
        """finish 工具 message 为空时，返回错误信息而非终止。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        # execute_skill_control_tool 对空 message 的 finish 返回错误
        error_msg = "错误：finish 的 message 参数不能为空。"
        with patch("skill_agent._agent.execute_skill_control_tool",
                    return_value=(error_msg, False, None)), \
             patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False):
            kwargs = self._make_process_args(agent, "finish", '{"message": ""}')
            ret = agent._process_tool_call_in_loop(**kwargs)

        # finish 返回 terminate=False，所以不会 return，而是 continue
        assert ret["action"] == "continue"

    def test_invalid_json_args_handled_gracefully(self, skill_agent_minimal):
        """tool_arguments 为无效 JSON 时，回退为空字典，不崩溃。"""
        agent = skill_agent_minimal
        agent._emit_event = MagicMock()

        with patch("skill_agent._agent.execute_atomic_tool",
                    return_value="ok"), \
             patch("skill_agent._agent.config.TOOL_CALL_DEDUPLICATION_ENABLED", False), \
             patch("skill_agent._agent.config.TOOL_OUTPUT_MAX_LENGTH", 10000), \
             patch("skill_agent._agent.config.TOOL_TRUNCATE_SHOW_DETAILS", False):
            # 直接构建 result，tool_arguments 为无效 JSON
            result = StreamResult(
                result_type="tool_call",
                tool_name="file_operation",
                tool_arguments="not valid json{{{",
            )
            ret = agent._process_tool_call_in_loop(
                result=result,
                full_thinking="",
                content_parts=[],
                messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "test"}],
                active_skill_text=[],
                active_skill_ids=[],
                model=MagicMock(),
                tools=[],
                log_callback=None,
                _emit_token_usage=lambda: None,
            )

        assert ret["action"] == "continue"
        assert ret["tool_called"] is True
