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

from logger import get_module_logger
from .command_validator import CommandValidator
from .context import ToolContext
from .decorators import atomic_tool
from .run_command import validate_and_log_warnings

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

_VENV_DIR = paths.get_venv_dir()


# ============================================================
# 环境检查模块
# ============================================================

def check_pip_available() -> bool:
    """
    检查 pip 是否可用。

    执行 `pip --version` 命令，检查 pip 是否正常工作。

    Returns:
        bool: pip 是否可用
    """
    import shutil

    # 优先检查虚拟环境中的 pip
    venv_pip = _get_venv_pip()
    if venv_pip and Path(venv_pip).exists():
        try:
            result = subprocess.run(
                [venv_pip, "--version"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                logger.debug(f"检测到虚拟环境 pip 可用: {venv_pip}")
                return True
        except Exception as e:
            logger.warning(f"虚拟环境 pip 检查失败: {e}")

    # 检查系统 pip
    pip_path = shutil.which("pip")
    if pip_path:
        try:
            result = subprocess.run(
                [pip_path, "--version"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                logger.debug(f"检测到系统 pip 可用: {pip_path}")
                return True
        except Exception as e:
            logger.warning(f"系统 pip 检查失败: {e}")

    # 检查 python -m pip
    python_path = shutil.which("python") or shutil.which("python3")
    if python_path:
        try:
            result = subprocess.run(
                [python_path, "-m", "pip", "--version"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                logger.debug(f"检测到 python -m pip 可用: {python_path}")
                return True
        except Exception as e:
            logger.warning(f"python -m pip 检查失败: {e}")

    logger.warning("未检测到可用的 pip")
    return False


def check_network_connection() -> bool:
    """
    检查网络连接状态。

    尝试访问 https://pypi.org 或执行 ping 命令检查网络连接。

    Returns:
        bool: 网络是否连接
    """
    import urllib.request
    import socket

    # 方法1: 尝试访问 PyPI
    test_urls = [
        "https://pypi.org",
        "https://mirrors.aliyun.com/pypi/simple/",  # 国内镜像
    ]

    for url in test_urls:
        try:
            request = urllib.request.Request(url, method='HEAD')
            request.add_header('User-Agent', 'Mozilla/5.0')
            urllib.request.urlopen(request, timeout=5)
            logger.debug(f"网络连接正常，成功访问: {url}")
            return True
        except urllib.error.URLError as e:
            logger.debug(f"访问 {url} 失败: {e}")
        except Exception as e:
            logger.debug(f"访问 {url} 异常: {e}")

    # 方法2: 使用 ping 命令检查网络（作为备用方案）
    try:
        # 检测操作系统
        os_type = detect_os_type()

        # 根据操作系统选择 ping 命令
        if os_type == "Windows":
            ping_cmd = ["ping", "-n", "1", "pypi.org"]
        else:  # Linux/Mac
            ping_cmd = ["ping", "-c", "1", "pypi.org"]

        result = subprocess.run(
            ping_cmd,
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )

        if result.returncode == 0:
            logger.debug("网络连接正常（ping 测试成功）")
            return True
        else:
            logger.warning("网络连接异常（ping 测试失败）")
            return False

    except Exception as e:
        logger.warning(f"网络检查异常: {e}")
        return False


def detect_os_type() -> str:
    """
    检测操作系统类型。

    Returns:
        str: 操作系统类型，返回 "Windows"、"Linux" 或 "Mac"
    """
    import platform

    system = platform.system().lower()

    if system == "windows":
        return "Windows"
    elif system == "linux":
        return "Linux"
    elif system == "darwin":
        return "Mac"
    else:
        logger.warning(f"未识别的操作系统: {system}")
        return system.capitalize()


def check_installation_environment() -> dict:
    """
    执行完整的环境检查。

    Returns:
        dict: 包含各项环境检查结果的字典
    """
    import time

    start_time = time.time()

    results = {
        "os_type": detect_os_type(),
        "pip_available": check_pip_available(),
        "network_connected": check_network_connection(),
        "check_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_ms": 0,
    }

    # 计算耗时
    results["elapsed_ms"] = int((time.time() - start_time) * 1000)

    # 记录检查结果
    logger.info(
        f"环境检查完成 - "
        f"操作系统: {results['os_type']}, "
        f"pip可用: {results['pip_available']}, "
        f"网络连接: {results['network_connected']}, "
        f"耗时: {results['elapsed_ms']}ms"
    )

    # 如果环境不满足要求，记录警告
    if not results["pip_available"]:
        logger.warning("pip 不可用，可能导致依赖安装失败")

    if not results["network_connected"]:
        logger.warning("网络连接异常，可能导致下载安装脚本失败")

    return results


def _find_system_python() -> str | None:
    """
    查找系统安装的 Python 解释器（非虚拟环境）。
    始终查找系统级 Python，避免使用虚拟环境中的 Python 来创建新虚拟环境，
    因为虚拟环境可能缺少 ensurepip 模块导致创建的 venv 没有 pip。
    """
    import shutil
    
    candidate_names = ["python", "python3", "py"]
    
    for name in candidate_names:
        python_path = shutil.which(name)
        if python_path and python_path.lower().find("\\venv\\") == -1 and python_path.lower().find("\\virtualenvs\\") == -1:
            return python_path
    
    common_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "python.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Python" / "python.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Python" / "python.exe",
    ]
    for p in common_paths:
        if p.exists() and p.is_file():
            return str(p)
    
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\PythonCore") as key:
            i = 0
            while True:
                version = winreg.EnumKey(key, i)
                subkey = winreg.OpenKey(key, version)
                install_path, _ = winreg.QueryValueEx(subkey, "InstallPath")
                python_exe = Path(install_path) / "python.exe"
                if python_exe.exists():
                    return str(python_exe)
                i += 1
    except (ImportError, OSError, FileNotFoundError):
        pass
    
    return None


def _ensure_venv_exists() -> bool:
    """确保 PersonalData 下存在虚拟环境,如果不存在则创建"""
    if _VENV_DIR.exists() and (_VENV_DIR / "Scripts" / "python.exe").exists():
        return True
    try:
        system_python = _find_system_python()
        if not system_python:
            return False
        
        subprocess.run(
            [system_python, "-m", "venv", str(_VENV_DIR)],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        
        venv_python = str(_VENV_DIR / "Scripts" / "python.exe")
        if not Path(venv_python).exists():
            return False
        
        pip_exe = _VENV_DIR / "Scripts" / "pip.exe"
        if not pip_exe.exists():
            import urllib.request
            import tempfile
            
            get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                temp_file = f.name
            
            try:
                urllib.request.urlretrieve(get_pip_url, temp_file)
                subprocess.run(
                    [venv_python, temp_file],
                    capture_output=True,
                    timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                )
            except Exception as e:
                logger.error(f"安装pip失败: {e}")
            finally:
                try:
                    os.unlink(temp_file)
                except:
                    pass
        
        return True
    except Exception as e:
        logger.error(f"创建虚拟环境异常: {e}")
        return False


def _get_venv_python() -> str | None:
    """获取虚拟环境中的 Python 可执行文件路径"""
    if not _ensure_venv_exists():
        return None
    return str(_VENV_DIR / "Scripts" / "python.exe")


def _get_venv_activate_script() -> str | None:
    """获取激活虚拟环境的脚本路径（不包含call关键字）"""
    if not _ensure_venv_exists():
        return None
    activate_script = _VENV_DIR / "Scripts" / "activate.bat"
    if activate_script.exists():
        return str(activate_script)
    return None


def _get_venv_pip() -> str | None:
    """获取虚拟环境中的 pip 可执行文件路径"""
    if not _ensure_venv_exists():
        return None
    pip_exe = _VENV_DIR / "Scripts" / "pip.exe"
    if pip_exe.exists():
        return str(pip_exe)
    return None


def _get_installed_packages() -> set[str]:
    """获取虚拟环境中已安装的包名集合"""
    venv_python = _get_venv_python()
    if not venv_python:
        return set()
    try:
        result = subprocess.run(
            [venv_python, "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=False,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        stdout = _decode_output(result.stdout or b"")
        packages = set()
        for line in stdout.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].lower().replace("-", "_")
                packages.add(pkg_name)
        return packages
    except Exception:
        return set()


def _check_skill_dependencies(skill_dir: Path) -> tuple[bool, list[str], str]:
    """
    检查 skill 包的依赖是否已安装。
    返回 (是否需要安装, 需要安装的包列表, 错误消息)
    """
    requirements_file = skill_dir / "requirements.txt"
    if not requirements_file.exists():
        return False, [], ""
    
    required_packages = set()
    try:
        content = requirements_file.read_text(encoding="utf-8")
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0]
                pkg_name = pkg_name.lower().replace("-", "_")
                required_packages.add(pkg_name)
    except Exception as e:
        return False, [], f"读取 requirements.txt 失败: {e}"
    
    if not required_packages:
        return False, [], ""
    
    installed = _get_installed_packages()
    to_install = required_packages - installed
    
    if not to_install:
        return False, [], ""
    
    return True, sorted(to_install), ""


def _install_skill_dependencies(skill_dir: Path) -> tuple[bool, str]:
    """
    安装 skill 包的依赖。
    返回 (成功与否, 消息)
    """
    # 执行环境检查（不阻塞安装流程，仅记录状态）
    try:
        env_check = check_installation_environment()
        # 如果环境不满足要求，记录警告但不阻止安装
        if not env_check.get("pip_available"):
            logger.warning(f"环境检查警告: pip 不可用，可能导致依赖安装失败 (skill_dir: {skill_dir})")
        if not env_check.get("network_connected"):
            logger.warning(f"环境检查警告: 网络连接异常，可能导致依赖下载失败 (skill_dir: {skill_dir})")
    except Exception as e:
        # 环境检查失败不影响安装流程
        logger.debug(f"环境检查异常（已忽略）: {e}")

    requirements_file = skill_dir / "requirements.txt"
    if not requirements_file.exists():
        return True, ""

    required_packages = set()
    try:
        content = requirements_file.read_text(encoding="utf-8")
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0]
                pkg_name = pkg_name.lower().replace("-", "_")
                required_packages.add(pkg_name)
    except Exception as e:
        return False, f"读取 requirements.txt 失败: {e}"

    if not required_packages:
        return True, ""

    installed = _get_installed_packages()
    to_install = required_packages - installed

    if not to_install:
        return True, ""

    pip_exe = _get_venv_pip()
    if not pip_exe:
        return False, "无法找到虚拟环境的 pip"

    try:
        result = subprocess.run(
            [pip_exe, "install", "-r", str(requirements_file)],
            capture_output=True,
            text=False,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            installed_names = ", ".join(sorted(to_install))
            return True, f"已安装依赖: {installed_names}"
        else:
            stderr = _decode_output(result.stderr or b"")
            return False, f"安装依赖失败: {stderr}"
    except subprocess.TimeoutExpired:
        return False, "安装依赖超时"
    except Exception as e:
        return False, f"安装依赖异常: {e}"


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


def _fix_powershell_env_variables(command: str) -> str:
    """
    修正 PowerShell 命令中的环境变量引用。

    将 $env:TEMP 替换为实际路径，将 $env:USERPROFILE 替换为实际路径。
    """
    import re

    fixed_command = command

    # 替换 $env:TEMP
    if "$env:TEMP" in command or "$env:temp" in command:
        temp_path = os.environ.get("TEMP", os.environ.get("TMP", ""))
        if temp_path:
            # 使用 lambda 函数避免路径中的反斜杠被解释为正则表达式转义
            fixed_command = re.sub(
                r'\$env:TEMP',
                lambda m: temp_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    # 替换 $env:USERPROFILE
    if "$env:USERPROFILE" in command or "$env:userprofile" in command:
        userprofile_path = os.environ.get("USERPROFILE", "")
        if userprofile_path:
            fixed_command = re.sub(
                r'\$env:USERPROFILE',
                lambda m: userprofile_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    # 替换 $env:APPDATA
    if "$env:APPDATA" in command or "$env:appdata" in command:
        appdata_path = os.environ.get("APPDATA", "")
        if appdata_path:
            fixed_command = re.sub(
                r'\$env:APPDATA',
                lambda m: appdata_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    # 替换 $env:LOCALAPPDATA
    if "$env:LOCALAPPDATA" in command or "$env:localappdata" in command:
        localappdata_path = os.environ.get("LOCALAPPDATA", "")
        if localappdata_path:
            fixed_command = re.sub(
                r'\$env:LOCALAPPDATA',
                lambda m: localappdata_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    return fixed_command


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
   .\install.ps1

方法3: 使用虚拟环境安装
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
如果需要在虚拟环境中安装：

1. 创建虚拟环境（如已存在可跳过）：
   python -m venv %USERPROFILE%\.skillhub_venv

2. 激活虚拟环境：
   %USERPROFILE%\.skillhub_venv\Scripts\activate

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


# ============================================================
# 命令预校验和自动修复机制
# ============================================================

def _detect_and_fix_command(command: str) -> tuple:
    """检测并自动修复命令中的已知问题模式。
    
    返回 (fixed_command, error_message):
    - (fixed_command, ""): 修复成功，返回修复后的命令
    - ("", error_message): 检测到不可修复的问题模式，返回错误提示
    - (command, ""): 无需修复，返回原命令
    """
    if not command:
        return command, ""
    
    # 1. 检测并转换 findstr /C:"..." 模式
    fixed, msg = _fix_findstr_quotes(command)
    if fixed is not None:
        return fixed, msg
    
    # 2. 检测并转换 wmic 命令
    fixed, msg = _fix_wmic_command(command)
    if fixed is not None:
        return fixed, msg
    
    # 3. 检测 %% 批处理语法（不可修复，直接报错）
    if _has_batch_variable_syntax(command):
        return "", "错误: 检测到批处理变量语法 (%%)。请改用 PowerShell 语法：使用 $variable 替代 %%a，使用 ForEach-Object 替代 for /f 循环。"
    
    # 4. 检测并转换常见 CMD 命令为 PowerShell 等效命令
    fixed, msg = _fix_cmd_to_powershell(command)
    if fixed is not None:
        return fixed, msg
    
    return command, ""


def _fix_findstr_quotes(command: str) -> tuple:
    """检测 findstr /C:"..." 模式并转换为 PowerShell Select-String。
    
    返回 (fixed_command, "") 或 None 表示无需处理。
    """
    import re
    
    # 匹配 findstr /C:"..." 或 findstr /C:'...'
    # 例如: systeminfo | findstr /C:"OS Name"
    pattern = r'(\S+)\s*\|\s*findstr\s+((?:/[^ ]+\s+)*)/C:("([^"]*?)"|\'([^\']*?)\')'
    match = re.search(pattern, command, re.IGNORECASE)
    
    if match:
        before_pipe = match.group(1).strip()
        findstr_args = match.group(2).strip()  # /B /C:... 等参数
        search_pattern = match.group(4) or match.group(5)  # 引号内的内容
        
        # 分析 findstr 参数，转换为 Select-String 等效参数
        select_string_args = []
        
        # 提取搜索模式
        if search_pattern:
            # 检查是否是 /C: 格式的属性名匹配（如 "OS Name"、"System Type"）
            # 这种模式通常用于 systeminfo/wmic 输出过滤
            # 转换为 PowerShell 的 Where-Object 或 Select-String
            select_string_args.append(f"Select-String -Pattern '{search_pattern}'")
        
        # 构建 PowerShell 命令
        fixed = f"powershell {before_pipe} | {' '.join(select_string_args)}"
        return fixed, ""
    
    return None, None


def _fix_wmic_command(command: str) -> tuple:
    """检测 wmic 命令并转换为 Get-CimInstance 等效命令。
    
    返回 (fixed_command, "") 或 None 表示无需处理。
    """
    import re
    
    # 匹配 wmic 命令: wmic <class> get <properties>
    pattern = r'wmic\s+(\w+)\s+get\s+(.+?)(?:\s*$|\s*&&|\s*2>|\s*>)'
    match = re.search(pattern, command, re.IGNORECASE)
    
    if match:
        wmic_class = match.group(1).strip()
        properties = match.group(2).strip().rstrip(',').strip()
        
        # 映射常见 WMIC 类到 CIM 类
        cim_class_map = {
            'cpu': 'Win32_Processor',
            'os': 'Win32_OperatingSystem',
            'memorychip': 'Win32_PhysicalMemory',
            'baseboard': 'Win32_BaseBoard',
            'bios': 'Win32_BIOS',
            'diskdrive': 'Win32_DiskDrive',
            'logicaldisk': 'Win32_LogicalDisk',
            'nic': 'Win32_NetworkAdapter',
            'nicconfig': 'Win32_NetworkAdapterConfiguration',
            'useraccount': 'Win32_UserAccount',
            'group': 'Win32_Group',
            'service': 'Win32_Service',
            'process': 'Win32_Process',
            'computersystem': 'Win32_ComputerSystem',
            'share': 'Win32_Share',
        }
        
        # 属性名映射
        prop_map = {
            'name': 'Name',
            'numberofcores': 'NumberOfCores',
            'numberoflogicalprocessors': 'NumberOfLogicalProcessors',
            'maxclockspeed': 'MaxClockSpeed',
            'caption': 'Caption',
            'version': 'Version',
            'serialnumber': 'SerialNumber',
            'manufacturer': 'Manufacturer',
            'model': 'Model',
            'capacity': 'Capacity',
            'speed': 'Speed',
            'size': 'Size',
            'freespace': 'FreeSpace',
            'description': 'Description',
            'status': 'Status',
            'state': 'State',
        }
        
        cim_class = cim_class_map.get(wmic_class.lower(), f'Win32_{wmic_class.title()}')
        
        # 转换属性名
        ps_props = []
        for prop in properties.split(','):
            prop = prop.strip()
            ps_prop = prop_map.get(prop.lower(), prop)
            ps_props.append(ps_prop)
        
        fixed = f"powershell Get-CimInstance {cim_class} | Select-Object {', '.join(ps_props)}"
        return fixed, ""
    
    return None, None


def _has_batch_variable_syntax(command: str) -> bool:
    """检测命令是否包含 %% 批处理变量语法。"""
    import re
    # 匹配 %%a, %%A, %%i 等批处理变量
    return bool(re.search(r'%%[a-zA-Z]', command))


def _fix_cmd_to_powershell(command: str) -> tuple:
    """检测常见 CMD 命令并转换为 PowerShell 等效命令。
    
    返回 (fixed_command, "") 或 None 表示无需处理。
    """
    import re
    
    # 匹配 systeminfo 命令
    if re.match(r'^systeminfo\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,TotalVisibleMemorySize,FreePhysicalMemory; Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory; Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors", ""
    
    # 匹配 whoami 命令
    if re.match(r'^whoami\s*$', command.strip(), re.IGNORECASE):
        return "powershell [System.Security.Principal.WindowsIdentity]::GetCurrent().Name", ""
    
    # 匹配 hostname 命令
    if re.match(r'^hostname\s*$', command.strip(), re.IGNORECASE):
        return "powershell $env:COMPUTERNAME", ""
    
    # 匹配 ipconfig 命令
    if re.match(r'^ipconfig\s*(?:/all)?\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-NetIPAddress | Select-Object InterfaceAlias,IPAddress,AddressFamily,PrefixLength", ""
    
    # 匹配 tasklist 命令
    if re.match(r'^tasklist\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-Process | Select-Object Name,Id,WorkingSet64,CPU | Sort-Object WorkingSet64 -Descending", ""
    
    # 匹配 netstat 命令
    if re.match(r'^netstat\s*(?:-an|-ano)?\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-NetTCPConnection | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State | Sort-Object LocalPort", ""
    
    return None, None


def _should_use_powershell(command: str) -> bool:
    """判断命令是否应该使用 PowerShell 执行。
    
    返回 True 如果命令应该用 PowerShell 执行，否则 False。
    """
    # 已经是 PowerShell 命令
    if command.lower().startswith("powershell"):
        return True
    
    # Python 命令不用 PowerShell
    cmd_lower = command.lower().strip()
    if cmd_lower.startswith("python") or cmd_lower.endswith(".py"):
        return False
    
    # 检测是否包含 PowerShell 特有语法
    powershell_patterns = [
        r'\bGet-\w+',      # Get- 开头的 cmdlet
        r'\bSet-\w+',      # Set- 开头的 cmdlet
        r'\bSelect-\w+',   # Select- 开头的 cmdlet
        r'\bWhere-\w+',    # Where- 开头的 cmdlet
        r'\bForEach-Object\b',
        r'\bSort-Object\b',
        r'\|',             # 管道符（PowerShell 管道更可靠）
        r'\$env:',         # 环境变量引用
        r'\[System\.',     # .NET 类型引用
    ]
    
    for pattern in powershell_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    
    return False


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
    from .handlers import get_handler, ensure_registered
    ensure_registered()
    handler = get_handler(name)
    if handler is not None:
        return handler.execute(args, ctx, registry)
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


def check_skill_dependencies(skill_id: str, registry: SkillRegistry) -> tuple[bool, list[str], str]:
    """
    检查指定 skill 的依赖是否已安装。
    返回 (是否需要安装, 需要安装的包列表, 错误消息)
    """
    skill = registry.get(str(skill_id))
    if not skill:
        return False, [], f"未找到 Skill: {skill_id}"
    
    if not skill.relative_path.parent:
        return False, [], ""
    
    skill_dir = Path(config.WORKER_DIR) / skill.relative_path.parent
    return _check_skill_dependencies(skill_dir)


def install_skill_dependencies(skill_id: str, registry: SkillRegistry) -> tuple[bool, str]:
    """
    安装指定 skill 的依赖。
    返回 (成功与否, 消息)
    """
    skill = registry.get(str(skill_id))
    if not skill:
        return False, f"未找到 Skill: {skill_id}"
    
    if not skill.relative_path.parent:
        return True, ""
    
    skill_dir = Path(config.WORKER_DIR) / skill.relative_path.parent
    return _install_skill_dependencies(skill_dir)


def install_skill_from_zip(zip_path: str, registry: SkillRegistry, overwrite: bool = False) -> tuple[list[str], str]:
    """
    从 ZIP 包安装 Skill。
    
    Args:
        zip_path: ZIP 文件路径
        registry: SkillRegistry 实例
        overwrite: 是否覆盖已存在的 Skill
        
    Returns:
        (安装的 skill_id 列表, 错误消息)
    """
    try:
        from skill.skill_manager import get_manager
        mgr = get_manager()
        installed_ids = mgr.install_from_zip(zip_path, overwrite=overwrite)
        # 刷新 registry
        if registry and installed_ids:
            registry.reload()
        return installed_ids, ""
    except FileNotFoundError as e:
        return [], f"ZIP文件不存在: {zip_path}"
    except ValueError as e:
        return [], str(e)
    except FileExistsError as e:
        return [], f"Skill已存在: {e}，如需覆盖请设置 overwrite=True"
    except Exception as e:
        return [], f"安装ZIP包失败: {e}"


def splice_skill_path(rel_path: str, skill_id: str, registry: SkillRegistry) -> str:
    """将相对路径拼接到 skill 包目录下"""
    return _splice_skill_path(rel_path, skill_id, registry)


# ============================================================
# 安装成功验证机制
# ============================================================

def verify_skillhub_installation() -> tuple[bool, str]:
    """
    验证 SkillHub CLI 是否安装成功。

    执行 `skillhub --version` 命令，检查 SkillHub CLI 是否可用。

    Returns:
        tuple[bool, str]: (是否验证成功, 版本信息或错误消息)
    """
    try:
        # 执行 skillhub --version 命令
        result = subprocess.run(
            ["skillhub", "--version"],
            capture_output=True,
            text=False,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )

        # 解码输出
        stdout = _decode_output(result.stdout or b"")
        stderr = _decode_output(result.stderr or b"")

        if result.returncode == 0:
            # 提取版本信息
            version_info = stdout.strip() if stdout.strip() else "版本信息未知"
            logger.info(f"SkillHub CLI 验证成功: {version_info}")
            return True, f"验证成功，版本信息: {version_info}"
        else:
            error_msg = stderr.strip() if stderr.strip() else "未知错误"
            logger.warning(f"SkillHub CLI 验证失败: {error_msg}")
            return False, f"验证失败，错误: {error_msg}"

    except FileNotFoundError:
        # skillhub 命令不存在
        error_msg = "SkillHub CLI 未安装或未添加到 PATH 环境变量"
        logger.warning(error_msg)
        return False, error_msg + _get_skillhub_installation_guide()
    except subprocess.TimeoutExpired:
        error_msg = "验证超时，SkillHub CLI 可能未正确安装"
        logger.warning(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"验证异常: {e}"
        logger.error(error_msg)
        return False, error_msg


def verify_skill_installation(skill_dir: str) -> tuple[bool, str]:
    """
    验证 Skill 是否安装成功。

    检查目标目录是否存在 SKILL.md 文件，并验证元数据是否正确。

    Args:
        skill_dir: Skill 安装目录路径

    Returns:
        tuple[bool, str]: (是否验证成功, 消息)
    """
    try:
        skill_path = Path(skill_dir)

        # 检查目录是否存在
        if not skill_path.exists():
            return False, f"Skill 目录不存在: {skill_dir}"

        if not skill_path.is_dir():
            return False, f"路径不是目录: {skill_dir}"

        # 检查 SKILL.md 文件是否存在
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            return False, f"SKILL.md 文件不存在: {skill_file}"

        if not skill_file.is_file():
            return False, f"SKILL.md 不是文件: {skill_file}"

        # 读取并解析 SKILL.md 文件
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception as e:
            return False, f"读取 SKILL.md 失败: {e}"

        # 解析 YAML front matter
        metadata = _parse_skill_yaml_front_matter(content)

        if metadata is None:
            return False, f"SKILL.md 文件格式错误: 缺少有效的 YAML front matter"

        # 验证必要的元数据字段
        required_fields = ["id", "name"]
        missing_fields = [field for field in required_fields if not metadata.get(field)]

        if missing_fields:
            return False, f"SKILL.md 元数据缺少必要字段: {', '.join(missing_fields)}"

        # 验证成功
        skill_id = metadata.get("id", "")
        skill_name = metadata.get("name", "")
        skill_description = metadata.get("description", "")

        logger.info(f"Skill 验证成功: ID={skill_id}, Name={skill_name}")

        return True, (
            f"验证成功:\n"
            f"- Skill ID: {skill_id}\n"
            f"- 名称: {skill_name}\n"
            f"- 描述: {skill_description[:50]}..." if len(skill_description) > 50 else f"- 描述: {skill_description}"
        )

    except Exception as e:
        error_msg = f"验证异常: {e}"
        logger.error(error_msg)
        return False, error_msg


def _parse_skill_yaml_front_matter(content: str) -> dict | None:
    """
    解析 SKILL.md 文件的 YAML front matter。

    Args:
        content: Markdown 文件内容

    Returns:
        dict | None: 解析后的元数据字典，解析失败返回 None
    """
    try:
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        yaml_content = parts[1].strip()

        try:
            metadata = yaml.safe_load(yaml_content)
            if not isinstance(metadata, dict):
                return None
            return metadata
        except yaml.YAMLError as e:
            logger.warning(f"YAML 解析失败: {e}")
            return None

    except Exception as e:
        logger.warning(f"解析 YAML front matter 失败: {e}")
        return None


def _get_skillhub_installation_guide() -> str:
    """
    获取 SkillHub CLI 安装指引。

    Returns:
        str: 安装指引字符串
    """
    return """

【SkillHub CLI 安装指引】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

方法1: 使用 pip 安装（推荐）
pip install skillhub-cli

方法2: 使用安装脚本
Invoke-WebRequest -Uri "https://skillhub.cn/install.ps1" | Invoke-Expression

方法3: 从 GitHub 安装
pip install git+https://github.com/skillhub/skillhub-cli.git

【验证安装】
安装完成后，请在新的终端窗口中运行：
skillhub --version

如果提示"命令未找到"，请：
1. 确认 Python 已正确安装并添加到 PATH
2. 重新打开终端窗口
3. 检查 pip 安装路径是否在 PATH 中
"""


def verify_and_report_skillhub_installation() -> str:
    """
    验证 SkillHub CLI 安装并返回详细的报告。

    Returns:
        str: 验证报告字符串
    """
    success, message = verify_skillhub_installation()

    if success:
        report = f"""
✓ SkillHub CLI 安装验证成功

{message}

【下一步】
您可以开始使用 SkillHub CLI 安装 Skill：
1. 列出可用的 Skill: skillhub list
2. 安装 Skill: skillhub install <skill_id>
3. 查看帮助: skillhub --help
"""
    else:
        report = f"""
✗ SkillHub CLI 安装验证失败

{message}

【故障排查建议】
1. 确认已正确安装 SkillHub CLI
2. 检查 Python 和 pip 是否正确安装
3. 确认安装路径已添加到 PATH 环境变量
4. 尝试重新打开终端窗口
"""

    return report


def verify_and_report_skill_installation(skill_dir: str) -> str:
    """
    验证 Skill 安装并返回详细的报告。

    Args:
        skill_dir: Skill 安装目录路径

    Returns:
        str: 验证报告字符串
    """
    success, message = verify_skill_installation(skill_dir)

    if success:
        report = f"""
✓ Skill 安装验证成功

安装目录: {skill_dir}

{message}

【下一步】
您现在可以使用此 Skill：
- 查看 Skill 详情: manage_skill(action="get_info", skill_id="<id>")
- 列出已安装 Skill: manage_skill(action="list")
"""
    else:
        report = f"""
✗ Skill 安装验证失败

安装目录: {skill_dir}

{message}

【故障排查建议】
1. 确认 Skill 目录路径正确
2. 检查 SKILL.md 文件是否存在
3. 验证 SKILL.md 文件格式是否正确（YAML front matter）
4. 检查元数据是否包含必要的字段（id、name）
"""

    return report


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
