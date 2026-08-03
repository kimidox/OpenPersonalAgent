"""
base_tool/dispatch.py 核心函数单元测试

覆盖：
- execute_atomic_tool: Handler 注册表分发
- _detect_and_fix_command: 命令预校验与自动修复
- _fix_powershell_env_variables: PowerShell 环境变量替换
- _truncate_run_output: 输出截断
- _detect_dangerous_command: 危险命令检测
- _is_download_failure: 下载失败检测
- _get_error_suggestions: 错误建议生成
- _should_use_powershell: PowerShell 执行判断
- _fix_findstr_quotes: findstr 引号修复
- _fix_cmd_to_powershell: CMD 命令转 PowerShell
"""
from unittest.mock import patch, MagicMock

import pytest

from base_tool.dispatch import (
    execute_atomic_tool,
    _detect_and_fix_command,
    _fix_powershell_env_variables,
    _truncate_run_output,
    _detect_dangerous_command,
    _is_download_failure,
    _get_error_suggestions,
    _should_use_powershell,
    _fix_findstr_quotes,
    _fix_cmd_to_powershell,
)


# ═══════════════════════════════════════════════════════════════
# execute_atomic_tool
# ═══════════════════════════════════════════════════════════════

class TestExecuteAtomicTool:
    """execute_atomic_tool 通过 Handler 注册表分发调用。"""

    def test_dispatches_to_matched_handler(self, tool_ctx):
        """注册表命中时，调用 handler.execute 并返回结果。"""
        mock_handler = MagicMock()
        mock_handler.execute.return_value = "文件列表结果"

        with patch("base_tool.handlers.get_handler", return_value=mock_handler), \
             patch("base_tool.handlers.ensure_registered"):
            result = execute_atomic_tool("file_operation", {"action": "list"}, tool_ctx, None)
            assert result == "文件列表结果"
            mock_handler.execute.assert_called_once_with(
                {"action": "list"}, tool_ctx, None
            )

    def test_returns_unknown_tool_when_handler_not_found(self, tool_ctx):
        """注册表未命中时，返回"未知原子工具"错误信息。"""
        with patch("base_tool.handlers.get_handler", return_value=None), \
             patch("base_tool.handlers.ensure_registered"):
            result = execute_atomic_tool("nonexistent_tool", {}, tool_ctx, None)
            assert "未知原子工具" in result
            assert "nonexistent_tool" in result

    def test_catches_handler_exception_and_returns_error(self, tool_ctx):
        """Handler 执行异常时，捕获异常并返回错误信息，不崩溃。"""
        mock_handler = MagicMock()
        mock_handler.execute.side_effect = RuntimeError("模拟执行失败")

        with patch("base_tool.handlers.get_handler", return_value=mock_handler), \
             patch("base_tool.handlers.ensure_registered"):
            result = execute_atomic_tool("file_operation", {}, tool_ctx, None)
            assert "错误" in result
            assert "执行异常" in result

    def test_ensure_registered_called_on_dispatch(self, tool_ctx):
        """每次调用时触发 ensure_registered 以保证 Handler 已注册。"""
        mock_handler = MagicMock()
        mock_handler.execute.return_value = "ok"

        with patch("base_tool.handlers.get_handler", return_value=mock_handler) as mock_get, \
             patch("base_tool.handlers.ensure_registered") as mock_ensure:
            execute_atomic_tool("file_operation", {}, tool_ctx, None)
            mock_ensure.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# _detect_dangerous_command
# ═══════════════════════════════════════════════════════════════

