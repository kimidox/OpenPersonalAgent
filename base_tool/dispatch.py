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
