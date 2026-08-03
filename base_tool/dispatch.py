"""原子工具调度核心模块。

职责：工具注册与分发、命令安全检测、输出处理、UIA 惰性加载。

注意：大量辅助函数已按职责拆分到子模块，本文件通过重新导出保持
所有 ``from base_tool.dispatch import xxx`` 的兼容性。

拆分目标：
- environment.py    → 环境检查 / 虚拟环境管理
- skill_installer.py → Skill 依赖检查与安装
- command_fixer.py   → 命令预校验与自动修复
- installation_verifier.py → 安装验证与报告
"""
from __future__ import annotations


import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

# psutil 可选导入，用于超时时的进程树清理
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

import config
import scheduled_tasks as st_module
from resource_path import paths

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from skill import SkillRegistry

from logger import get_module_logger, generate_trace_id
from .command_validator import CommandValidator
from .context import ToolContext
from .decorators import atomic_tool
from .run_command import validate_and_log_warnings

# ── 从子模块重新导出，保持外部 import 路径不断裂 ──────────────

# environment
from .environment import (                          # noqa: F401
    check_pip_available,
    check_network_connection,
    detect_os_type,
    check_installation_environment,
    _find_system_python,
    _ensure_venv_exists,
    _get_venv_python,
    _get_venv_activate_script,
    _get_venv_pip,
    _VENV_DIR,
)

# skill_installer
from .skill_installer import (                      # noqa: F401
    _check_skill_dependencies,
    _install_skill_dependencies,
    check_skill_dependencies,
    install_skill_dependencies,
    install_skill_from_zip,
    _get_installed_packages,
)

# command_fixer
from .command_fixer import (                        # noqa: F401
    _detect_and_fix_command,
    _fix_findstr_quotes,
    _fix_wmic_command,
    _has_batch_variable_syntax,
    _fix_cmd_to_powershell,
    _should_use_powershell,
    _fix_powershell_env_variables,
)

# installation_verifier
from .installation_verifier import (                # noqa: F401
    verify_skillhub_installation,
    verify_skill_installation,
    verify_and_report_skillhub_installation,
    verify_and_report_skill_installation,
    _parse_skill_yaml_front_matter,
    _get_skillhub_installation_guide,
)

logger = get_module_logger("ToolDispatch")

# UI Automation 模块惰性加载：避免启动时同步加载 automation 子模块链，
# 首个 UI 自动化工具调用时才导入（UIA_AVAILABLE 语义由 _ensure_uia() 保留）
UIA_AVAILABLE: bool | None = None  # None=未探测，True/False=探测结果


def _ensure_uia() -> bool:
    """首次调用时导入 UI Automation 符号到模块全局，返回是否可用。"""
    global UIA_AVAILABLE
    global AccessibilityTreeParser, ElementFinder, ActionExecutor
    global get_uia_client, get_controller, reset_controller, TaskController, get_tracker
    if UIA_AVAILABLE is None:
        try:
            from automation import (
                AccessibilityTreeParser as _ATP,
                ElementFinder as _EF,
                ActionExecutor as _AE,
            )
            from automation.uia_client import get_uia_client as _guc
            from automation.task_controller import (
                get_controller as _gc,
                reset_controller as _rc,
                TaskController as _TC,
            )
            from automation.success_rate_tracker import get_tracker as _gt

            AccessibilityTreeParser = _ATP
            ElementFinder = _EF
            ActionExecutor = _AE
            get_uia_client = _guc
            get_controller = _gc
            reset_controller = _rc
            TaskController = _TC
            get_tracker = _gt
            UIA_AVAILABLE = True
        except ImportError:
            UIA_AVAILABLE = False
    return UIA_AVAILABLE

_RUN_COMMAND_DEFAULT_TIMEOUT = 60
_RUN_COMMAND_MAX_TIMEOUT = 180
_RUN_COMMAND_MAX_TOTAL_OUT = 12000