class TestDetectDangerousCommand:
    """_detect_dangerous_command 危险命令模式匹配测试。"""

    def test_rm_rf_root_is_dangerous(self):
        """rm -rf / 匹配危险模式。"""
        assert _detect_dangerous_command("rm -rf /") is True

    def test_rm_r_root_is_dangerous(self):
        """rm -r / 匹配危险模式。"""
        assert _detect_dangerous_command("rm -r /") is True

    def test_format_drive_is_dangerous(self):
        """format C: 匹配危险模式。"""
        assert _detect_dangerous_command("format C:") is True

    def test_del_all_files_is_dangerous(self):
        r"""del /f *. 匹配危险模式（正则 `\*\.?\s*$`）。"""
        # 正则 r'^\s*del\s+(/f|/s|/q)*\s+\*\.?\s*$' 要求 flags 连写，
        # 通配符为 * 或 *.
        assert _detect_dangerous_command("del /f *.") is True

    def test_rd_s_q_drive_is_dangerous(self):
        """rd /s/q C:\\ 匹配危险模式（正则要求 flags 连写 /s/q）。"""
        # 正则 r'^\s*rd\s+(/s|/q)*\s+[a-zA-Z]:\\$' 要求 /s/q 连写无空格
        assert _detect_dangerous_command("rd /s/q C:\\") is True

    def test_diskpart_is_dangerous(self):
        """diskpart 匹配危险模式。"""
        assert _detect_dangerous_command("diskpart ") is True

    def test_reg_delete_force_is_dangerous(self):
        """reg delete ... /f 匹配危险模式。"""
        assert _detect_dangerous_command("reg delete HKLM\\Software\\Test /f") is True

    def test_net_user_is_dangerous(self):
        """net user 匹配危险模式（用户管理）。"""
        assert _detect_dangerous_command("net user ") is True

    def test_safe_command_is_not_dangerous(self):
        """安全命令不匹配任何危险模式。"""
        assert _detect_dangerous_command("ls -la") is False

    def test_python_script_is_not_dangerous(self):
        """python 脚本命令不是危险命令。"""
        assert _detect_dangerous_command("python main.py") is False

    def test_case_insensitive_match(self):
        """危险命令检测不区分大小写。"""
        assert _detect_dangerous_command("RM -RF /") is True
        assert _detect_dangerous_command("FORMAT D:") is True

    def test_leading_whitespace_still_detected(self):
        """命令前有空白仍然能匹配危险模式。"""
        assert _detect_dangerous_command("  rm -rf /") is True


# ═══════════════════════════════════════════════════════════════
# _detect_and_fix_command
# ═══════════════════════════════════════════════════════════════

class TestDetectAndFixCommand:
    """_detect_and_fix_command 命令预校验与自动修复测试。"""

    def test_empty_command_returns_as_is(self):
        """空命令无需修复。"""
        fixed, msg = _detect_and_fix_command("")
        assert fixed == ""
        assert msg == ""

    def test_none_like_command_returns_as_is(self):
        """None 级别的空值直接返回。"""
        fixed, msg = _detect_and_fix_command("")
        assert msg == ""

    def test_batch_variable_syntax_returns_error(self):
        """检测到 %% 批处理变量语法返回不可修复错误。"""
        fixed, msg = _detect_and_fix_command("for /f %%a in (1) do echo %%a")
        assert fixed == ""
        assert "批处理变量语法" in msg
        assert "%%" in msg

    def test_findstr_pattern_gets_fixed(self):
        """findstr /C:"..." 模式被转换为 PowerShell Select-String。"""
        fixed, msg = _detect_and_fix_command('systeminfo | findstr /C:"OS Name"')
        assert msg == ""
        assert "Select-String" in fixed

    def test_wmic_command_gets_fixed(self):
        """wmic 命令被转换为 Get-CimInstance。"""
        fixed, msg = _detect_and_fix_command("wmic cpu get name")
        assert msg == ""
        assert "Get-CimInstance" in fixed

    def test_systeminfo_gets_converted(self):
        """systeminfo 被转换为 PowerShell 等效命令。"""
        fixed, msg = _detect_and_fix_command("systeminfo")
        assert msg == ""
        assert "Get-CimInstance" in fixed

    def test_safe_command_returns_unchanged(self):
        """安全命令原样返回。"""
        cmd = "python main.py"
        fixed, msg = _detect_and_fix_command(cmd)
        assert fixed == cmd
        assert msg == ""


# ═══════════════════════════════════════════════════════════════
# _fix_powershell_env_variables
# ═══════════════════════════════════════════════════════════════

