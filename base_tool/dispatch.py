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
            return f"错误: 命令执行超时（{timeout_sec}s）\n{tail}".strip()

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