_DANGEROUS_COMMAND_PATTERNS = [
    r'^\s*rm\s+(-rf?|--force)\s+/',          # rm -rf /
    r'^\s*format\s+',                          # format C:
    r'^\s*del\s+(/f|/s|/q)*\s+\*\.?\s*$',     # del *.* /f
    r'^\s*rd\s+(/s|/q)*\s+[a-zA-Z]:\\$',      # rd /s /q C:\
    r'^\s*shutdown\s+(/a)',                    # shutdown abort
    r'^\s*diskpart\s+',                        # diskpart
    r'^\s*fsutil\s+usn\s+deletejournal',       # fsutil usn deletejournal
    r'^\s*cipher\s+(/w)',                      # cipher /w
    r'^\s*reg\s+delete\s+.*\s+(/f)',          # reg delete ... /f
    r'^\s*net\s+user\s+',                      # net user (user management)
]


# ============================================================
# 核心调度函数
# ============================================================

def _resolve_safe(ctx: ToolContext, rel: str) -> Path:
    root = Path(ctx.work_dir).resolve()
    rel = (rel or ".").strip().replace("\\", "/")
    if rel in ("", "."):
        return root
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise ValueError("路径必须位于工作目录内") from e
    return candidate


def _splice_skill_path(rel_path: str, skill_id: str, registry: SkillRegistry) -> str:
    """将相对路径拼接到 skill 包目录下"""
    skill = registry.get(str(skill_id))
    if skill:
        skill_relative_path_parent = skill.relative_path.parent
        if skill_relative_path_parent:
            skill_dir = str(skill_relative_path_parent)
            normalized_rel_path = rel_path.replace("\\", "/")
            normalized_skill_dir = skill_dir.replace("\\", "/")
            if normalized_rel_path.startswith(normalized_skill_dir + "/"):
                return rel_path
            if normalized_skill_dir in normalized_rel_path:
                idx = normalized_rel_path.find(normalized_skill_dir)
                if idx >= 0:
                    start = idx + len(normalized_skill_dir)
                    suffix = normalized_rel_path[start:]
                    if suffix.startswith("/"):
                        suffix = suffix[1:]
                    return f"{skill_dir}/{suffix}" if suffix else skill_dir
            return os.path.join(skill_dir, rel_path)
        raise ValueError(f"未找到 Skill 的相对路径: {skill_id}")
    raise ValueError(f"未找到 Skill: {skill_id}")


def _detect_dangerous_command(command: str) -> bool:
    """检测命令是否匹配危险命令模式"""
    for pattern in _DANGEROUS_COMMAND_PATTERNS:
        if re.match(pattern, command, re.IGNORECASE):
            return True
    return False


def _detect_skills_path_misuse(command: str, args: dict) -> str:
    """检测 LLM 是否直接拼了 Skills\\xxx\\... 这种路径访问 skill 包内文件。

    若检测到，返回引导文本；否则返回空字符串。
    """
    if not command:
        return ""
    cmd = command.replace("\\", "/")
    # 命令里出现 Skills/ 且本次调用没传 skill_id
    has_skills_prefix = "skills/" in cmd.lower()
    has_skill_id = bool(args.get("skill_id"))
    if not has_skills_prefix or has_skill_id:
        return ""

    # 判断是读文件类命令（type/Get-Content/cat/Read-Host）还是执行脚本
    read_cmd_patterns = (
        r"\btype\b", r"\bget-content\b", r"\bcat\b", r"\bread-host\b",
        r"\bget-childitem\b", r"\bdir\b", r"\bls\b",
    )
    is_read_op = any(re.search(p, cmd, re.IGNORECASE) for p in read_cmd_patterns)

    if is_read_op:
        return (
            "\n\n【路径提示】检测到直接拼 `Skills\\xxx\\...` 路径访问 skill 包内文件。\n"
            "- 工作目录不是 Skills 的父目录，这种路径无法解析。\n"
            "- 正确做法：使用 `file_operation(action=\"read\"|\"list\", path=\"<相对skill包的路径>\", skill_id=\"<id>\")`。\n"
            "- 例：读取 skill 包下 example/a.md → file_operation(action=\"read\", path=\"example/a.md\", skill_id=\"<当前skill_id>\")"
        )
    return (
        "\n\n【路径提示】检测到命令中含 `Skills\\xxx\\...` 路径但未传 skill_id。\n"
        "- 执行 skill 包内脚本时，应使用 `run_command(command=\"python scripts/xxx.py ...\", skill_id=\"<id>\")`，"
        "命令中只写相对 skill 包目录的路径（如 scripts/xxx.py），不要拼 `Skills\\xxx\\` 前缀。"
    )


