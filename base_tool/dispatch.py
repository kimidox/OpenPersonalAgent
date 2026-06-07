from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config
import scheduled_tasks as st_module
from resource_path import paths
from skill import SkillRegistry
from skill.loader import load_skill_memory_lazy
from .context import ToolContext

# UI Automation 模块导入
try:
    from automation import AccessibilityTreeParser, ElementFinder, ActionExecutor
    from automation.uia_client import get_uia_client
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False

_RUN_COMMAND_DEFAULT_TIMEOUT = 60
_RUN_COMMAND_MAX_TIMEOUT = 180
_RUN_COMMAND_MAX_TOTAL_OUT = 12000

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
                print(f"安装pip失败: {e}")
            finally:
                try:
                    os.unlink(temp_file)
                except:
                    pass
        
        return True
    except Exception as e:
        print(f"创建虚拟环境异常: {e}")
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


def _truncate_run_output(text: str, limit: int = _RUN_COMMAND_MAX_TOTAL_OUT) -> str:
    t = text or ""
    if len(t) <= limit:
        return t
    return t[:limit] + "\n\n…（输出已截断）"


def execute_atomic_tool(name: str, args: dict, ctx: ToolContext, registry) -> str:
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
        command = str(args.get("command", "") or "").strip()
        if not command:
            return "错误: 缺少 command 参数"
        
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

        try:
            timeout_raw = args.get("timeout_sec", _RUN_COMMAND_DEFAULT_TIMEOUT)
            timeout_sec = int(float(timeout_raw))
        except (TypeError, ValueError):
            timeout_sec = _RUN_COMMAND_DEFAULT_TIMEOUT
        timeout_sec = max(1, min(timeout_sec, _RUN_COMMAND_MAX_TIMEOUT))

        # 使用虚拟环境执行命令
        venv_python = _get_venv_python()
        
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
                # 非Python命令直接执行，不需要虚拟环境
                if command.lower().startswith("powershell"):
                    import shlex
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
            if command.lower().startswith("powershell"):
                import shlex
                remaining = command[len("powershell"):].strip()
                try:
                    parsed = shlex.split(remaining)
                    cmd = ["powershell.exe"] + parsed
                except:
                    cmd = ["powershell.exe", "-Command", remaining]
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
        
        popen_kw: dict = {
            "cwd": valid_cwd,
            "capture_output": True,
            "text": False,
            "timeout": timeout_sec,
        }
        if sys.platform == "win32":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        
        # 设置环境变量，确保 Python 脚本输出使用 UTF-8 编码
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        popen_kw["env"] = env

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
        result = _truncate_run_output(merged)
        if proc.returncode == 0:
            result = result + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
        return result

    if name == "read_memory":
        if ctx.memory is None:
            return "错误: memory 对象不可用"
        
        query = args.get("query", "")
        limit = args.get("limit", 10)
        
        if query and query.strip():
            # 使用关键词检索
            segments = ctx.memory.search_long_term_memory(query, limit=limit)
            if not segments:
                return f"未找到与关键词「{query}」相关的记忆"
            
            memory_parts = []
            for seg in segments:
                if seg.created_at and hasattr(seg.created_at, 'strftime'):
                    timestamp = seg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                elif seg.created_at:
                    timestamp = str(seg.created_at)
                else:
                    timestamp = ""
                score_info = f" (相关度: {seg.score:.2f})" if seg.score else ""
                memory_parts.append(f"## [{timestamp}]{score_info}\n{seg.content}")
            memory_content = "\n".join(memory_parts)
            return memory_content
        else:
            # 不提供查询时返回所有记忆（向后兼容）
            return ctx.memory.get_long_term_memory()

    if name == "write_memory":
        content = args.get("content", "")
        mode = args.get("mode", "append")

        if ctx.memory is None:
            return "错误: memory 对象不可用"

        if mode == "append":
            ctx.memory.append_long_term_memory(content)
            return "已追加到长期记忆\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
        elif mode == "overwrite":
            ctx.memory.update_long_term_memory(content)
            return "已更新长期记忆\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
        else:
            return f"错误: 未知的 mode 参数: {mode}，支持 'append' 或 'overwrite'"

    if name == "load_skill_memory":
        skill_id = args.get("skill_id", "")
        query = args.get("query", None)
        limit = args.get("limit", 5)

        if not skill_id:
            return "错误: 缺少 skill_id 参数"

        if registry is None:
            return "错误: SkillRegistry 不可用"

        skill = registry.get(str(skill_id))
        if skill is None:
            return f"错误: 未找到 Skill: {skill_id}"

        load_skill_memory_lazy(skill, registry, query=query, limit=limit)

        if skill.memory_content and skill.memory_content.strip():
            return f"### Skill「{skill_id}」执行经验\n\n{skill.memory_content.strip()}\n\n请参考以上经验，避免重复之前的错误。"
        return f"Skill「{skill_id}」暂无执行经验记录。"

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
                return llm_readable + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: {result.get('error', '未知错误')}"
        except Exception as e:
            return f"错误: 获取 Accessibility Tree 失败: {e}"

    if name == "find_element":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        method = args.get("method", "")
        query = args.get("query", "")
        window_title = args.get("window_title", None)
        max_results = args.get("max_results", 50)

        if not method or not query:
            return "错误: 缺少 method 或 query 参数"

        try:
            finder = ElementFinder()

            if method == "by_name":
                result = finder.find_by_name(
                    name=query,
                    window_title=window_title,
                    max_results=max_results,
                )
            elif method == "by_automation_id":
                result = finder.find_by_automation_id(
                    automation_id=query,
                    window_title=window_title,
                )
            elif method == "by_control_type":
                result = finder.find_by_control_type(
                    control_type=query,
                    window_title=window_title,
                    max_results=max_results,
                )
            elif method == "by_coordinates":
                # 解析坐标
                coords = query.split(",")
                if len(coords) != 2:
                    return "错误: 坐标格式应为 x,y"
                x, y = int(coords[0].strip()), int(coords[1].strip())
                result = finder.find_by_coordinates(x=x, y=y)
            elif method == "by_pattern":
                result = finder.find_by_pattern(
                    pattern=query,
                    window_title=window_title,
                    max_results=max_results,
                )
            else:
                return f"错误: 未知的查找方法: {method}"

            if result.get("success"):
                # 格式化输出
                if "results" in result:
                    elements = result["results"]
                    output_lines = [f"找到 {len(elements)} 个元素:"]
                    for elem in elements:
                        output_lines.append(
                            f"- [{elem.get('control_type', 'Unknown')}] {elem.get('name', '')}"
                            f" (id: {elem.get('automation_id', '')})"
                        )
                    return "\n".join(output_lines) + "\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                elif "result" in result:
                    elem = result["result"]
                    return (
                        f"找到元素:\n"
                        f"- 类型: {elem.get('control_type', 'Unknown')}\n"
                        f"- 名称: {elem.get('name', '')}\n"
                        f"- AutomationId: {elem.get('automation_id', '')}\n"
                        f"- 边界: {elem.get('bounding_rectangle', (0, 0, 0, 0))}\n"
                        f"- Patterns: {', '.join(elem.get('patterns', []))}\n\n"
                        f"✓ 操作成功。如果任务已完成，请调用 finish 结束。"
                    )
            else:
                return f"错误: {result.get('error', '未找到元素')}"
        except Exception as e:
            return f"错误: 查找元素失败: {e}"

    if name == "click_element":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        element = args.get("element", "")
        method = args.get("method", "invoke")
        wait_time = args.get("wait_time", 0.1)
        window_title = args.get("window_title", None)

        if not element:
            return "错误: 缺少 element 参数"

        try:
            executor = ActionExecutor()

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                # JSON 格式
                element_info = json.loads(element)

            result = executor.click(
                element=element_info,
                method=method,
                wait_time=wait_time,
            )

            if result.get("success"):
                return f"点击成功 (方法: {method})\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: {result.get('error', '点击失败')}"
        except Exception as e:
            return f"错误: 点击元素失败: {e}"

    if name == "type_text":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

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

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                element_info = json.loads(element)

            result = executor.type_text(
                element=element_info,
                text=text,
                method=method,
                clear_first=clear_first,
                wait_time=wait_time,
            )

            if result.get("success"):
                return f"输入成功 (方法: {method}, 文本长度: {len(text)})\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: {result.get('error', '输入失败')}"
        except Exception as e:
            return f"错误: 输入文本失败: {e}"

    if name == "scroll_element":
        if not UIA_AVAILABLE:
            return "错误: UI Automation 模块不可用"

        element = args.get("element", "")
        direction = args.get("direction", "down")
        amount = args.get("amount", "small")
        count = args.get("count", 1)
        window_title = args.get("window_title", None)

        if not element or not direction:
            return "错误: 缺少 element 或 direction 参数"

        try:
            executor = ActionExecutor()

            # 解析元素信息
            element_info = element
            if element.startswith("{") or element.startswith("["):
                element_info = json.loads(element)

            result = executor.scroll(
                element=element_info,
                direction=direction,
                amount=amount,
                count=count,
            )

            if result.get("success"):
                return f"滚动成功 (方向: {direction}, 次数: {count})\n\n✓ 操作成功。如果任务已完成，请调用 finish 结束。"
            else:
                return f"错误: {result.get('error', '滚动失败')}"
        except Exception as e:
            return f"错误: 滚动元素失败: {e}"

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

        if not app:
            return "错误: 缺少 app 参数"

        try:
            import subprocess
            import webbrowser
            import os
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
                        return f"错误: 所有启动方式都失败: {e}"
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
            return f"错误: 启动程序失败: {e}"

    if name == "list_installed_apps":
        filter_keyword = args.get("filter", "")
        max_results = args.get("max_results", 50)

        try:
            import os
            import subprocess
            from pathlib import Path

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
                        import json
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