class TestFixPowershellEnvVariables:
    """_fix_powershell_env_variables 环境变量替换测试。"""

    def test_replace_env_temp(self):
        """$env:TEMP 被替换为实际路径。"""
        with patch.dict("os.environ", {"TEMP": "C:\\Temp123"}):
            result = _fix_powershell_env_variables("copy file $env:TEMP\\out.txt")
            assert "C:\\Temp123" in result
            assert "$env:TEMP" not in result

    def test_replace_env_userprofile(self):
        """$env:USERPROFILE 被替换为实际路径。"""
        with patch.dict("os.environ", {"USERPROFILE": "C:\\Users\\TestUser"}):
            result = _fix_powershell_env_variables("cd $env:USERPROFILE\\Documents")
            assert "C:\\Users\\TestUser" in result
            assert "$env:USERPROFILE" not in result

    def test_replace_env_appdata(self):
        """$env:APPDATA 被替换为实际路径。"""
        with patch.dict("os.environ", {"APPDATA": "C:\\Users\\Test\\AppData\\Roaming"}):
            result = _fix_powershell_env_variables("dir $env:APPDATA\\MyApp")
            assert "C:\\Users\\Test\\AppData\\Roaming" in result

    def test_replace_env_localappdata(self):
        """$env:LOCALAPPDATA 被替换为实际路径。"""
        with patch.dict("os.environ", {"LOCALAPPDATA": "C:\\Users\\Test\\AppData\\Local"}):
            result = _fix_powershell_env_variables("dir $env:LOCALAPPDATA\\MyApp")
            assert "C:\\Users\\Test\\AppData\\Local" in result

    def test_case_insensitive_replacement(self):
        """环境变量替换不区分大小写。"""
        with patch.dict("os.environ", {"TEMP": "C:\\Tmp"}):
            result = _fix_powershell_env_variables("copy file $env:temp\\out.txt")
            assert "C:\\Tmp" in result

    def test_command_without_env_vars_unchanged(self):
        """不含环境变量的命令不做修改。"""
        cmd = "echo hello world"
        assert _fix_powershell_env_variables(cmd) == cmd

    def test_multiple_env_vars_replaced(self):
        """命令中多个不同的环境变量同时被替换。"""
        with patch.dict("os.environ", {"TEMP": "C:\\Tmp", "USERPROFILE": "C:\\Users\\U"}):
            result = _fix_powershell_env_variables("copy $env:TEMP\\a.txt $env:USERPROFILE\\b.txt")
            assert "C:\\Tmp" in result
            assert "C:\\Users\\U" in result

    def test_env_var_not_in_os_environ_not_replaced(self):
        """环境变量在 os.environ 中不存在时不替换。"""
        with patch.dict("os.environ", {}, clear=True):
            result = _fix_powershell_env_variables("copy file $env:TEMP\\out.txt")
            assert "$env:TEMP" in result


# ═══════════════════════════════════════════════════════════════
# _truncate_run_output
# ═══════════════════════════════════════════════════════════════

class TestTruncateRunOutput:
    """_truncate_run_output 输出截断测试。"""

    def test_short_text_not_truncated(self):
        """短文本不做截断。"""
        text = "hello world"
        assert _truncate_run_output(text, limit=100) == text

    def test_exact_limit_not_truncated(self):
        """恰好等于限制长度的文本不截断。"""
        text = "a" * 50
        assert _truncate_run_output(text, limit=50) == text

    def test_long_text_truncated(self):
        """超长文本被截断并添加提示。"""
        text = "a" * 200
        result = _truncate_run_output(text, limit=100)
        assert result.startswith("a" * 100)
        assert "截断" in result

    def test_none_text_returns_empty(self):
        """None 文本返回空字符串。"""
        assert _truncate_run_output(None, limit=100) == ""

    def test_empty_text_returns_empty(self):
        """空字符串返回空字符串。"""
        assert _truncate_run_output("", limit=100) == ""

    def test_truncation_shows_details_when_config_enabled(self):
        """配置开启详细模式时，截断提示包含原始长度和显示长度。"""
        text = "b" * 300
        with patch("config.TOOL_TRUNCATE_SHOW_DETAILS", True):
            result = _truncate_run_output(text, limit=100)
            assert "300" in result
            assert "100" in result

    def test_truncation_hides_details_when_config_disabled(self):
        """配置关闭详细模式时，截断提示不含具体长度。"""
        text = "c" * 300
        with patch("config.TOOL_TRUNCATE_SHOW_DETAILS", False):
            result = _truncate_run_output(text, limit=100)
            assert "300" not in result
            assert "100" not in result
            assert "截断" in result

    def test_limit_from_config_when_none(self):
        """limit=None 时从配置文件读取截断阈值。"""
        text = "d" * 200
        with patch("config.TOOL_OUTPUT_MAX_LENGTH", 50):
            result = _truncate_run_output(text, limit=None)
            assert "截断" in result