def _get_error_suggestions(stderr: str, stdout: str = "") -> str:
    """根据错误内容返回针对性的建议"""
    combined = (stderr or "") + (stdout or "")
    if not combined:
        return ""

    suggestions = []

    # 命令不存在
    if "不是内部或外部命令" in combined or "'不是内部或外部命令" in combined:
        suggestions.append("提示: 命令不存在，请检查命令拼写或确保程序已安装并加入PATH")

    # 权限不足
    if "拒绝访问" in combined or "Access is denied" in combined:
        suggestions.append("提示: 权限不足，请尝试以管理员权限运行或使用其他命令")

    # 文件/路径不存在
    if "系统找不到指定的文件" in combined or "The system cannot find the file" in combined:
        suggestions.append("提示: 文件或路径不存在，请检查路径是否正确")

    # 超时
    if "timeout" in combined.lower() or "超时" in combined:
        suggestions.append("提示: 命令执行超时，可能需要增加 timeout_sec 参数")

    # Python 模块缺失
    if "ModuleNotFoundError" in combined or "No module named" in combined:
        suggestions.append("提示: 缺少Python模块，请使用 pip install 安装所需依赖")

    # findstr 引号解析错误
    if "FINDSTR: 无法打开" in combined or "FINDSTR: Cannot open" in combined:
        suggestions.append("提示: findstr /C:\"包含空格的字符串\" 模式中的双引号被 cmd.exe 错误解析。请改用 PowerShell 命令: powershell Get-CimInstance 或 powershell Select-String")

    if suggestions:
        return "\n" + "\n".join(suggestions)
    return ""


# ============================================================
# 安装失败自动重试和备用方案机制
# ============================================================

def handle_installation_failure(command: str, error_output: str, exit_code: int, retry_count: int = 0) -> tuple[str, bool]:
    """
    处理 SkillHub 安装失败的自动重试和备用方案。

    Args:
        command: 原始执行的命令
        error_output: 错误输出
        exit_code: 命令退出码
        retry_count: 当前重试次数

    Returns:
        (处理后的命令或指引字符串, 是否应该重试)
        - 如果应该重试，返回修正后的命令
        - 如果不应该重试，返回手动安装指引字符串
    """
    # 最大重试次数
    MAX_RETRIES = 3

    # 检测是否已达到最大重试次数
    if retry_count >= MAX_RETRIES:
        return _get_manual_installation_guide(command, error_output), False

    # 场景1: 检测 PowerShell 环境变量解析失败
    if "找不到驱动器。名为\"$env\"的驱动器不存在" in error_output or \
       "Cannot find drive. The drive name $env does not exist" in error_output:
        fixed_command = _fix_powershell_env_variables(command)
        if fixed_command != command:
            logger.info(f"检测到 PowerShell 环境变量解析失败，已修正命令: {command} -> {fixed_command}")
            return fixed_command, True

    # 场景2: 检测下载失败（404、超时）
    if _is_download_failure(error_output):
        # 尝试备用方案：pip install skillhub-cli
        fallback_command = _get_fallback_installation_command(command)
        if fallback_command:
            logger.info(f"检测到下载失败，切换到备用安装方案: {fallback_command}")
            return fallback_command, True

    # 其他情况：返回手动安装指引
    return _get_manual_installation_guide(command, error_output), False


def _is_download_failure(error_output: str) -> bool:
    """
    检测是否为下载失败。

    检测 404、超时、连接失败等下载相关错误。
    """
    error_lower = error_output.lower()

    # 404 错误
    if "404" in error_output or "not found" in error_lower:
        return True

    # 超时错误
    if "timeout" in error_lower or "timed out" in error_lower or "超时" in error_output:
        return True

    # 连接失败
    if "could not connect" in error_lower or "connection refused" in error_lower or \
       "连接失败" in error_output or "无法连接" in error_output:
        return True

    # DNS 解析失败
    if "could not resolve" in error_lower or "name resolution" in error_lower or \
       "dns" in error_lower:
        return True

    # SSL/TLS 错误
    if "ssl" in error_lower or "tls" in error_lower or "certificate" in error_lower:
        return True

    return False


