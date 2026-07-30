"""run_command 工具处理器"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .base import ToolHandler
from ..context import ToolContext
from ..dispatch import (
    _resolve_safe,
    _splice_skill_path,
    _detect_dangerous_command,
    _detect_and_fix_command,
    _decode_output,
    _should_use_powershell,
    _install_skill_dependencies,
    _get_venv_python,
    _truncate_run_output,
    _get_error_suggestions,
    _detect_skills_path_misuse,
    _RUN_COMMAND_DEFAULT_TIMEOUT,
    _RUN_COMMAND_MAX_TIMEOUT,
    PSUTIL_AVAILABLE,
)
from ..command_validator import CommandValidator
from ..run_command import validate_and_log_warnings
import config
from logger import get_module_logger
from . import register_handler

# psutil 可选导入，用于超时时的进程树清理
try:
    import psutil
except ImportError:
    psutil = None

logger = get_module_logger(__name__)


class RunCommandHandler(ToolHandler):
    """命令执行工具处理器

    最复杂的工具处理器，包含：
    - 参数校验和自动修复
    - 危险命令检测
    - 超时管理
    - PowerShell/CMD 智能选择
    - 输出截断和编码处理
    """

    @property
    def name(self) -> str:
        """返回工具名称"""
        return "run_command"

    def execute(self, args: dict, ctx: ToolContext, registry) -> str:
        """执行命令行指令，包含参数校验、危险命令检测、超时管理和输出处理

        Args:
            args: 工具参数字典，支持 command、cwd、timeout_sec、skill_id
            ctx: ToolContext 执行上下文
            registry: 工具注册表

        Returns:
            工具执行结果的字符串
        """
        # 兼容 LLM 误用 cmd 参数名（实际期望 command）
        command = str(args.get("command") or args.get("cmd") or "").strip()
        if not command:
            return (
                "错误: 缺少 command 参数。请提供要执行的命令行指令。\n"
                "提示：参数名是 `command`（不是 `cmd`）。"
            )

        # 步骤1: 参数校验
        validator = CommandValidator()
        validation_result = validator.validate(command, args)

        if not validation_result.is_valid:
            # 校验失败，返回结构化错误报告
            error_report = f"""【参数校验失败】
【错误类型】{validation_result.error_type}
【错误摘要】{validation_result.error_context.get('message', '参数格式错误')}
【错误详情】{validation_result.error_context}
【修复建议】{validation_result.fix_suggestion}
【重试模板】{validation_result.retry_template}