# ═══════════════════════════════════════════════════════════════
# _is_download_failure
# ═══════════════════════════════════════════════════════════════

class TestIsDownloadFailure:
    """_is_download_failure 下载失败检测测试。"""

    def test_404_error(self):
        """404 错误判定为下载失败。"""
        assert _is_download_failure("HTTP Error 404: Not Found") is True

    def test_not_found_text(self):
        """包含 'not found' 判定为下载失败。"""
        assert _is_download_failure("The resource was not found") is True

    def test_timeout_error(self):
        """超时错误判定为下载失败。"""
        assert _is_download_failure("Connection timeout after 30s") is True

    def test_timed_out_error(self):
        """'timed out' 判定为下载失败。"""
        assert _is_download_failure("Request timed out") is True

    def test_chinese_timeout(self):
        """中文'超时'判定为下载失败。"""
        assert _is_download_failure("连接超时") is True

    def test_connection_refused(self):
        """连接被拒绝判定为下载失败。"""
        assert _is_download_failure("Could not connect to host") is True
        assert _is_download_failure("Connection refused") is True

    def test_chinese_connection_failure(self):
        """中文连接失败判定为下载失败。"""
        assert _is_download_failure("连接失败") is True
        assert _is_download_failure("无法连接到服务器") is True

    def test_dns_failure(self):
        """DNS 解析失败判定为下载失败。"""
        assert _is_download_failure("Could not resolve hostname") is True
        assert _is_download_failure("DNS resolution failed") is True

    def test_ssl_error(self):
        """SSL/TLS 错误判定为下载失败。"""
        assert _is_download_failure("SSL certificate verification failed") is True
        assert _is_download_failure("TLS handshake error") is True
        assert _is_download_failure("certificate verify failed") is True

    def test_normal_output_not_failure(self):
        """正常输出不是下载失败。"""
        assert _is_download_failure("Successfully installed package") is False

    def test_empty_string_not_failure(self):
        """空字符串不是下载失败。"""
        assert _is_download_failure("") is False


# ═══════════════════════════════════════════════════════════════
# _get_error_suggestions
# ═══════════════════════════════════════════════════════════════

class TestGetErrorSuggestions:
    """_get_error_suggestions 错误建议生成测试。"""

    def test_command_not_found_suggestion(self):
        """'不是内部或外部命令' 产生命令不存在建议。"""
        result = _get_error_suggestions("'python' 不是内部或外部命令")
        assert "命令不存在" in result
        assert "PATH" in result

    def test_access_denied_suggestion(self):
        """'拒绝访问' 产生权限不足建议。"""
        result = _get_error_suggestions("拒绝访问")
        assert "权限不足" in result

    def test_english_access_denied_suggestion(self):
        """'Access is denied' 产生权限不足建议。"""
        result = _get_error_suggestions("Access is denied")
        assert "权限不足" in result

    def test_file_not_found_suggestion(self):
        """'系统找不到指定的文件' 产生路径不存在建议。"""
        result = _get_error_suggestions("系统找不到指定的文件")
        assert "路径不存在" in result

    def test_english_file_not_found_suggestion(self):
        """'The system cannot find the file' 产生路径不存在建议。"""
        result = _get_error_suggestions("The system cannot find the file specified")
        assert "路径不存在" in result

    def test_timeout_suggestion(self):
        """'timeout' 产生超时建议。"""
        result = _get_error_suggestions("Command timeout exceeded")
        assert "超时" in result
        assert "timeout_sec" in result

    def test_chinese_timeout_suggestion(self):
        """中文'超时'产生超时建议。"""
        result = _get_error_suggestions("操作超时")
        assert "超时" in result

    def test_module_not_found_suggestion(self):
        """ModuleNotFoundError 产生缺少模块建议。"""
        result = _get_error_suggestions("ModuleNotFoundError: No module named 'xxx'")
        assert "缺少Python模块" in result
        assert "pip install" in result

    def test_findstr_error_suggestion(self):
        """FINDSTR 无法打开产生 findstr 替代建议。"""
        result = _get_error_suggestions("FINDSTR: 无法打开")
        assert "findstr" in result.lower()
        assert "PowerShell" in result

    def test_multiple_suggestions_combined(self):
        """多个错误模式同时匹配时，产生多条建议。"""
        result = _get_error_suggestions("ModuleNotFoundError: 拒绝访问")
        assert "权限不足" in result
        assert "缺少Python模块" in result

    def test_no_error_returns_empty(self):
        """无错误内容时返回空字符串。"""
        assert _get_error_suggestions("") == ""

    def test_none_stderr_returns_empty(self):
        """stderr 和 stdout 均为空时返回空字符串。"""
        assert _get_error_suggestions("", "") == ""

    def test_stdout_also_checked(self):
        """stdout 中的错误模式也会产生建议。"""
        result = _get_error_suggestions(stderr="", stdout="ModuleNotFoundError: foo")
        assert "缺少Python模块" in result

    def test_unknown_error_no_suggestion(self):
        """未知错误不产生建议。"""
        result = _get_error_suggestions("some random error output")
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# _should_use_powershell
# ═══════════════════════════════════════════════════════════════

