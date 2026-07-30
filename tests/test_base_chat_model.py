"""
BaseChatModel 核心方法单元测试

覆盖：
- _sanitize_tool_arguments: 工具参数清洗
- _sanitize_messages_for_api: 消息格式修复
- StreamParser._extract_tool_call_from_text: XML/JSON 工具调用提取
- StreamParser._extract_xml_tool_call: Qwen3 XML 格式解析
- StreamParser._extract_json_tool_call: Hermes JSON 格式解析
- StreamResult 工厂方法和转换方法
"""
import json

import pytest

from llm.BaseChatModel import (
    _sanitize_tool_arguments,
    _sanitize_messages_for_api,
    StreamParser,
    StreamResult,
    StreamResultType,
)

# Qwen3 工具调用标记字符（U+2588 FULL BLOCK）
BLOCK = "\u2588"


# ═══════════════════════════════════════════════════════════════
# _sanitize_tool_arguments
# ═══════════════════════════════════════════════════════════════

class TestSanitizeToolArguments:
    """工具参数清洗纯函数测试。"""

    def test_none_returns_empty_json(self):
        assert _sanitize_tool_arguments(None) == "{}"

    def test_valid_json_string_passthrough(self):
        args = '{"key": "value"}'
        assert _sanitize_tool_arguments(args) == args

    def test_invalid_json_string_returns_empty(self):
        assert _sanitize_tool_arguments("not json") == "{}"

    def test_dict_serialized(self):
        result = _sanitize_tool_arguments({"a": 1})
        assert json.loads(result) == {"a": 1}

    def test_int_returns_empty(self):
        assert _sanitize_tool_arguments(42) == "{}"

    def test_list_returns_empty(self):
        assert _sanitize_tool_arguments([1, 2]) == "{}"

    def test_empty_dict_returns_empty_json(self):
        result = _sanitize_tool_arguments({})
        assert json.loads(result) == {}

    def test_empty_string_returns_empty(self):
        assert _sanitize_tool_arguments("") == "{}"


# ═══════════════════════════════════════════════════════════════
# _sanitize_messages_for_api
# ═══════════════════════════════════════════════════════════════