请根据上述提示修正命令参数后重新调用 run_command。"""
            logger.warning(f"命令参数校验失败: {validation_result.error_type} - {validation_result.error_context}")
            return error_report

        logger.debug("命令参数校验通过")

        # 危险命令检测
        if _detect_dangerous_command(command):
            return (
                f"【安全警告】检测到可能具有破坏性的命令: {command}\n\n"
                f"该命令可能对系统造成不可逆的影响。请确认：\n"
                f"1. 这是否是您真正想要执行的命令？\n"
                f"2. 是否有更安全的替代方案？\n\n"
                f"如果确认需要执行，请将命令修改为明确安全的版本后重试。"
            )

        # 命令预校验和自动修复
        fixed_command, fix_error = _detect_and_fix_command(command)
        if fix_error:
            return fix_error
        if fixed_command != command:
            logger.debug("命令已自动修复: %s -> %s", command, fixed_command)
            command = fixed_command

        # 参数完整性检查（检查失败只记录警告，不阻止执行）
        validate_and_log_warnings(command, logger)

        raw_cwd = args.get("cwd", "")
        skill_id = args.get("skill_id", "")

        if skill_id and registry:
            try:
                skill_relative_path = _splice_skill_path(raw_cwd or ".", str(skill_id), registry)
                cwd_path = _resolve_safe(ctx, skill_relative_path)
                cwd_str = str(cwd_path)

                skill = registry.get(str(skill_id))
                if skill and skill.relative_path.parent:
                    skill_dir = Path(config.WORKER_DIR) / skill.relative_path.parent
                    success, msg = _install_skill_dependencies(skill_dir)
                    if not success:
                        return f"错误: {msg}"
            except ValueError as e:
                return f"错误: {e}"
        elif raw_cwd:
            try:
                cwd_path = _resolve_safe(ctx, str(raw_cwd))
                cwd_str = str(cwd_path)
            except ValueError as e:
                return f"错误: {e}"
        else:
            cwd_str = str(Path(ctx.work_dir).resolve())

        # 超时值处理
        invalid_timeout_flag = False
        try:
            timeout_raw = args.get("timeout_sec", _RUN_COMMAND_DEFAULT_TIMEOUT)
            timeout_sec = int(float(timeout_raw))
        except (TypeError, ValueError):
            timeout_sec = _RUN_COMMAND_DEFAULT_TIMEOUT
            invalid_timeout_flag = True
        timeout_sec = max(1, min(timeout_sec, _RUN_COMMAND_MAX_TIMEOUT))

        # 使用虚拟环境执行命令
        venv_python = _get_venv_python()

        # 检测并提取 python -c "..." 命令，直接调用 Python 避免 cmd.exe 引号截断问题
        def _extract_python_c_code(cmd_str: str) -> tuple[str | None, str | None]:
            """提取 python -c "..." 命令中的代码部分，返回 (python路径, code) 或 (None, None)"""
            import re
            # 匹配 python -c "..." 或 python -c '...'
            match = re.match(
                r'^python(?:\.exe)?\s+-c\s*(["\'])(.*)\1\s*$',
                cmd_str,
                re.IGNORECASE | re.DOTALL
            )
            if match:
                quote, code = match.groups()
                # 将换行符替换为分号（Python 语句分隔符）
                code = code.replace('\n', '; ')
                python_exe = venv_python or sys.executable
                return python_exe, code
            return None, None

        python_c_exe, python_c_code = _extract_python_c_code(command)

        # 构建使用虚拟环境的命令
        if sys.platform == "win32":
            # 对于 python -c "..." 命令，直接调用 Python 解释器，避免 cmd.exe 引号截断
            if python_c_exe and python_c_code:
                cmd = [python_c_exe, "-c", python_c_code]
            elif (command.lower().strip().startswith("python") or command.lower().strip().endswith(".py")) and venv_python:
                # 替换命令中的python为虚拟环境的python
                cmd_lower = command.lower().strip()
                parts = command.split(None, 1)
                if len(parts) == 2:
                    remaining = parts[1]
                else:
                    remaining = ""
                # 非 -c 的 python 命令仍通过 cmd.exe 执行
                cmd = ["cmd.exe", "/c", f'{venv_python} {remaining}']
            else:
                # 非Python命令：智能路由选择执行器
                if command.lower().startswith("powershell") or _should_use_powershell(command):
                    # PowerShell 命令始终使用 -Command 参数传递完整字符串
                    # 不使用 shlex.split，因为 shlex 是为 POSIX shell 设计的，会破坏 PowerShell 的管道和引号语法
                    remaining = command[len("powershell"):].strip() if command.lower().startswith("powershell") else command
                    # 去除 LLM 可能重复添加的 -Command 前缀及其外层引号
                    remaining_lower = remaining.lower()
                    if remaining_lower.startswith("-command"):
                        remaining = remaining[len("-command"):].strip()
                        if remaining.startswith('"') and remaining.endswith('"'):
                            remaining = remaining[1:-1]
                    # 使用 -NoProfile 加快执行速度，使用 & { } 确保内容被当作代码执行而非字符串
                    cmd = ["powershell.exe", "-NoProfile", "-Command", "& { " + remaining + " }"]
                else:
                    # 对于简单的命令（无管道符、无特殊字符），使用 cmd.exe
                    cmd = ["cmd.exe", "/c", command]
        else:
            # Unix-like 系统
            if command.lower().startswith("powershell"):
                # 同上，始终使用 -Command 传递完整字符串
                remaining = command[len("powershell"):].strip()
                remaining_lower = remaining.lower()
                if remaining_lower.startswith("-command"):
                    remaining = remaining[len("-command"):].strip()
                    if remaining.startswith('"') and remaining.endswith('"'):
                        remaining = remaining[1:-1]
                cmd = ["powershell.exe", "-NoProfile", "-Command", "& { " + remaining + " }"]
            else:
                cmd = ["cmd.exe", "/c", command]

        # 验证和处理 cwd 路径
        valid_cwd = str(Path(ctx.work_dir).resolve())
        try:
            cwd_path = Path(cwd_str)
            if cwd_path.exists() and cwd_path.is_dir():
                valid_cwd = str(cwd_path.resolve())
        except Exception:
            # 如果路径验证失败，回退到默认工作目录
            pass

        # 构建 Popen 参数（注意：不再包含 timeout，改用 communicate() 的 timeout）
        # capture_output 仅适用于 subprocess.run，Popen 需使用 PIPE
        popen_kw: dict = {
            "cwd": valid_cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        # 设置环境变量，确保 Python 脚本输出使用 UTF-8 编码
        # PYTHONIOENCODING: 强制 stdout/stderr 使用 UTF-8
        # PYTHONUTF8: 强制 open() 默认使用 UTF-8 (Python 3.7+)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        popen_kw["env"] = env

        try:
            proc = subprocess.Popen(cmd, **popen_kw)
            try:
                stdout_raw, stderr_raw = proc.communicate(timeout=timeout_sec)
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                # 超时：尝试捕获部分输出
                try:
                    stdout_raw, stderr_raw = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    stdout_raw = proc.stdout.read() if proc.stdout else b""
                    stderr_raw = proc.stderr.read() if proc.stderr else b""

                # 终止进程树
                try:
                    if PSUTIL_AVAILABLE:
                        parent = psutil.Process(proc.pid)
                        children = parent.children(recursive=True)
                        for child in children:
                            try:
                                child.kill()
                            except Exception:
                                pass
                        parent.kill()
                    else:
                        proc.kill()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

                # 格式化超时返回
                captured_output = ""
                if stdout_raw:
                    captured_output += _decode_output(stdout_raw)
                if stderr_raw:
                    captured_output += _decode_output(stderr_raw)
                captured_output = _truncate_run_output(captured_output) if captured_output else "(无)"

                timeout_note = ""
                if invalid_timeout_flag:
                    timeout_note = "\n注意: timeout_sec 参数无效，已使用默认值 60 秒"

                return (
                    f"【执行结果】命令执行超时\n"
                    f"【超时时间】{timeout_sec}秒\n"
                    f"【已输出内容】{captured_output}\n"
                    f"【建议】请检查命令是否需要交互输入，或适当增加 timeout_sec 参数后重试。"
                    f"{timeout_note}"
                )

            # 正常执行完成
            stdout = _decode_output(stdout_raw or b"")
            stderr = _decode_output(stderr_raw or b"")

            # 无效超时参数备注
            timeout_note = ""
            if invalid_timeout_flag:
                timeout_note = "\n注意: timeout_sec 参数无效，已使用默认值 60 秒"

            if returncode == 0:
                # 成功格式
                output_section = stdout
                if stderr and stderr.strip():
                    output_section += "\n" + stderr
                output_section = output_section.strip() if output_section else "(无输出)"

                result = (
                    f"【执行结果】命令执行成功\n"
                    f"【退出码】exit_code: 0\n"
                    f"【输出内容】{output_section}"
                    f"{timeout_note}\n\n"
                    f"✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                )
            else:
                # 失败格式
                stdout_section = stdout if stdout and stdout.strip() else "(无)"
                stderr_section = stderr if stderr and stderr.strip() else "(无)"

                # 根据错误内容添加针对性建议
                error_suggestions = _get_error_suggestions(stderr, stdout)

                # 检测 LLM 是否直接拼了 Skills\xxx\... 这种路径
                skills_path_hint = _detect_skills_path_misuse(command, args)

                result = (
                    f"【执行结果】命令执行失败\n"
                    f"【退出码】exit_code: {returncode}\n"
                    f"【标准输出】{stdout_section}\n"
                    f"【错误输出】{stderr_section}"
                    f"{error_suggestions}"
                    f"{skills_path_hint}"
                    f"{timeout_note}\n\n"
                    f"【重试引导】请分析上述错误信息，检查参数（路径、命令拼写、权限等）是否正确，修正后重新调用 run_command 重试。连续失败时请分析错误原因并调整方案。"
                )

            return _truncate_run_output(result)

        except Exception as e:
            return f"错误: 命令执行异常: {e}"


register_handler(RunCommandHandler())