def _get_fallback_installation_command(command: str) -> str | None:
    """
    获取备用安装命令。

    优先尝试 pip install skillhub-cli。
    """
    # 执行环境检查（不阻塞安装流程，仅记录状态）
    try:
        env_check = check_installation_environment()
        # 如果环境不满足要求，记录警告但不阻止安装
        if not env_check.get("pip_available"):
            logger.warning("环境检查警告: pip 不可用，备用安装可能失败")
        if not env_check.get("network_connected"):
            logger.warning("环境检查警告: 网络连接异常，备用安装可能失败")
    except Exception as e:
        # 环境检查失败不影响安装流程
        logger.debug(f"环境检查异常（已忽略）: {e}")

    # 检测是否为 SkillHub 安装命令
    # 典型命令: Invoke-WebRequest -Uri "https://skillhub.cn/install.ps1" | Invoke-Expression
    if "skillhub" in command.lower() and ("install" in command.lower() or "invoke-webrequest" in command.lower()):
        # 检查 pip 是否可用
        venv_pip = _get_venv_pip()
        if venv_pip:
            return f'"{venv_pip}" install skillhub-cli'

        # 检查系统 pip
        import shutil
        pip_path = shutil.which("pip")
        if pip_path:
            return f'"{pip_path}" install skillhub-cli'

        # 尝试使用 python -m pip
        venv_python = _get_venv_python()
        if venv_python:
            return f'"{venv_python}" -m pip install skillhub-cli'

    return None


def _get_manual_installation_guide(command: str, error_output: str) -> str:
    """
    生成手动安装指引。

    当所有自动重试失败后，提供详细的手动安装步骤。
    """
    guide = """
【SkillHub 安装失败 - 手动安装指引】

自动安装尝试已失败，请按照以下步骤手动安装 SkillHub：

方法1: 使用 pip 安装（推荐）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 打开命令提示符（CMD）或 PowerShell
2. 执行以下命令：

   pip install skillhub-cli

   如果提示权限不足，请使用：

   pip install --user skillhub-cli

方法2: 使用 Python 安装脚本
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
如果 pip 不可用，可以尝试：

1. 下载安装脚本：
   - 访问官网: https://skillhub.cn
   - 或直接下载: https://skillhub.cn/install.ps1

2. 在 PowerShell 中运行：
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   .\\install.ps1

方法3: 使用虚拟环境安装
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
如果需要在虚拟环境中安装：

1. 创建虚拟环境（如已存在可跳过）：
   python -m venv %USERPROFILE%\\.skillhub_venv

2. 激活虚拟环境：
   %USERPROFILE%\\.skillhub_venv\\Scripts\\activate

3. 安装 SkillHub：
   pip install skillhub-cli

【错误详情】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
原始命令: {command}
错误信息: {error}

【常见问题】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q: 提示"pip 不是内部或外部命令"
A: 请先安装 Python 并确保勾选 "Add Python to PATH" 选项

Q: 提示"权限不足"
A: 使用 --user 参数或以管理员身份运行命令提示符

Q: 网络连接失败
A: 检查网络连接，或使用国内镜像源：
   pip install skillhub-cli -i https://pypi.tuna.tsinghua.edu.cn/simple

【获取帮助】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
官网: https://skillhub.cn
文档: https://skillhub.cn/docs
GitHub: https://github.com/skillhub/skillhub-cli
""".format(command=command, error=error_output[:200] if len(error_output) > 200 else error_output)

    return guide


def _truncate_run_output(text: str, limit: int = None) -> str:
    """
    截断工具输出内容

    Args:
        text: 原始文本
        limit: 截断长度限制，如果为 None 则从配置文件读取

    Returns:
        截断后的文本，如果发生截断会添加提示信息
    """
    import config

    t = text or ""

    # 从配置读取截断阈值
    if limit is None:
        limit = config.TOOL_OUTPUT_MAX_LENGTH

    if len(t) <= limit:
        return t

    # 截断并添加提示信息
    truncated = t[:limit]

    if config.TOOL_TRUNCATE_SHOW_DETAILS:
        # 显示详细信息
        truncated += f"\n\n…（输出已截断：原始长度 {len(t)} 字符，显示 {limit} 字符）"
    else:
        # 简洁提示
        truncated += "\n\n…（输出已截断）"

    return truncated


