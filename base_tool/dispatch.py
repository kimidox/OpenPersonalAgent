from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from skill import SkillRegistry
from .context import ToolContext

_RUN_COMMAND_DEFAULT_TIMEOUT = 60
_RUN_COMMAND_MAX_TIMEOUT = 180
_RUN_COMMAND_MAX_TOTAL_OUT = 12000

# 获取项目根目录下的 PersonalData 路径
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PERSONAL_DATA_DIR = _PROJECT_ROOT / "PersonalData"
_VENV_DIR = _PERSONAL_DATA_DIR / "venv"


def _ensure_venv_exists() -> bool:
    """确保 PersonalData 下存在虚拟环境,如果不存在则创建"""
    if _VENV_DIR.exists() and (_VENV_DIR / "Scripts" / "python.exe").exists():
        return True
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(_VENV_DIR)],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        return (_VENV_DIR / "Scripts" / "python.exe").exists()
    except Exception:
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
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        packages = set()
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pkg_name = line.split("==")[0].lower().replace("-", "_")
                packages.add(pkg_name)
        return packages
    except Exception:
        return set()


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
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            installed_names = ", ".join(sorted(to_install))
            return True, f"已安装依赖: {installed_names}"
        else:
            return False, f"安装依赖失败: {result.stderr}"
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
            rel_path = os.path.join(str(skill_relative_path_parent), rel_path)
            return rel_path
        raise ValueError(f"未找到 Skill 的相对路径: {skill_id}")
    raise ValueError(f"未找到 Skill: {skill_id}")


def _truncate_run_output(text: str, limit: int = _RUN_COMMAND_MAX_TOTAL_OUT) -> str:
    t = text or ""
    if len(t) <= limit:
        return t
    return t[:limit] + "\n\n…（输出已截断）"


def execute_atomic_tool(name: str, args: dict, ctx: ToolContext, registry) -> str:
    if name == "run_command":
        command = str(args.get("command", "") or "").strip()
        if not command:
            return "错误: 缺少 command 参数"
        
        if sys.platform == "win32":
            command = command.replace("/", "\\")
        
        raw_cwd = args.get("cwd", "")
        skill_id = args.get("skill_id", "")
        
        if skill_id and registry:
            try:
                skill_relative_path = _splice_skill_path(raw_cwd or ".", str(skill_id), registry)
                cwd_path = _resolve_safe(ctx, skill_relative_path)
                cwd_str = str(cwd_path)
                
                skill = registry.get(str(skill_id))
                if skill and skill.relative_path.parent:
                    skill_dir = _PERSONAL_DATA_DIR / skill.relative_path.parent
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

        try:
            timeout_raw = args.get("timeout_sec", _RUN_COMMAND_DEFAULT_TIMEOUT)
            timeout_sec = int(float(timeout_raw))
        except (TypeError, ValueError):
            timeout_sec = _RUN_COMMAND_DEFAULT_TIMEOUT
        timeout_sec = max(1, min(timeout_sec, _RUN_COMMAND_MAX_TIMEOUT))

        # 使用虚拟环境执行命令
        venv_python = _get_venv_python()
        venv_activate_script = _get_venv_activate_script()
        
        # 构建使用虚拟环境的命令
        if sys.platform == "win32":
            # Windows: 对于Python脚本，直接使用虚拟环境的Python解释器
            cmd_lower = command.lower().strip()
            if (cmd_lower.startswith("python") or cmd_lower.endswith(".py")) and venv_python:
                # 替换命令中的python为虚拟环境的python
                if cmd_lower.startswith("python"):
                    parts = command.split(None, 1)
                    if len(parts) == 2:
                        command = f'{venv_python} {parts[1]}'
                    else:
                        command = venv_python
                elif cmd_lower.endswith(".py"):
                    command = f'{venv_python} {command}'
                # 使用虚拟环境的Python直接执行，无需激活
                cmd = ["cmd.exe", "/c", command]
            else:
                # 非Python命令，如果需要激活虚拟环境则先激活
                if venv_activate_script:
                    cmd = ["cmd.exe", "/c", f'{venv_activate_script} && cd /d "{cwd_str}" && {command}']
                else:
                    import shlex
                    if command.lower().startswith("powershell"):
                        remaining = command[len("powershell"):].strip()
                        try:
                            parsed = shlex.split(remaining)
                            cmd = ["powershell.exe"] + parsed
                        except:
                            cmd = ["powershell.exe", "-Command", remaining]
                    else:
                        cmd = ["cmd.exe", "/c", command]
        else:
            # Unix-like 系统
            if venv_activate_script:
                cmd = ["/bin/bash", "-c", f"source {venv_activate_script} && cd {cwd_str} && {command}"]
            else:
                import shlex
                if command.lower().startswith("powershell"):
                    remaining = command[len("powershell"):].strip()
                    try:
                        parsed = shlex.split(remaining)
                        cmd = ["powershell.exe"] + parsed
                    except:
                        cmd = ["powershell.exe", "-Command", remaining]
                else:
                    cmd = ["cmd.exe", "/c", command]
        
        popen_kw: dict = {
            "cwd": cwd_str,
            "capture_output": True,
            "text": False,
            "timeout": timeout_sec,
        }
        if sys.platform == "win32":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.run(cmd, **popen_kw)
        except subprocess.TimeoutExpired as e:
            out = _decode_output(e.stdout or b"") + _decode_output(e.stderr or b"")
            tail = _truncate_run_output(out)
            return f"错误: 命令执行超时({timeout_sec}s)\n{tail}".strip()

        stdout = _decode_output(proc.stdout or b"")
        stderr = _decode_output(proc.stderr or b"")
        merged = (
            f"exit_code: {proc.returncode}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}"
        )
        return _truncate_run_output(merged)


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