class TestShouldUsePowershell:
    """_should_use_powershell PowerShell 执行判断测试。"""

    def test_explicit_powershell_prefix(self):
        """以 powershell 开头的命令判定为使用 PowerShell。"""
        assert _should_use_powershell("powershell Get-Process") is True

    def test_powershell_case_insensitive(self):
        """PowerShell 前缀判断不区分大小写。"""
        assert _should_use_powershell("PowerShell Get-Process") is True

    def test_get_cmdlet(self):
        """包含 Get- 开头的 cmdlet 判定为使用 PowerShell。"""
        assert _should_use_powershell("Get-Process") is True

    def test_set_cmdlet(self):
        """包含 Set- 开头的 cmdlet 判定为使用 PowerShell。"""
        assert _should_use_powershell("Set-Location C:\\Temp") is True

    def test_select_cmdlet(self):
        """包含 Select- 开头的 cmdlet 判定为使用 PowerShell。"""
        assert _should_use_powershell("Get-Process | Select-Object Name") is True

    def test_foreach_object(self):
        """包含 ForEach-Object 判定为使用 PowerShell。"""
        assert _should_use_powershell("1..5 | ForEach-Object { $_ }") is True

    def test_pipe_operator(self):
        """包含管道符判定为使用 PowerShell。"""
        assert _should_use_powershell("dir | findstr txt") is True

    def test_env_variable_reference(self):
        """包含 $env: 判定为使用 PowerShell。"""
        assert _should_use_powershell("echo $env:TEMP") is True

    def test_dotnet_type_reference(self):
        """包含 [System. 判定为使用 PowerShell。"""
        assert _should_use_powershell("[System.IO.File]::ReadAllText('a.txt')") is True

    def test_python_command_not_powershell(self):
        """python 命令不使用 PowerShell。"""
        assert _should_use_powershell("python script.py") is False

    def test_py_script_not_powershell(self):
        """.py 结尾的命令不使用 PowerShell。"""
        assert _should_use_powershell("script.py") is False

    def test_simple_cmd_command_not_powershell(self):
        """简单 CMD 命令不使用 PowerShell。"""
        assert _should_use_powershell("dir") is False
        assert _should_use_powershell("echo hello") is False


# ═══════════════════════════════════════════════════════════════
# _fix_findstr_quotes
# ═══════════════════════════════════════════════════════════════

class TestFixFindstrQuotes:
    """_fix_findstr_quotes findstr /C:"..." 模式修复测试。"""

    def test_findstr_with_double_quotes(self):
        """findstr /C:"OS Name" 模式被转换为 Select-String。"""
        fixed, msg = _fix_findstr_quotes('systeminfo | findstr /C:"OS Name"')
        assert fixed is not None
        assert "Select-String" in fixed
        assert "OS Name" in fixed

    def test_findstr_with_single_quotes(self):
        """findstr /C:'pattern' 单引号模式也被转换。"""
        fixed, msg = _fix_findstr_quotes("systeminfo | findstr /C:'OS Name'")
        assert fixed is not None
        assert "Select-String" in fixed

    def test_command_without_findstr_returns_none(self):
        """不含 findstr 的命令返回 None，表示无需处理。"""
        fixed, msg = _fix_findstr_quotes("echo hello")
        assert fixed is None

    def test_findstr_without_c_flag_returns_none(self):
        """findstr 没有 /C: 标志时返回 None。"""
        fixed, msg = _fix_findstr_quotes("dir | findstr txt")
        assert fixed is None

    def test_converted_command_has_powershell_prefix(self):
        """转换后的命令以 powershell 开头。"""
        fixed, msg = _fix_findstr_quotes('systeminfo | findstr /C:"OS Name"')
        assert fixed is not None
        assert fixed.startswith("powershell")