def execute_atomic_tool(name: str, args: dict, ctx: ToolContext, registry) -> str:
    """通过 Handler 注册表分发原子工具调用。

    将原先 1867 行的 if/elif 链替换为注册表查找 + Handler.execute() 调用。
    每个 Handler 实现与原 if 分支完全等价的逻辑。

    Business purpose:
        统一原子工具的调度入口，支持注册表式扩展和分发。

    Parameters:
        name: 工具名称（如 "file_operation", "run_command" 等）
        args: LLM 传入的工具参数字典
        ctx: 工具上下文（工作目录、权限等）
        registry: Skill 注册表（可选，部分工具需要用于路径解析和依赖安装）

    Returns:
        工具执行结果字符串

    Key branches:
        - Handler 命中: 调用 handler.execute(args, ctx, registry)
        - Handler 未命中: 返回 "未知原子工具: {name}" 错误信息

    Side effects:
        首次调用时触发 Handler 自动注册（导入所有 handler 子模块）

    Modification notes:
        2026-07-29: 由 if/elif 链重构为注册表分发

    Related tests:
        tests/test_dispatch_handlers.py (待补充)
    """
    trace_id = generate_trace_id("dispatch")
    logger.debug_with_context(f"execute_atomic_tool: tool={name}", trace_id=trace_id, operation_type="tool_dispatch", phase="start")
    from .handlers import get_handler, ensure_registered
    ensure_registered()
    handler = get_handler(name)
    # AI-BRANCH-MARKER: 工具分发分支 — handler命中走执行路径，未命中返回错误
    if handler is not None:
        try:
            handler_result = handler.execute(args, ctx, registry)
            logger.debug_with_context(f"execute_atomic_tool: tool={name} completed", trace_id=trace_id, operation_type="tool_dispatch", phase="complete")
            return handler_result
        except Exception as e:
            # 捕获所有未预期的异常，防止主进程崩溃
            logger.debug_with_context(f"execute_atomic_tool: tool={name} exception {e}", trace_id=trace_id, operation_type="tool_dispatch", phase="error", error_code="exception")
            logger.exception(f"工具 [{name}] 执行异常: {e}")
            return f"错误: 工具 {name} 执行异常: {e}"
    logger.debug_with_context(f"execute_atomic_tool: unknown tool={name}", trace_id=trace_id, operation_type="tool_dispatch", phase="error", error_code="unknown_tool")
    return f"未知原子工具: {name}"


def _decode_output(data: bytes) -> str:
    """智能解码命令输出，优先尝试常见编码"""
    encodings = ["utf-8", "gbk", "gb2312", "cp936", "utf-16"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def splice_skill_path(rel_path: str, skill_id: str, registry: SkillRegistry) -> str:
    """将相对路径拼接到 skill 包目录下"""
    return _splice_skill_path(rel_path, skill_id, registry)


def _register_all_atomic_tools() -> None:
    """将所有原子工具的实现注册到统一工具注册表。

    注意：工具定义已在 ToolRegistry.__init__() 的 _load_builtin_tools() 中注册，
    这里只负责将实现函数绑定到已有工具上，因此使用 overwrite=True。
    """
    from .registry import get_tool_registry
    from .definitions import ATOMIC_TOOL_DEFINITIONS

    registry = get_tool_registry()

    for tool_def in ATOMIC_TOOL_DEFINITIONS:
        tool_name = tool_def.get("name", "")
        if tool_name:
            registry.register_tool(
                tool_name=tool_name,
                tool_definition={
                    "name": tool_name,
                    "category": "atomic",
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("parameters", {}),
                },
                implementation=lambda name=tool_name, args=None, ctx=None, reg=None: execute_atomic_tool(name, args or {}, ctx, reg),
                overwrite=True,
            )


_register_all_atomic_tools()