class TestSanitizeMessagesForApi:
    """消息格式修复纯函数测试。"""

    def test_no_tool_calls_passthrough(self):
        """无 tool_calls 的消息列表原样返回。"""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = _sanitize_messages_for_api(messages)
        assert result == messages

    def test_fixes_invalid_arguments(self):
        """非法 arguments 被修复为 '{}'。"""
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "run_command",
                            "arguments": "not json",
                        },
                    }
                ],
            },
        ]
        result = _sanitize_messages_for_api(messages)
        assert result[0]["tool_calls"][0]["function"]["arguments"] == "{}"

    def test_valid_arguments_unchanged(self):
        """合法 arguments 不被修改。"""
        valid_args = '{"command": "ls"}'
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "run_command",
                            "arguments": valid_args,
                        },
                    }
                ],
            },
        ]
        result = _sanitize_messages_for_api(messages)
        assert result[0]["tool_calls"][0]["function"]["arguments"] == valid_args

    def test_dict_arguments_converted(self):
        """arguments 为 dict 时被序列化为 JSON 字符串。"""
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "run_command",
                            "arguments": {"command": "ls"},
                        },
                    }
                ],
            },
        ]
        result = _sanitize_messages_for_api(messages)
        args_str = result[0]["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args_str, str)
        assert json.loads(args_str) == {"command": "ls"}

    def test_non_assistant_unchanged(self):
        """user/system/tool 消息不被修改。"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "tool", "content": "result", "tool_call_id": "call_1"},
        ]
        result = _sanitize_messages_for_api(messages)
        assert result == messages

    def test_tool_calls_without_function_no_crash(self):
        """tool_calls 中缺少 function 字段时不崩溃。"""
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function"}],
            },
        ]
        result = _sanitize_messages_for_api(messages)
        assert len(result) == 1

    def test_function_without_arguments_no_crash(self):
        """function 中缺少 arguments 字段时不崩溃。"""
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "run_command"},
                    }
                ],
            },
        ]
        result = _sanitize_messages_for_api(messages)
        assert len(result) == 1

    def test_does_not_mutate_original(self):
        """原始消息列表不被修改（深拷贝验证）。"""
        original_args = "not json"
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "run_command",
                            "arguments": original_args,
                        },
                    }
                ],
            },
        ]
        _ = _sanitize_messages_for_api(messages)
        # 原始消息的 arguments 应未被修改
        assert messages[0]["tool_calls"][0]["function"]["arguments"] == original_args


# ═══════════════════════════════════════════════════════════════
# StreamParser._extract_tool_call_from_text
# ═══════════════════════════════════════════════════════════════

class TestExtractToolCallFromText:
    """XML/JSON 工具调用提取测试。

    注意：Qwen3 模型输出工具调用时使用 █ (U+2588) 标记包裹
    <tool_call> 块，因此测试数据需要包含该标记。
    """

    def test_empty_text_returns_none(self):
        assert StreamParser._extract_tool_call_from_text("") is None

    def test_none_text_returns_none(self):
        assert StreamParser._extract_tool_call_from_text(None) is None

    def test_no_block_marker_returns_none(self):
        """不含 █ 标记的文本返回 None。"""
        text = "这是一段普通文本，没有工具调用标记。"
        assert StreamParser._extract_tool_call_from_text(text) is None

    def test_xml_format_qwen3(self):
        """Qwen3 XML 格式正确提取（█ + tool_call 块）。"""
        tc_open = "<tool_call>"
        tc_close = "</tool_call>"
        fn_open = "<function=run_command>"
        fn_close = "</function>"
        param = "<parameter=command>ls -la</parameter>"
        text = f"{BLOCK}{tc_open}{fn_open}{param}{fn_close}{tc_close}{BLOCK}"
        result = StreamParser._extract_tool_call_from_text(text)
        assert result is not None
        name, args_json = result
        assert name == "run_command"
        args = json.loads(args_json)
        assert args["command"] == "ls -la"

    def test_hermes_json_format(self):
        """Hermes JSON 格式正确提取。"""
        tc_open = "<tool_call>"
        tc_close = "</tool_call>"
        payload = '{"name": "file_operation", "arguments": {"action": "list", "path": "."}}'
        text = f"{BLOCK}{tc_open}{payload}{tc_close}{BLOCK}"
        result = StreamParser._extract_tool_call_from_text(text)
        assert result is not None
        name, args_json = result
        assert name == "file_operation"
        args = json.loads(args_json)
        assert args["action"] == "list"

    def test_unknown_tool_name_returns_none(self):
        """未知工具名返回 None（防止 prose 误判）。"""
        tc_open = "<tool_call>"
        tc_close = "</tool_call>"
        fn_open = "<function=nonexistent_tool>"
        fn_close = "</function>"
        param = "<parameter=key>val</parameter>"
        text = f"{BLOCK}{tc_open}{fn_open}{param}{fn_close}{tc_close}{BLOCK}"
        assert StreamParser._extract_tool_call_from_text(text) is None

    def test_unknown_json_tool_name_returns_none(self):
        """JSON 格式中未知工具名也返回 None。"""
        tc_open = "<tool_call>"
        tc_close = "</tool_call>"
        payload = '{"name": "unknown_tool", "arguments": {}}'
        text = f"{BLOCK}{tc_open}{payload}{tc_close}{BLOCK}"
        assert StreamParser._extract_tool_call_from_text(text) is None

    def test_multiple_params_xml(self):
        """XML 格式多参数提取。"""
        tc_open = "<tool_call>"
        tc_close = "</tool_call>"
        fn_open = "<function=edit>"
        fn_close = "</function>"
        params = (
            "<parameter=path>test.py</parameter>"
            "<parameter=old_str>hello</parameter>"
            "<parameter=new_str>world</parameter>"
        )
        text = f"{BLOCK}{tc_open}{fn_open}{params}{fn_close}{tc_close}{BLOCK}"
        result = StreamParser._extract_tool_call_from_text(text)
        assert result is not None
        name, args_json = result
        assert name == "edit"
        args = json.loads(args_json)
        assert args["path"] == "test.py"
        assert args["old_str"] == "hello"
        assert args["new_str"] == "world"

    def test_json_arguments_as_string(self):
        """JSON 格式中 arguments 为字符串时正确解析。"""
        tc_open = "<tool_call>"
        tc_close = "</tool_call>"
        inner_args = json.dumps({"command": "ls"})
        payload = json.dumps({"name": "run_command", "arguments": inner_args})
        text = f"{BLOCK}{tc_open}{payload}{tc_close}{BLOCK}"
        result = StreamParser._extract_tool_call_from_text(text)
        assert result is not None
        name, args_json = result
        assert name == "run_command"
        args = json.loads(args_json)
        assert args["command"] == "ls"


# ═══════════════════════════════════════════════════════════════
# StreamParser._extract_xml_tool_call
# ═══════════════════════════════════════════════════════════════

class TestExtractXmlToolCall:
    """Qwen3 XML 格式解析测试。"""

    def test_valid_xml_block(self):
        fn_open = "<function=run_command>"
        fn_close = "</function>"
        param = "<parameter=command>ls</parameter>"
        block = f"{fn_open}{param}{fn_close}"
        result = StreamParser._extract_xml_tool_call(block)
        assert result is not None
        name, args_json = result
        assert name == "run_command"

    def test_no_function_tag_returns_none(self):
        block = "<parameter=key>value</parameter>"
        assert StreamParser._extract_xml_tool_call(block) is None

    def test_unknown_tool_name_returns_none(self):
        fn_open = "<function=unknown>"
        fn_close = "</function>"
        param = "<parameter=key>val</parameter>"
        block = f"{fn_open}{param}{fn_close}"
        assert StreamParser._extract_xml_tool_call(block) is None

    def test_nested_json_parameter(self):
        """参数值为 JSON 对象时正确解析。"""
        fn_open = "<function=file_operation>"
        fn_close = "</function>"
        param = '<parameter=options>{"recursive": true}</parameter>'
        block = f"{fn_open}{param}{fn_close}"
        result = StreamParser._extract_xml_tool_call(block)
        assert result is not None
        name, args_json = result
        args = json.loads(args_json)
        assert args["options"] == {"recursive": True}


# ═══════════════════════════════════════════════════════════════
# StreamParser._extract_json_tool_call
# ═══════════════════════════════════════════════════════════════

class TestExtractJsonToolCall:
    """Hermes JSON 格式解析测试。"""

    def test_valid_json_block(self):
        block = '{"name": "edit", "arguments": {"path": "a.py"}}'
        result = StreamParser._extract_json_tool_call(block)
        assert result is not None
        name, args_json = result
        assert name == "edit"

    def test_no_json_object_returns_none(self):
        block = "no json here"
        assert StreamParser._extract_json_tool_call(block) is None

    def test_missing_name_returns_none(self):
        block = '{"arguments": {"path": "a.py"}}'
        assert StreamParser._extract_json_tool_call(block) is None

    def test_unknown_name_returns_none(self):
        block = '{"name": "nonexistent", "arguments": {}}'
        assert StreamParser._extract_json_tool_call(block) is None

    def test_empty_arguments(self):
        block = '{"name": "finish", "arguments": {}}'
        result = StreamParser._extract_json_tool_call(block)
        assert result is not None
        name, args_json = result
        assert name == "finish"
        assert json.loads(args_json) == {}


# ═══════════════════════════════════════════════════════════════
# StreamResult
# ═══════════════════════════════════════════════════════════════

class TestStreamResult:
    """StreamResult 工厂方法和转换方法测试。"""

    def test_from_text(self):
        r = StreamResult.from_text("hello", reasoning_content="think")
        assert r.result_type == "text"
        assert r.content == "hello"
        assert r.reasoning_content == "think"
        assert r.tool_name is None

    def test_from_tool_call(self):
        r = StreamResult.from_tool_call("run_command", '{"cmd": "ls"}')
        assert r.result_type == "tool_call"
        assert r.tool_name == "run_command"
        assert r.tool_arguments == '{"cmd": "ls"}'

    def test_from_truncated(self):
        r = StreamResult.from_truncated("partial content")
        assert r.result_type == "truncated"
        assert r.content == "partial content"

    def test_from_error(self):
        r = StreamResult.from_error("something went wrong")
        assert r.result_type == "error"
        assert r.error_message == "something went wrong"
        assert r.content == "something went wrong"

    def test_to_legacy_dict_text(self):
        r = StreamResult.from_text("hello")
        d = r.to_legacy_dict()
        assert d["name"] is None
        assert d["content"] == "hello"
        assert d["arguments"] is None

    def test_to_legacy_dict_tool_call(self):
        r = StreamResult.from_tool_call("edit", '{"path": "a"}')
        d = r.to_legacy_dict()
        assert d["name"] == "edit"
        assert d["arguments"] == '{"path": "a"}'

    def test_to_legacy_dict_error(self):
        r = StreamResult.from_error("oops")
        d = r.to_legacy_dict()
        assert d["name"] == "finish"
        assert "oops" in d["arguments"]

    def test_to_simple_namespace(self):
        r = StreamResult.from_text("hello", reasoning_content="think")
        ns = r.to_simple_namespace()
        assert ns.content == "hello"
        assert ns.reasoning_content == "think"

    def test_stream_result_type_enum(self):
        """验证 StreamResultType 枚举值。"""
        assert StreamResultType.TEXT == "text"
        assert StreamResultType.TOOL_CALL == "tool_call"
        assert StreamResultType.ERROR == "error"
        assert StreamResultType.TRUNCATED == "truncated"