# ═══════════════════════════════════════════════════════════════
# _fix_cmd_to_powershell
# ═══════════════════════════════════════════════════════════════

class TestFixCmdToPowershell:
    """_fix_cmd_to_powershell CMD 命令转 PowerShell 测试。"""

    def test_systeminfo_converted(self):
        """systeminfo 转换为 Get-CimInstance Win32_OperatingSystem。"""
        fixed, msg = _fix_cmd_to_powershell("systeminfo")
        assert fixed is not None
        assert "Get-CimInstance" in fixed
        assert "Win32_OperatingSystem" in fixed

    def test_whoami_converted(self):
        """whoami 转换为 WindowsIdentity。"""
        fixed, msg = _fix_cmd_to_powershell("whoami")
        assert fixed is not None
        assert "WindowsIdentity" in fixed

    def test_hostname_converted(self):
        """hostname 转换为 $env:COMPUTERNAME。"""
        fixed, msg = _fix_cmd_to_powershell("hostname")
        assert fixed is not None
        assert "$env:COMPUTERNAME" in fixed

    def test_ipconfig_converted(self):
        """ipconfig 转换为 Get-NetIPAddress。"""
        fixed, msg = _fix_cmd_to_powershell("ipconfig")
        assert fixed is not None
        assert "Get-NetIPAddress" in fixed

    def test_ipconfig_all_converted(self):
        """ipconfig /all 也被转换。"""
        fixed, msg = _fix_cmd_to_powershell("ipconfig /all")
        assert fixed is not None
        assert "Get-NetIPAddress" in fixed

    def test_tasklist_converted(self):
        """tasklist 转换为 Get-Process。"""
        fixed, msg = _fix_cmd_to_powershell("tasklist")
        assert fixed is not None
        assert "Get-Process" in fixed

    def test_netstat_converted(self):
        """netstat 转换为 Get-NetTCPConnection。"""
        fixed, msg = _fix_cmd_to_powershell("netstat")
        assert fixed is not None
        assert "Get-NetTCPConnection" in fixed

    def test_netstat_an_converted(self):
        """netstat -an 也被转换。"""
        fixed, msg = _fix_cmd_to_powershell("netstat -an")
        assert fixed is not None
        assert "Get-NetTCPConnection" in fixed

    def test_netstat_ano_converted(self):
        """netstat -ano 也被转换。"""
        fixed, msg = _fix_cmd_to_powershell("netstat -ano")
        assert fixed is not None
        assert "Get-NetTCPConnection" in fixed

    def test_unsupported_command_returns_none(self):
        """不支持的 CMD 命令返回 None。"""
        fixed, msg = _fix_cmd_to_powershell("dir")
        assert fixed is None

    def test_python_command_returns_none(self):
        """python 命令返回 None，不做转换。"""
        fixed, msg = _fix_cmd_to_powershell("python script.py")
        assert fixed is None

    def test_case_insensitive_match(self):
        """CMD 命令匹配不区分大小写。"""
        fixed, msg = _fix_cmd_to_powershell("SYSTEMINFO")
        assert fixed is not None
        assert "Get-CimInstance" in fixed

    def test_command_with_extra_args_not_converted(self):
        """带额外参数的 systeminfo 不匹配精确模式，返回 None。"""
        # systeminfo 后跟其他内容不匹配 ^systeminfo\s*$
        fixed, msg = _fix_cmd_to_powershell("systeminfo /s remotehost")
        assert fixed is None

    def test_converted_command_has_empty_message(self):
        """成功转换时消息为空字符串。"""
        fixed, msg = _fix_cmd_to_powershell("systeminfo")
        assert fixed is not None
        assert msg == ""
