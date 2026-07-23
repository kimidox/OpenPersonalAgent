from __future__ import annotations


import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# psutil 可选导入，用于超时时的进程树清理
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

import config
import scheduled_tasks as st_module
from resource_path import paths
from skill import SkillRegistry

from logger import get_module_logger
from .context import ToolContext
from .decorators import atomic_tool

logger = get_module_logger("ToolDispatch")

# UI Automation 模块导入
try:
    from automation import AccessibilityTreeParser, ElementFinder, ActionExecutor
    from automation.uia_client import get_uia_client
    from automation.task_controller import get_controller, reset_controller, TaskController
    from automation.success_rate_tracker import get_tracker
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False

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


def _truncate_run_output(text: str, limit: int = _RUN_COMMAND_MAX_TOTAL_OUT) -> str:
    t = text or ""
    if len(t) <= limit:
        return t
    return t[:limit] + "\n\n…（输出已截断）"


def execute_atomic_tool(name: str, args: dict, ctx: ToolContext, registry) -> str:
    import  json
    if name == "file_operation":
        action = args.get("action", "")
        raw_path = args.get("path", "")
        skill_id = args.get("skill_id", "")
        
        if skill_id and registry:
            try:
                skill_relative_path = _splice_skill_path(raw_path or ".", str(skill_id), registry)
                target_path = _resolve_safe(ctx, skill_relative_path)
            except ValueError as e:
                return f"错误: {e}"
        else:
            try:
                target_path = _resolve_safe(ctx, raw_path)
            except ValueError as e:
                return f"错误: {e}"
        
        if action == "read":
            if not target_path.exists():
                return f"错误: 文件不存在: {target_path}"
            if not target_path.is_file():
                return f"错误: 不是文件: {target_path}"
            try:
                content = target_path.read_text(encoding="utf-8")
                return content + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            except Exception as e:
                return f"错误: 读取文件失败: {e}"
        
        elif action == "write":
            content = args.get("content", "")
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                return f"文件写入成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            except Exception as e:
                return f"错误: 写入文件失败: {e}"
        
        elif action == "delete":
            if not target_path.exists():
                return f"错误: 文件不存在: {target_path}"
            if not target_path.is_file():
                return f"错误: 不是文件: {target_path}"
            try:
                target_path.unlink()
                return f"文件删除成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            except Exception as e:
                return f"错误: 删除文件失败: {e}"
        
        elif action == "list":
            if not target_path.exists():
                return f"错误: 目录不存在: {target_path}"
            if not target_path.is_dir():
                return f"错误: 不是目录: {target_path}"
            try:
                items = list(target_path.iterdir())
                result_lines = []
                for item in sorted(items):
                    if item.is_dir():
                        result_lines.append(f"[DIR]  {item.name}/")
                    else:
                        result_lines.append(f"[FILE] {item.name}")
                return "\n".join(result_lines) if result_lines else "(空目录)"
            except Exception as e:
                return f"错误: 列出目录失败: {e}"
        
        else:
            return f"错误: 未知的 action: {action}，支持 read/write/delete/list"

    if name == "edit":
        raw_path = args.get("path", "")
        old_str = args.get("old_str", "")
        new_str = args.get("new_str", "")
        skill_id = args.get("skill_id", "")
        
        if not old_str:
            return "错误: 缺少 old_str 参数"
        
        if skill_id and registry:
            try:
                skill_relative_path = _splice_skill_path(raw_path or ".", str(skill_id), registry)
                target_path = _resolve_safe(ctx, skill_relative_path)
            except ValueError as e:
                return f"错误: {e}"
        else:
            try:
                target_path = _resolve_safe(ctx, raw_path)
            except ValueError as e:
                return f"错误: {e}"
        
        if not target_path.exists():
            return f"错误: 文件不存在: {target_path}"
        if not target_path.is_file():
            return f"错误: 不是文件: {target_path}"
        
        try:
            content = target_path.read_text(encoding="utf-8")
        except Exception as e:
            return f"错误: 读取文件失败: {e}"
        
        if old_str not in content:
            return f"错误: 未找到要替换的内容"
        
        new_content = content.replace(old_str, new_str, 1)
        
        try:
            target_path.write_text(new_content, encoding="utf-8")
            return f"文件编辑成功: {target_path}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
        except Exception as e:
            return f"错误: 写入文件失败: {e}"

    if name == "run_command":
        # 兼容 LLM 误用 cmd 参数名（实际期望 command）
        command = str(args.get("command") or args.get("cmd") or "").strip()
        if not command:
            return (
                "错误: 缺少 command 参数。请提供要执行的命令行指令。\n"
                "提示：参数名是 `command`（不是 `cmd`）。"
            )

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
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
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

    if name == "create_scheduled_task":
        title = args.get("title", "")
        trigger_time_str = args.get("trigger_time", "")
        content = args.get("content", "")
        repeat_type = args.get("repeat_type", "none")
        execution_type = args.get("execution_type", "notification")
        execution_chain = args.get("execution_chain", None)
        skill_ids_raw = args.get("skill_ids", None)

        if not title:
            return "错误: 缺少 title 参数"
        if not trigger_time_str:
            return "错误: 缺少 trigger_time 参数"

        try:
            trigger_time = datetime.fromisoformat(trigger_time_str)
        except ValueError:
            return f"错误: trigger_time 格式无效，应为 ISO 格式（YYYY-MM-DDTHH:MM:SS）"

        valid_repeat_types = ["none", "daily", "weekly", "monthly"]
        if repeat_type not in valid_repeat_types:
            return f"错误: repeat_type 无效，支持: {', '.join(valid_repeat_types)}"

        valid_execution_types = ["notification", "agent_conversation"]
        if execution_type not in valid_execution_types:
            return f"错误: execution_type 无效，支持: {', '.join(valid_execution_types)}"

        skill_ids = None
        if skill_ids_raw is not None:
            if isinstance(skill_ids_raw, str):
                try:
                    skill_ids = json.loads(skill_ids_raw)
                    if not isinstance(skill_ids, list):
                        return "错误: skill_ids 必须是字符串列表"
                except json.JSONDecodeError:
                    return "错误: skill_ids JSON 解析失败"
            elif isinstance(skill_ids_raw, list):
                skill_ids = skill_ids_raw
            else:
                return "错误: skill_ids 必须是字符串或列表"

        user_id = ctx.user_id or "default"
        source_conversation_id = getattr(ctx, "conversation_id", None)

        try:
            task = st_module.add_task(
                user_id=user_id,
                title=title,
                content=content,
                trigger_time=trigger_time,
                repeat_type=repeat_type,
                execution_type=execution_type,
                execution_chain=execution_chain,
                source_conversation_id=source_conversation_id,
                skill_ids=skill_ids,
            )
            task_info = task.to_dict()
            result = (
                f"定时任务创建成功！\n"
                f"- 任务ID: {task_info['task_id']}\n"
                f"- 标题: {task_info['title']}\n"
                f"- 内容: {task_info['content'] or '(无)'}\n"
                f"- 触发时间: {task_info['trigger_time']}\n"
                f"- 重复类型: {task_info['repeat_type']}\n"
                f"- 执行类型: {task_info['execution_type']}\n"
            )
            if execution_type == "agent_conversation":
                if task_info.get("skill_ids"):
                    result += f"- 关联技能: {', '.join(task_info['skill_ids'])}\n"
                if task_info.get("execution_chain"):
                    chain_preview = task_info["execution_chain"][:100]
                    if len(task_info["execution_chain"]) > 100:
                        chain_preview += "..."
                    result += f"- 执行链路: {chain_preview}\n"
            result += f"- 状态: {task_info['status']}\n\n"
            result += "✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result
        except Exception as e:
            return f"错误: 创建定时任务失败: {e}"

    if name == "list_scheduled_tasks":
        status = args.get("status", None)

        valid_statuses = ["pending", "triggered", "cancelled", "deleted"]
        if status and status not in valid_statuses:
            return f"错误: status 无效，支持: {', '.join(valid_statuses)}"

        user_id = ctx.user_id or "default"

        try:
            tasks = st_module.list_tasks(user_id=user_id, status=status)
            if not tasks:
                status_desc = f"状态为「{status}」的" if status else ""
                return f"当前没有{status_desc}定时任务。\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            task_list = []
            for task in tasks:
                task_info = task.to_dict()
                task_list.append(
                    f"- ID: {task_info['task_id']}\n"
                    f"  标题: {task_info['title']}\n"
                    f"  内容: {task_info['content'] or '(无)'}\n"
                    f"  触发时间: {task_info['trigger_time']}\n"
                    f"  重复类型: {task_info['repeat_type']}\n"
                    f"  状态: {task_info['status']}"
                )

            status_desc = f"（状态: {status})" if status else ""
            result = f"定时任务列表{status_desc}：\n\n" + "\n\n".join(task_list)
            result += "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result
        except Exception as e:
            return f"错误: 获取定时任务列表失败: {e}"

    if name == "delete_scheduled_task":
        task_id = args.get("task_id", "")

        if not task_id:
            return "错误: 缺少 task_id 参数"

        try:
            success = st_module.delete_task(task_id)
            if success:
                return f"定时任务已删除（ID: {task_id}）\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: 未找到任务（ID: {task_id}），可能已被删除"
        except Exception as e:
            return f"错误: 删除定时任务失败: {e}"

    if name == "uploaded_files":
        action = args.get("action", "")
        file_name = args.get("file_name", "")

        if ctx.file_upload_controller is None:
            return "错误: 当前会话没有文件上传功能可用"

        controller = ctx.file_upload_controller

        if action == "list":
            all_files = controller.get_all_files()
            if not all_files:
                return "当前没有已上传的文件。\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            file_list = []
            for f in all_files:
                status = "解析成功" if f.is_success else ("解析失败" if f.parse_error else ("解析中..." if f.is_parsing else "待解析"))
                file_list.append(
                    f"- 文件名: {f.original_name}\n"
                    f"  文件ID: {f.file_id}\n"
                    f"  类型: {f.extension.upper()}\n"
                    f"  大小: {f.get_file_size_display()}\n"
                    f"  上传时间: {f.upload_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"  状态: {status}"
                )
                if f.parse_error:
                    file_list[-1] += f"\n  错误: {f.parse_error}"
                if f.summary:
                    summary_preview = f.summary[:100] + "..." if len(f.summary) > 100 else f.summary
                    file_list[-1] += f"\n  摘要预览: {summary_preview}"

            result = f"已上传文件列表（共 {len(all_files)} 个）：\n\n" + "\n\n".join(file_list)
            result += "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result

        elif action == "get_content":
            if not file_name:
                return "错误: get_content 操作需要提供 file_name 参数"

            all_files = controller.get_all_files()
            target_file = None
            for f in all_files:
                if f.original_name == file_name or f.file_id == file_name:
                    target_file = f
                    break

            if target_file is None:
                available_names = [f.original_name for f in all_files]
                return f"错误: 未找到文件「{file_name}」。可用文件: {', '.join(available_names) if available_names else '无'}"

            if not target_file.is_success:
                if target_file.is_parsing:
                    return f"文件「{file_name}」正在解析中，请稍后再试。"
                elif target_file.parse_error:
                    return f"错误: 文件「{file_name}」解析失败: {target_file.parse_error}"
                else:
                    return f"错误: 文件「{file_name}」尚未解析完成"

            parse_result = target_file.parse_result
            if parse_result is None:
                return f"错误: 文件「{file_name}」没有解析结果"

            content = parse_result.content or ""
            result = f"【文件内容: {target_file.original_name}】\n"
            result += f"类型: {target_file.extension.upper()}\n"
            result += f"大小: {target_file.get_file_size_display()}\n"
            result += f"上传时间: {target_file.upload_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            result += f"--- 文件内容 ---\n{content}\n"

            if parse_result.summary:
                result += f"\n--- 内容摘要 ---\n{parse_result.summary}\n"

            result += "\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result

        elif action == "get_metadata":
            if not file_name:
                return "错误: get_metadata 操作需要提供 file_name 参数"

            all_files = controller.get_all_files()
            target_file = None
            for f in all_files:
                if f.original_name == file_name or f.file_id == file_name:
                    target_file = f
                    break

            if target_file is None:
                available_names = [f.original_name for f in all_files]
                return f"错误: 未找到文件「{file_name}」。可用文件: {', '.join(available_names) if available_names else '无'}"

            metadata_info = {
                "文件名": target_file.original_name,
                "文件ID": target_file.file_id,
                "文件类型": target_file.extension.upper(),
                "MIME类型": target_file.mime_type or "未知",
                "文件大小": target_file.get_file_size_display(),
                "原始路径": str(target_file.file_path),
                "上传时间": target_file.upload_time.strftime("%Y-%m-%d %H:%M:%S"),
                "解析状态": "成功" if target_file.is_success else ("失败" if target_file.parse_error else ("解析中" if target_file.is_parsing else "待解析")),
            }

            if target_file.parse_error:
                metadata_info["解析错误"] = target_file.parse_error

            if target_file.parse_result and hasattr(target_file.parse_result, "metadata"):
                extra_meta = target_file.parse_result.metadata
                if extra_meta:
                    for key, value in extra_meta.items():
                        metadata_info[f"解析元数据.{key}"] = value

            result_lines = [f"【文件元信息: {target_file.original_name}】"]
            for key, value in metadata_info.items():
                result_lines.append(f"- {key}: {value}")

            result = "\n".join(result_lines)
            result += "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            return result

        else:
            return f"错误: 未知的 action: {action}，支持 list/get_content/get_metadata"

    # ===== UI Automation 工具处理 =====

    if name == "get_accessibility_tree":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用，请确保已安装 uiautomation 库"

        # 检查停止条件
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

    if name == "find_element":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
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

    if name == "click_element":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
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

    if name == "type_text":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
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

    if name == "scroll_element":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        # 检查停止条件
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

    if name == "get_element_state":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        element = args.get("element", "")
        window_title = args.get("window_title", None)

        if not element:
            return "错误: 缺少 element 参数"

        try:
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
                controller = get_controller()
                status_summary = controller.get_status_summary()
                output_lines.append("")
                output_lines.append(f"【任务状态】{status_summary}")
                
                return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: {result.get('error', '获取状态失败')}"
        except Exception as e:
            return f"错误: 获取元素状态失败: {e}"

    if name == "start_application":
        app = args.get("app", "")
        method = args.get("method", "by_name")
        wait_time = args.get("wait_time", 2.0)
        app_args = args.get("args", "")

        # 检查停止条件
        controller = get_controller()
        check_result = controller.check_before_operation(f"start_{app}")
        if not check_result.get("can_continue"):
            return f"【任务终止】{check_result.get('stop_reason', '达到停止条件')}\n\n请不要再继续尝试，应重新规划任务或放弃。"

        if not app:
            return "错误: 缺少 app 参数"

        try:
            import webbrowser
            import time

            if method == "by_url":
                # 通过URL启动（打开浏览器）
                webbrowser.open(app)
                if wait_time > 0:
                    time.sleep(wait_time)
                return f"已打开URL: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            elif method == "by_path":
                # 通过路径启动
                # 判断是否是快捷方式
                if app.lower().endswith('.lnk'):
                    # 快捷方式使用 os.startfile
                    os.startfile(app)
                else:
                    # 可执行文件使用 subprocess
                    cmd = [app]
                    if app_args:
                        cmd.append(app_args)
                    subprocess.Popen(cmd, shell=False)
                if wait_time > 0:
                    time.sleep(wait_time)
                
                # 【状态验证】验证启动结果
                if UIA_AVAILABLE:
                    executor = ActionExecutor()
                    verify_result = executor.verify_start_result(app, timeout=wait_time + 2)
                    if verify_result.get("success"):
                        return f"已启动程序: {app}\n验证: {verify_result.get('reason', '已验证')}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    else:
                        # 记录失败
                        failure_info = controller.record_failure(f"start_{app}", verify_result.get("reason", "启动验证失败"))
                        return f"警告: 程序已启动但验证失败: {verify_result.get('reason', '')}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"
                
                return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            elif method == "by_name":
                # 通过程序名启动
                if sys.platform == "win32":
                    # Windows: 尝试多种方式启动
                    
                    # 方式1: 尝试 os.startfile（适用于快捷方式和PATH中的程序）
                    try:
                        os.startfile(app)
                        if wait_time > 0:
                            time.sleep(wait_time)
                        
                        # 【状态验证】验证启动结果
                        if UIA_AVAILABLE:
                            executor = ActionExecutor()
                            verify_result = executor.verify_start_result(app, timeout=wait_time + 2)
                            if verify_result.get("success"):
                                status_summary = controller.get_status_summary()
                                return f"已启动程序: {app}\n验证: {verify_result.get('reason', '已验证')}\n\n【任务状态】{status_summary}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                            else:
                                # 验证失败但程序可能已启动
                                status_summary = controller.get_status_summary()
                                return f"已启动程序: {app}\n警告: 验证失败 - {verify_result.get('reason', '')}\n\n【任务状态】{status_summary}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                        
                        return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    except Exception:
                        pass
                    
                    # 方式2: 使用 subprocess.Popen + shell=True
                    try:
                        cmd = app
                        if app_args:
                            cmd = f"{app} {app_args}"
                        subprocess.Popen(cmd, shell=True)
                        if wait_time > 0:
                            time.sleep(wait_time)
                        return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    except Exception:
                        pass
                    
                    # 方式3: 使用 cmd /c start
                    try:
                        cmd = f'cmd /c start "" "{app}"'
                        if app_args:
                            cmd = f'cmd /c start "" "{app}" "{app_args}"'
                        subprocess.run(cmd, shell=True, timeout=10)
                        if wait_time > 0:
                            time.sleep(wait_time)
                        return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    except Exception as e:
                        # 记录失败
                        failure_info = controller.record_failure(f"start_{app}", str(e))
                        return f"错误: 所有启动方式都失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"
                else:
                    # Linux/Mac: 直接执行
                    cmd = [app]
                    if app_args:
                        cmd.append(app_args)
                    subprocess.Popen(cmd)
                    if wait_time > 0:
                        time.sleep(wait_time)
                    return f"已启动程序: {app}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            else:
                return f"错误: 未知的启动方式: {method}"

        except Exception as e:
            # 记录失败
            failure_info = controller.record_failure(f"start_{app}", str(e))
            return f"错误: 启动程序失败: {e}\n\n{failure_info.get('stop_reason', '')}\n\n【失败统计】{controller.failure_counter.get_status_summary()}"

    if name == "list_installed_apps":
        filter_keyword = args.get("filter", "")
        max_results = args.get("max_results", 50)

        try:

            apps = []

            # 1. 查询 Windows 开始菜单快捷方式（并解析目标路径）
            if sys.platform == "win32":
                start_menu_paths = [
                    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                ]

                for start_path in start_menu_paths:
                    if start_path.exists():
                        for lnk_file in start_path.rglob("*.lnk"):
                            try:
                                name = lnk_file.stem
                                if filter_keyword and filter_keyword.lower() not in name.lower():
                                    continue
                                
                                # 解析快捷方式获取目标路径
                                target_path = ""
                                try:
                                    # 使用 PowerShell 解析快捷方式
                                    ps_script = f'''
                                    $shell = New-Object -ComObject WScript.Shell
                                    $shortcut = $shell.CreateShortcut("{str(lnk_file)}")
                                    $shortcut.TargetPath
                                    '''
                                    result = subprocess.run(
                                        ["powershell", "-Command", ps_script],
                                        capture_output=True,
                                        text=True,
                                        timeout=5,
                                    )
                                    if result.returncode == 0 and result.stdout.strip():
                                        target_path = result.stdout.strip()
                                except Exception:
                                    pass
                                
                                apps.append({
                                    "name": name,
                                    "shortcut_path": str(lnk_file),
                                    "target_path": target_path,  # 实际启动路径
                                    "type": "shortcut",
                                    "launch_command": target_path if target_path else str(lnk_file),
                                })
                                if len(apps) >= max_results:
                                    break
                            except Exception:
                                pass

            # 2. 查询 PATH 环境变量中的可执行程序
            path_env = os.environ.get("PATH", "")
            path_dirs = path_env.split(os.pathsep)

            common_apps = {
                "notepad": ("记事本", "C:\\Windows\\notepad.exe"),
                "calc": ("计算器", "calc.exe"),
                "mspaint": ("画图", "mspaint.exe"),
                "explorer": ("文件资源管理器", "explorer.exe"),
                "cmd": ("命令提示符", "cmd.exe"),
                "powershell": ("PowerShell", "powershell.exe"),
                "chrome": ("Chrome浏览器", "chrome.exe"),
                "firefox": ("Firefox浏览器", "firefox.exe"),
                "msedge": ("Edge浏览器", "msedge.exe"),
                "excel": ("Excel", "excel.exe"),
                "word": ("Word", "winword.exe"),
                "powerpnt": ("PowerPoint", "powerpnt.exe"),
                "outlook": ("Outlook", "outlook.exe"),
                "code": ("VS Code", "code.exe"),
                "notepad++": ("Notepad++", "notepad++.exe"),
                "python": ("Python", "python.exe"),
                "git": ("Git", "git.exe"),
            }

            for path_dir in path_dirs:
                if not path_dir:
                    continue
                try:
                    for exe_file in Path(path_dir).glob("*.exe"):
                        exe_name = exe_file.stem.lower()
                        display_name, default_launch = common_apps.get(exe_name, (exe_name, exe_name))
                        if filter_keyword:
                            if filter_keyword.lower() not in exe_name.lower() and filter_keyword.lower() not in display_name.lower():
                                continue
                        apps.append({
                            "name": display_name,
                            "exe_name": exe_name,
                            "path": str(exe_file),
                            "type": "exe",
                            "in_path": True,
                            "launch_command": exe_name,  # 可以直接用程序名启动
                        })
                        if len(apps) >= max_results:
                            break
                except Exception:
                    pass

            # 3. 查询注册表中的已安装程序（Windows）
            if sys.platform == "win32" and len(apps) < max_results:
                try:
                    # 使用 PowerShell 查询注册表，获取更详细的路径信息
                    ps_script = '''
                    Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,
                                     HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* |
                    Where-Object { $_.DisplayName } |
                    Select-Object DisplayName, InstallLocation, DisplayIcon, UninstallString |
                    ConvertTo-Json -Depth 1
                    '''
                    result = subprocess.run(
                        ["powershell", "-Command", ps_script],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0 and result.stdout:
                        reg_apps = json.loads(result.stdout)
                        if isinstance(reg_apps, list):
                            for app in reg_apps:
                                name = app.get("DisplayName", "")
                                location = app.get("InstallLocation", "")
                                icon = app.get("DisplayIcon", "")
                                uninstall_string = app.get("UninstallString", "")
                                
                                if filter_keyword and filter_keyword.lower() not in name.lower():
                                    continue
                                
                                # 尝试从安装路径推断可执行文件
                                exe_path = ""
                                if location:
                                    try:
                                        # 查找安装目录下的exe文件
                                        for exe in Path(location).glob("*.exe"):
                                            exe_path = str(exe)
                                            break
                                    except Exception:
                                        pass
                                
                                # 尝试从图标路径推断
                                if not exe_path and icon:
                                    exe_path = icon
                                
                                apps.append({
                                    "name": name,
                                    "install_location": location,
                                    "exe_path": exe_path,
                                    "icon": icon,
                                    "type": "installed",
                                    "launch_command": exe_path if exe_path else f"需手动查找: {location}",
                                })
                                if len(apps) >= max_results:
                                    break
                except Exception:
                    pass

            # 去重并格式化输出
            seen_names = set()
            unique_apps = []
            for app in apps:
                name_lower = app.get("name", "").lower()
                if name_lower not in seen_names:
                    seen_names.add(name_lower)
                    unique_apps.append(app)

            # 格式化输出（包含启动路径）
            output_lines = [f"找到 {len(unique_apps)} 个已安装的应用程序:"]
            output_lines.append("")
            output_lines.append("【程序列表】")
            for i, app in enumerate(unique_apps[:max_results], 1):
                name = app.get("name", "")
                app_type = app.get("type", "")
                launch_command = app.get("launch_command", "")
                
                if app_type == "exe":
                    path = app.get("path", "")
                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 类型: PATH可执行文件")
                    output_lines.append(f"   - 路径: {path}")
                    output_lines.append(f"   - 启动命令: start_application(app='{launch_command}')")
                elif app_type == "shortcut":
                    shortcut_path = app.get("shortcut_path", "")
                    target_path = app.get("target_path", "")
                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 类型: 快捷方式")
                    output_lines.append(f"   - 快捷方式路径: {shortcut_path}")
                    output_lines.append(f"   - 目标路径: {target_path}")
                    if target_path:
                        output_lines.append(f"   - 启动命令: start_application(app='{target_path}', method='by_path')")
                    else:
                        output_lines.append(f"   - 启动命令: start_application(app='{shortcut_path}', method='by_path')")
                elif app_type == "installed":
                    location = app.get("install_location", "")
                    exe_path = app.get("exe_path", "")
                    output_lines.append(f"{i}. {name}")
                    output_lines.append(f"   - 类型: 已安装程序")
                    output_lines.append(f"   - 安装路径: {location}")
                    output_lines.append(f"   - 可执行文件: {exe_path}")
                    if exe_path and exe_path.endswith('.exe'):
                        output_lines.append(f"   - 启动命令: start_application(app='{exe_path}', method='by_path')")
                    else:
                        output_lines.append(f"   - 启动命令: 需手动查找可执行文件")
                else:
                    output_lines.append(f"{i}. {name}")
                output_lines.append("")

            output_lines.append("【建议】")
            output_lines.append("根据用户意图选择合适的程序，复制上面的启动命令即可启动程序。")

            return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

        except Exception as e:
            return f"错误: 查询已安装程序失败: {e}"

    if name == "send_hotkey":
        keys = args.get("keys", "")
        target_window = args.get("target_window", None)

        if not keys:
            return "错误: 缺少 keys 参数"

        try:
            import time

            # 键名映射表（将用户输入的键名转换为pyautogui/pydirectinput支持的键名）
            key_mapping = {
                "ctrl": "ctrl",
                "alt": "alt",
                "shift": "shift",
                "win": "win",
                "enter": "enter",
                "esc": "esc",
                "escape": "esc",
                "tab": "tab",
                "backspace": "backspace",
                "delete": "delete",
                "del": "delete",
                "insert": "insert",
                "home": "home",
                "end": "end",
                "pageup": "pageup",
                "pagedown": "pagedown",
                "pgup": "pageup",
                "pgdn": "pagedown",
                "f1": "f1",
                "f2": "f2",
                "f3": "f3",
                "f4": "f4",
                "f5": "f5",
                "f6": "f6",
                "f7": "f7",
                "f8": "f8",
                "f9": "f9",
                "f10": "f10",
                "f11": "f11",
                "f12": "f12",
                "up": "up",
                "down": "down",
                "left": "left",
                "right": "right",
                "space": "space",
                "printscreen": "printscreen",
                "prtsc": "printscreen",
                "pause": "pause",
                "capslock": "capslock",
                "numlock": "numlock",
                "scrolllock": "scrolllock",
            }

            # 解析热键组合
            key_parts = keys.lower().split("+")
            mapped_keys = []
            for part in key_parts:
                part = part.strip()
                mapped_key = key_mapping.get(part, part)
                mapped_keys.append(mapped_key)

            # 如果指定了目标窗口，先激活该窗口
            if target_window:
                try:
                    import ctypes
                    user32 = ctypes.windll.user32

                    # 查找窗口
                    hwnd = user32.FindWindowW(None, target_window)
                    if hwnd:
                        # 激活窗口
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(0.3)  # 等待窗口激活
                    else:
                        return f"警告: 未找到窗口 '{target_window}'，热键将发送到当前焦点窗口"
                except Exception as e:
                    return f"警告: 激活窗口失败: {e}，热键将发送到当前焦点窗口"

            # 发送热键
            # 尝试使用 pyautogui（如果已安装）
            try:
                import pyautogui

                # pyautogui 的 hotkey 函数可以直接接收多个键名
                if len(mapped_keys) == 1:
                    pyautogui.press(mapped_keys[0])
                else:
                    pyautogui.hotkey(*mapped_keys)

                time.sleep(0.1)  # 等待热键生效
                return f"已发送热键: {keys}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

            except ImportError:
                # 如果 pyautogui 未安装，使用 ctypes 直接调用 Win32 API
                try:
                    import ctypes
                    from ctypes import wintypes

                    user32 = ctypes.windll.user32

                    # 虚拟键码映射
                    vk_codes = {
                        "ctrl": 0x11,  # VK_CONTROL
                        "alt": 0x12,   # VK_MENU
                        "shift": 0x10, # VK_SHIFT
                        "win": 0x5B,   # VK_LWIN
                        "enter": 0x0D, # VK_RETURN
                        "esc": 0x1B,   # VK_ESCAPE
                        "tab": 0x09,   # VK_TAB
                        "backspace": 0x08, # VK_BACK
                        "delete": 0x2E,    # VK_DELETE
                        "insert": 0x2D,    # VK_INSERT
                        "home": 0x24,      # VK_HOME
                        "end": 0x23,       # VK_END
                        "pageup": 0x21,    # VK_PRIOR
                        "pagedown": 0x22,  # VK_NEXT
                        "f1": 0x70,
                        "f2": 0x71,
                        "f3": 0x72,
                        "f4": 0x73,
                        "f5": 0x74,
                        "f6": 0x75,
                        "f7": 0x76,
                        "f8": 0x77,
                        "f9": 0x78,
                        "f10": 0x79,
                        "f11": 0x7A,
                        "f12": 0x7B,
                        "up": 0x26,    # VK_UP
                        "down": 0x28,  # VK_DOWN
                        "left": 0x25,  # VK_LEFT
                        "right": 0x27, # VK_RIGHT
                        "space": 0x20, # VK_SPACE
                        "printscreen": 0x2A, # VK_SNAPSHOT
                        "pause": 0x13,       # VK_PAUSE
                        "capslock": 0x14,    # VK_CAPITAL
                        "numlock": 0x90,     # VK_NUMLOCK
                    }

                    # 获取虚拟键码
                    vk_list = []
                    for key in mapped_keys:
                        vk = vk_codes.get(key)
                        if vk:
                            vk_list.append(vk)
                        else:
                            # 对于普通字符键，使用 VkKeyScan
                            vk = user32.VkKeyScanW(ord(key.upper())) & 0xFF
                            vk_list.append(vk)

                    # 按下所有键
                    for vk in vk_list:
                        user32.keybd_event(vk, 0, 0, 0)  # KEYDOWN
                        time.sleep(0.05)

                    # 释放所有键（反向顺序）
                    for vk in reversed(vk_list):
                        user32.keybd_event(vk, 0, 2, 0)  # KEYUP
                        time.sleep(0.05)

                    return f"已发送热键: {keys}\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"

                except Exception as e:
                    return f"错误: 发送热键失败: {e}"

        except Exception as e:
            return f"错误: 发送热键失败: {e}"

    # ========== Skill 管理工具 ==========
    if name == "manage_skill":
        action = args.get("action", "")
        if not action:
            return "错误: 缺少 action 参数"

        if action == "list":
            # 列出所有用户自定义 Skill
            if not registry:
                return "错误: SkillRegistry 不可用"
            user_skills = []
            for skill in registry.list_user_skills():
                user_skills.append({
                    "id": skill.skill_id,
                    "name": skill.name,
                    "description": skill.description[:100] + "..." if len(skill.description) > 100 else skill.description
                })
            if not user_skills:
                return "未找到用户自定义 Skill"
            result_lines = ["用户自定义 Skill 列表：", ""]
            for s in user_skills:
                result_lines.append(f"- **{s['id']}**: {s['name']}")
                result_lines.append(f"  描述：{s['description']}")
            return "\n".join(result_lines)

        if action == "get_info":
            skill_id = args.get("skill_id", "")
            if not skill_id:
                return "错误: 缺少 skill_id 参数"
            if not registry:
                return "错误: SkillRegistry 不可用"
            skill = registry.get(str(skill_id))
            if not skill:
                return f"错误: 未找到 Skill '{skill_id}'"
            import json
            info = {
                "id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "skill_type": skill.skill_type,
                "file_path": str(skill.relative_path) if skill.relative_path else "unknown"
            }
            return json.dumps(info, ensure_ascii=False, indent=2)



        if action == "edit":
            skill_id = args.get("skill_id", "")
            content = args.get("content", "")
            if not skill_id:
                return "错误: 缺少 skill_id 参数"
            if not content:
                return "错误: 缺少 content 参数"
            if not registry:
                return "错误: SkillRegistry 不可用"
            # 检查是否为内置 Skill
            skill = registry.get(str(skill_id))
            if not skill:
                return f"错误: 未找到 Skill '{skill_id}'"
            if skill.skill_type == "builtin":
                return f"错误: 内置 Skill '{skill_id}' 不可修改，仅支持优化用户自定义 Skill"
            # 使用 SkillManager 编辑 Skill
            try:
                from skill.skill_manager import get_manager
                mgr = get_manager()
                success = mgr.edit_skill(str(skill_id), content)
                if success:
                    return f"✓ Skill '{skill_id}' 文档已更新"
                else:
                    return f"错误: Skill '{skill_id}' 更新失败"
            except Exception as e:
                return f"错误: 编辑 Skill 失败: {e}"

        return f"错误: 未知的 action 参数: {action}"

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
