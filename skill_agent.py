from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import config
from base_tool import (
    ToolContext,
    execute_atomic_tool,
    check_skill_dependencies,
    install_skill_dependencies,
)
from skill_agent_preferences import load_disabled_skill_ids
from executor import Executor
from llm import get_chat_model
from llm.token_usage import TokenUsage
from memory import Memory
from memory.compactor import ContextCompactor, estimate_messages_tokens
from memory.conversation import Conversation
from prompt import DynamicSystemPrompt
from prompt.template import (
    SKILL_CATALOG_SECTION_TEMPLATE,
    ACTIVE_SKILLS_SECTION_TEMPLATE,
    USER_MEMORY_SECTION_TEMPLATE,
    RECENT_MEMORY_SUMMARY_SECTION_TEMPLATE,
)
from skill import (
    SkillRegistry,
    build_skills_catalog_text,
    execute_skill_control_tool,
    skills_auto_matched_for_query,
    format_skill_for_prompt,
)
from skill.memory_summarizer import summarize_skill_execution, save_skill_memory

SKILL_AGENT_AWAITING_USER_REPLY = "__SKILL_AGENT_AWAITING_USER_REPLY__"


def _ask_user_ui_log_payload(args: dict[str, Any]) -> str:
    choices_raw = args.get("choices")
    choices: list[str] = []
    if isinstance(choices_raw, list):
        for c in choices_raw:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                choices.append(s)
    payload = {
        "question": str(args.get("question", "")).strip(),
        "context": str(args.get("context", "")).strip(),
        "choices": choices,
    }
    return json.dumps(payload, ensure_ascii=False)


def _message_text(message: Any) -> str:
    c = getattr(message, "content", None)
    if isinstance(c, str) and c.strip():
        return c.strip()
    return ""


def _history_without_system(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in messages if m.get("role") != "system"]


def _build_system_prompt(catalog: str, constraints: str = "") -> str:
    dp = DynamicSystemPrompt()
    dp.update_skill_catalog(catalog)
    if constraints.strip():
        dp.update_conversation_constraints(constraints.strip())
    return dp.build()


class SkillAgent:
    """
    Skill Agent：根据用户业务提问选择并执行合适的Skill流程。

    **重复检测机制**（双层防护）：
    1. **通用重复检测**（_check_repeated_tool_call）：
       - 适用范围：所有原子工具（run_command、read_file等）
       - 检测方式：基于 tool_name + args 的 MD5 哈希值匹配
       - 响应策略：第1-2次返回警告，≥3次自动终止

    2. **写入操作特例检测**（_check_repeated_write_success）：
       - 适用范围：仅限 run_command 中的文件写入操作
       - 检测方式：基于命令文本匹配 + 文件存在性验证
       - 响应策略：连续2次相同写入命令即自动终止
       - 额外功能：验证文件是否成功创建

    两者协同工作，提供全面的重复调用保护。
    """
    def __init__(
        self,
        work_dir: str,
        *,
        skills_dir: str | Path | None = None,
        max_steps: int | None = None,
        executor: Executor | None = None,
        memory: Memory | None = None,
        conversation_id: str | None = None,
        username: str ,
        file_upload_controller: Any = None,
    ) -> None:
        self.work_dir = str(Path(work_dir).resolve())
        sd = skills_dir if skills_dir is not None else config.SKILLS_DIR
        builtin_sd = config.BUILTIN_SKILLS_DIR
        self.registry = SkillRegistry(sd, builtin_sd)
        self.max_steps = int(max_steps if max_steps is not None else config.SKILL_AGENT_MAX_STEPS)
        self.executor = executor
        self.memory = memory
        self.username = username
        if memory is not None:
            cid = (conversation_id or "").strip()
            self._conversation_id = cid
        else:
            self._conversation_id = (conversation_id or "").strip()
        self._tool_ctx = ToolContext(
            work_dir=self.work_dir,
            executor=executor,
            memory=memory,
            user_id=self.username,
            file_upload_controller=file_upload_controller,
        )
        self._recent_commands: list[tuple[str, str]] = []
        self._compactor: ContextCompactor | None = None
        self._token_usage = TokenUsage.empty()
        self._dynamic_prompt = DynamicSystemPrompt()
        self._conversation_constraints: str = ""
        self._last_user_query: str | None = None
        self._stop_event = threading.Event()
        self._recent_tool_calls: list[dict] = []
        self._consecutive_repeat_count: int = 0
        self._uploaded_files_content: str = ""

    def set_file_upload_controller(self, controller: Any) -> None:
        self._tool_ctx.file_upload_controller = controller

    def set_uploaded_files_content(self, content: str) -> None:
        self._uploaded_files_content = content or ""

    @property
    def _get_compactor(self) -> ContextCompactor | None:
        if self._compactor is None and self.memory is not None:
            model = get_chat_model()
            self._compactor = ContextCompactor(self.memory, model)
        return self._compactor

    def _should_compact(self, messages: list[dict[str, Any]]) -> bool:
        if self.memory is None:
            return False
        compactor = self._get_compactor
        if compactor is None:
            return False
        return compactor.should_compact(messages)

    def _perform_compaction(
        self,
        messages: list[dict[str, Any]],
        log_callback: Callable[[str, str], Any] | None = None,
    ) -> list[dict[str, Any]]:
        compactor = self._get_compactor
        if compactor is None:
            return messages
        return compactor.compact(self._conversation_id, messages, log_callback)

    def _disabled_skill_ids_frozen(self) -> frozenset[str]:
        return frozenset(load_disabled_skill_ids())

    def _update_system_message(self, messages: list[dict]) -> None:
        """更新消息列表中的系统消息"""
        # 使用最近保存的用户查询来重新构建系统提示词
        disabled = self._disabled_skill_ids_frozen()
        skills_visible = [s for s in self.registry.list_skills() if s.skill_id not in disabled]
        catalog = build_skills_catalog_text(skills_visible)
        
        # 获取当前的 active skills
        active_skill_text: list[str] = []
        active_skill_ids: list[str] = []
        if self.memory is not None:
            saved_skill_ids = self.memory.get_active_skills(self._conversation_id)
            if saved_skill_ids:
                for sid in saved_skill_ids:
                    skill = self.registry.get(sid)
                    if skill:
                        formatted_skill = format_skill_for_prompt(skill)
                        active_skill_text.append(formatted_skill)
                        active_skill_ids.append(sid)
        
        new_system_prompt = self._build_dynamic_system_prompt(
            catalog, 
            active_skill_text=active_skill_text if active_skill_text else None,
            active_skill_ids=active_skill_ids if active_skill_ids else None,
            user_query=self._last_user_query
        )
        
        print(f"[DEBUG-exec] 更新系统提示词：{new_system_prompt}")
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = new_system_prompt
        else:
            messages.insert(0, {"role": "system", "content": new_system_prompt})

    def _build_active_skills_text(self, active_skill_text: list[str], active_skill_ids: list[str]) -> str:
        if not active_skill_text:
            return ""
        parts = [
            f"### 已加载 Skill #{i + 1}: {active_skill_ids[i]}\n\n{t.strip()}"
            for i, t in enumerate(active_skill_text)
        ]
        merged = "\n\n---\n\n".join(parts)
        return ACTIVE_SKILLS_SECTION_TEMPLATE.format(skills=merged)

    def _fill_user_memory(self, query: str | None = None, limit: int = 5) -> str:
        if self.memory is None:
            return ""
        try:
            if query:
                segments = self.memory.search_long_term_memory(query, limit)
                if not segments:
                    return ""
                memory_parts = []
                for seg in segments:
                    timestamp = seg.created_at.strftime("%Y-%m-%d %H:%M:%S") if seg.created_at else ""
                    memory_parts.append(f"## [{timestamp}]\n{seg.content}")
                memory_content = "\n".join(memory_parts)
            else:
                memory_content = self.memory.get_long_term_memory()
            
            if not memory_content or not memory_content.strip():
                return ""
            return USER_MEMORY_SECTION_TEMPLATE.format(memory=memory_content.strip())
        except Exception:
            return ""

    def _fill_recent_memory_summary(self) -> str:
        if self.memory is None:
            return ""
        try:
            recent_summary = self.memory.get_recent_conversations_summary(limit=5)
            if not recent_summary or not recent_summary.strip():
                return ""
            return RECENT_MEMORY_SUMMARY_SECTION_TEMPLATE.format(summary=recent_summary.strip())
        except Exception:
            return ""

    def _build_tool_catalog_text(self, tool_catalog: list[dict]) -> str:
        if not tool_catalog:
            return ""
        lines = ["## 可用工具目录（简要描述）\n"]
        lines.append("以下是可用工具的简要描述。如需使用某个工具，请先调用 `request_tool_details` 获取完整参数定义。\n")
        for tool in tool_catalog:
            name = tool.get("name", "")
            brief = tool.get("brief", "")
            lines.append(f"- **{name}**: {brief}")
        return "\n".join(lines)

    def get_base_info(self) -> str:
        base_info = f"用户名：{self.username}\n"
        base_info+=f"当前系统时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return base_info
    def _build_dynamic_system_prompt(
        self,
        catalog: str,
        active_skill_text: list[str] | None = None,
        active_skill_ids: list[str] | None = None,
        user_query: str | None = None,
        tool_catalog: str | None = None,
    ) -> str:
        self._dynamic_prompt.clear_all_placeholders()
        base_info=self.get_base_info()
        self._dynamic_prompt.update_base_info(base_info)
        self._dynamic_prompt.update_skill_catalog(catalog)
        if tool_catalog:
            self._dynamic_prompt.update_tool_catalog(tool_catalog)
        if active_skill_text and active_skill_ids:
            active_skills_section = self._build_active_skills_text(active_skill_text, active_skill_ids)
            if active_skills_section:
                self._dynamic_prompt.update_active_skills(active_skills_section)
        user_memory_section = self._fill_user_memory(query=user_query)
        if user_memory_section:
            self._dynamic_prompt.update_user_memory(user_memory_section)
        recent_summary_section = self._fill_recent_memory_summary()
        if recent_summary_section:
            self._dynamic_prompt.update_recent_memory_summary(recent_summary_section)
        if self._conversation_constraints:
            self._dynamic_prompt.update_conversation_constraints(self._conversation_constraints)
        if self._uploaded_files_content:
            self._dynamic_prompt.update_uploaded_files(self._uploaded_files_content)
        return self._dynamic_prompt.build()

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    def reload_skills(self) -> None:
        self.registry.reload()

    def start_new_conversation(self) -> tuple[str, str]:
        if self.memory is None:
            self._conversation_id = ""
            return (self._conversation_id, "")
        self._conversation_id = str(uuid.uuid4())
        title = self.memory.ensure_conversation(self._conversation_id,title=f"新会话-{self._conversation_id[:5]}")
        return (self._conversation_id, title)

    def set_conversation_id(self, conversation_id: str) -> None:
        self._conversation_id = (conversation_id or "").strip()

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def set_conversation_constraints(self, constraints: str) -> None:
        self._conversation_constraints = (constraints or "").strip()

    def clear_conversation_constraints(self) -> None:
        self._conversation_constraints = ""

    def clear_runtime_cache(self) -> None:
        """清理运行时缓存，释放内存"""
        self._recent_tool_calls.clear()
        self._recent_commands.clear()
        self._dynamic_prompt.clear_all_placeholders()

    def get_conversation_constraints(self) -> str:
        return self._conversation_constraints

    def list_saved_conversations(self) -> list[Conversation]:
        if self.memory is None:
            return []
        return self.memory.list_user_conversations()

    def message_records_for_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        if self.memory is None:
            return []
        return self.memory.get_message_records((conversation_id or "").strip())

    @staticmethod
    def conversation_awaits_user_clarification(
        memory: Memory | None,
        conversation_id: str,
    ) -> bool:
        if memory is None:
            return False
        cid = (conversation_id or "").strip()
        if not cid:
            return False
        records = memory.get_message_records(cid)
        if not records:
            return False
        last = records[-1]
        if last.get("role") != "tool":
            return False
        meta = last.get("metadata") or {}
        if meta.get("name") != "ask_user":
            return False
        content = str(last.get("content", "") or "")
        if content.startswith("错误"):
            return False
        return True

    def _is_dangerous_command(self, command: str) -> bool:
        if not config.DANGEROUS_COMMAND_CHECK_ENABLED:
            return False
        
        cmd_lower = command.lower().strip()
        
        for pattern in config.DANGEROUS_COMMAND_PREFIXES:
            if cmd_lower.startswith(pattern):
                return True
        
        for pattern in config.DANGEROUS_COMMAND_CONTAINS:
            if pattern in cmd_lower:
                return True
        
        return False

    def _is_write_operation(self, command: str) -> bool:
        cmd_lower = command.lower().strip()
        write_indicators = [
            ">", ">>", "set-content", "write-host", "write-output",
            "out-file", "add-content", "echo ", "mkdir ", "md ",
            "copy ", "move ", "del ", "erase ", "rmdir ", "ren "
        ]
        for indicator in write_indicators:
            if indicator in cmd_lower:
                return True
        return False

    def _is_package_install_command(self, command: str) -> tuple[bool, list[str]]:
        """
        检测是否为包安装命令，并提取要安装的包名。
        返回 (是否为包安装命令, 包名列表)
        """
        import re
        cmd_lower = command.lower().strip()
        
        install_patterns = [
            (r"pip\s+install\s+(.+)", "pip"),
            (r"pip3\s+install\s+(.+)", "pip3"),
            (r"python\s+-m\s+pip\s+install\s+(.+)", "python -m pip"),
            (r"python3\s+-m\s+pip\s+install\s+(.+)", "python3 -m pip"),
            (r"conda\s+install\s+(.+)", "conda"),
            (r"npm\s+install\s+(.+)", "npm"),
            (r"npm\s+i\s+(.+)", "npm"),
            (r"npm\s+add\s+(.+)", "npm"),
            (r"yarn\s+add\s+(.+)", "yarn"),
            (r"pnpm\s+add\s+(.+)", "pnpm"),
            (r"cargo\s+install\s+(.+)", "cargo"),
            (r"gem\s+install\s+(.+)", "gem"),
            (r"go\s+get\s+(.+)", "go"),
            (r"go\s+install\s+(.+)", "go"),
            (r"apt\s+install\s+(.+)", "apt"),
            (r"apt-get\s+install\s+(.+)", "apt-get"),
            (r"choco\s+install\s+(.+)", "choco"),
            (r"scoop\s+install\s+(.+)", "scoop"),
            (r"winget\s+install\s+(.+)", "winget"),
        ]
        
        for pattern, manager in install_patterns:
            match = re.search(pattern, cmd_lower)
            if match:
                packages_part = match.group(1).strip()
                packages = []
                
                for pkg in re.split(r'\s+', packages_part):
                    pkg = pkg.strip()
                    if not pkg or pkg.startswith('-'):
                        continue
                    if pkg.startswith('"') or pkg.startswith("'"):
                        pkg = pkg.strip('"\'')
                    if pkg:
                        packages.append(pkg)
                
                if packages:
                    return True, packages
                return True, []
        
        return False, []

    def _check_repeated_write_success(self, command: str, result: str) -> Optional[str]:
        """检查是否为重复的写入操作（特例优化：包含文件验证）"""
        print(f"[DEBUG-write] _check_repeated_write_success 被调用")
        print(f"[DEBUG-write]   注意：这是写入操作的专用检测，与通用重复检测(_check_repeated_tool_call)协同工作")
        print(f"[DEBUG-write]   command: {command[:80]}...")

        if "exit_code: 0" not in result:
            return None

        stdout_match = result.split("--- stdout ---")
        if len(stdout_match) < 2:
            return None
        stdout = stdout_match[1].split("--- stderr ---")[0].strip()

        if stdout:
            return None

        if not self._is_write_operation(command):
            return None

        self._recent_commands.append(command)
        if len(self._recent_commands) > 10:
            self._recent_commands.pop(0)

        write_count = sum(1 for cmd in self._recent_commands if self._is_write_operation(cmd))
        if write_count >= 2:
            seen = set()
            for cmd in self._recent_commands:
                if cmd in seen:
                    msg = "检测到重复的文件写入操作且已成功完成，任务自动结束。"
                    print(f"[DEBUG-write] ✅ 触发写入重复检测: {msg}")
                    return msg
                seen.add(cmd)

        return None

    def _check_repeated_tool_call(self, tool_name: str, args: dict) -> tuple[bool, Optional[str], Optional[str]]:
        """
        检查是否为重复的工具调用

        返回: (is_repeated, cached_result_or_warning, last_result)
        - is_repeated: 是否检测到重复
        - cached_result_or_warning: 如果重复，返回警告信息+上次结果；否则返回None
        - last_result: 上次执行的结果（用于自动终止时使用）
        """
        import hashlib
        import json

        max_repeats = config.MAX_CONSECUTIVE_REPEATS
        print(f"[DEBUG-repeat] 配置信息: 去重启用={config.TOOL_CALL_DEDUPLICATION_ENABLED}, 最大重复次数={max_repeats}, 历史窗口大小={config.REPEAT_DETECTION_WINDOW_SIZE}")

        args_hash = hashlib.md5(json.dumps({"name": tool_name, **args}, sort_keys=True).encode()).hexdigest()

        print(f"[DEBUG-repeat] 检查工具调用重复: {tool_name}, args_hash={args_hash[:8]}...")
        print(f"[DEBUG-repeat] 历史记录数: {len(self._recent_tool_calls)}")

        for record in self._recent_tool_calls:
            if record["name"] == tool_name and record["args_hash"] == args_hash:
                self._consecutive_repeat_count += 1
                last_result = record.get("result", "")

                warning_msg = (
                    f"⚠️ 检测到重复的工具调用 [{tool_name}]。"
                    f"该工具已在之前成功执行并返回结果，请直接使用已有结果完成任务，或调用 finish 工具结束对话。\n\n"
                    f"上次执行结果：\n{last_result}"
                )

                print(f"[DEBUG-repeat] ✓ 发现重复调用: {tool_name}")
                print(f"[DEBUG-repeat]   连续重复次数: {self._consecutive_repeat_count}")
                print(f"[DEBUG-repeat]   上次结果长度: {len(last_result)}")

                return (True, warning_msg, last_result)

        self._consecutive_repeat_count = 0
        print(f"[DEBUG-repeat] ✗ 未发现重复调用: {tool_name}")
        return (False, None, None)

    def _record_tool_call(self, tool_name: str, args: dict, result: str) -> None:
        """记录一次工具调用到历史中"""
        import hashlib
        import json
        import time

        args_hash = hashlib.md5(json.dumps({"name": tool_name, **args}, sort_keys=True).encode()).hexdigest()

        self._recent_tool_calls.append({
            "name": tool_name,
            "args_hash": args_hash,
            "result": result[:500],
            "timestamp": time.time()
        })

        window_size = config.REPEAT_DETECTION_WINDOW_SIZE
        if len(self._recent_tool_calls) > window_size:
            self._recent_tool_calls.pop(0)

        print(f"[DEBUG-repeat] 记录工具调用: {tool_name}, args_hash={args_hash[:8]}, result长度={min(len(result), 500)}, 当前历史数={len(self._recent_tool_calls)}")

    @staticmethod
    def _format_tool_result(success: bool, content: str, error_msg: str = "", suggestion: str = "") -> str:
        """
        标准化工具返回结果格式

        Args:
            success: 是否成功
            content: 主要内容（如文件内容、命令输出等）
            error_msg: 错误信息（仅失败时使用）
            suggestion: 建议的修复方案或下一步操作（可选）

        Returns:
            格式化的结果字符串
        """
        if success:
            if len(content) > 2000:
                content = content[:2000] + "\n\n…（内容已截断）"
            return f"""✅ 操作成功

{content}

---
💡 如果任务已完成，请调用 finish 工具结束对话。"""
        else:
            result = f"""❌ 操作失败

错误原因：{error_msg}"""

            if suggestion:
                result += f"\n\n建议方案：{suggestion}"

            result += "\n\n---\n💡 请修正后重试，或调用 finish 结束当前任务。"
            return result

    def _extract_file_path(self, command: str) -> Optional[str]:
        import re
        patterns = [
            r"[-/]Path\s+['\"]([^'\"]+)['\"]",
            r">>\s*['\"]([^'\"]+)['\"]",
            r">\s*['\"]([^'\"]+)['\"]",
            r">>\s*(\S+)",
            r">\s*(\S+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _verify_file_exists(self, file_path: str, cwd: str) -> str:
        from pathlib import Path
        
        if cwd == ".":
            full_path = Path(self.work_dir) / file_path
        else:
            full_path = Path(self.work_dir) / cwd / file_path
        
        full_path = full_path.resolve()
        
        if full_path.exists():
            if full_path.is_file():
                size = full_path.stat().st_size
                return f"✓ 文件已创建成功：{full_path}（大小：{size} 字节）"
            else:
                return f"✓ 路径存在，但不是文件：{full_path}"
        else:
            return f"✗ 文件不存在：{full_path}"

    def _dispatch(
        self,
        name: str,
        args: dict,
        active_skill_text: list[str],
        active_skill_ids: list[str],
    ) -> tuple[str, bool, Optional[str]]:
        if name in ("select_skill", "finish", "ask_user", "load_skill_memory"):
            return execute_skill_control_tool(
                name,
                args,
                registry=self.registry,
                active_skill_text=active_skill_text,
                active_skill_ids=active_skill_ids,
                disabled_skill_ids=self._disabled_skill_ids_frozen(),
            )
        return (execute_atomic_tool(name, args, self._tool_ctx,self.registry), False, None)

    def _append_model_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        system_prompt: str,
        user_query: str,
    ) -> None:
        assert self.memory is not None
        cid = self._conversation_id
        prior = _history_without_system(self.memory.get_messages(cid))
        messages.clear()
        messages.append({"role": "system", "content": system_prompt})
        messages.extend(prior)
        self.memory.append_message(cid, "user", user_query.strip())
        messages.append({"role": "user", "content": user_query.strip()})

    def _persist_after_tool_turn(
        self,
        fname: str,
        args:dict,
        result: str,
        active_skill_text: list[str],
        active_skill_ids: list[str],
        messages: list[dict[str, Any]],
        log_callback: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        assert self.memory is not None
        cid = self._conversation_id
        args_str=json.dumps(args, ensure_ascii=False, indent=2)
        if fname == "select_skill":
            meta_type = "skill"
        elif fname == "ask_user":
            meta_type = "ask_user"
        else:
            meta_type = "base_tool"
        self.memory.append_message(
            cid,
            "tool",
            str(result),
            metadata={"type": meta_type, "name": fname, "args": args_str},
        )
        messages.append({"role": "tool", "name": fname, "content": str(result)})
        if fname == "select_skill" and active_skill_text and not str(result).startswith("错误"):
            self.memory.set_active_skills(cid, list(active_skill_ids))
            active_skills_text = self._build_active_skills_text(active_skill_text, active_skill_ids)
            self._dynamic_prompt.update_active_skills(active_skills_text)
            for i, msg in enumerate(messages):
                if msg.get("role") == "system":
                    messages[i] = {"role": "system", "content": self._dynamic_prompt.build()}
                    print(f"[DEBUG-exec] 更新系统提示词_dynamic_prompt：{self._dynamic_prompt.build()}")
                    break

    def _summarize_session_skills(self, conversation_id: str, active_skill_ids: list[str] | None = None) -> None:
        import threading
        current_thread = threading.current_thread()
        print(f"[SkillSummary] _summarize_session_skills 开始: thread={current_thread.name}, conversation_id={conversation_id}")
        
        if not self.memory:
            print(f"[SkillSummary] 跳过总结: memory 为空 (conversation_id={conversation_id})")
            return

        if active_skill_ids is None:
            print(f"[SkillSummary] 获取活跃 skill_ids (conversation_id={conversation_id})")
            active_skill_ids = self.memory.get_active_skills(conversation_id)

        print(f"[SkillSummary] 开始总结: conversation_id={conversation_id}, active_skill_ids={active_skill_ids}")

        if not active_skill_ids:
            print(f"[SkillSummary] 跳过总结: 无活跃 skill (conversation_id={conversation_id})")
            return

        messages = self.memory.get_message_records(conversation_id)
        if not messages:
            print(f"[SkillSummary] 跳过总结: 无会话消息 (conversation_id={conversation_id})")
            return

        print(f"[SkillSummary] 加载会话消息完成: count={len(messages)}, conversation_id={conversation_id}")
        
        model = get_chat_model()
        print(f"[SkillSummary] 获取 LLM 模型完成, conversation_id={conversation_id}")

        success_count = 0
        for idx, skill_id in enumerate(active_skill_ids):
            try:
                print(f"[SkillSummary] 正在总结 skill: {skill_id} ({idx+1}/{len(active_skill_ids)})")
                memory = summarize_skill_execution(skill_id, messages, model)
                if memory:
                    saved_path = save_skill_memory(skill_id, memory, self.registry)
                    print(f"[SkillSummary] skill {skill_id} 总结完成, 保存至: {saved_path}")
                    success_count += 1
                else:
                    print(f"[SkillSummary] skill {skill_id} 总结结果为空, 未保存")
            except Exception as e:
                import traceback
                print(f"[SkillSummary] ❌ 总结 skill {skill_id} 执行经验失败: {e}")
                print(f"[SkillSummary] 📋 异常堆栈:\n{traceback.format_exc()}")
        
        print(f"[SkillSummary] 总结会话完成: conversation_id={conversation_id}, "
              f"total={len(active_skill_ids)}, success={success_count}")
        print(f"[SkillSummary] 后台线程退出: thread={current_thread.name}")

    def _start_summary_in_background(self, conversation_id: str, active_skill_ids: list[str] | None = None) -> None:
        import threading
        print(f"[SkillSummary] 准备启动后台总结线程: conversation_id={conversation_id}, active_skill_ids={active_skill_ids}")
        
        if not self.memory:
            print(f"[SkillSummary] 跳过总结: memory 为空 (conversation_id={conversation_id})")
            return
        
        if active_skill_ids is None:
            print(f"[SkillSummary] 获取活跃 skill_ids (conversation_id={conversation_id})")
            active_skill_ids = self.memory.get_active_skills(conversation_id)
        
        if not active_skill_ids:
            print(f"[SkillSummary] 跳过总结: 无活跃 skill (conversation_id={conversation_id})")
            return
        
        print(f"[SkillSummary] 构建总结线程: conversation_id={conversation_id}, active_skill_ids={active_skill_ids}")
        
        t = threading.Thread(
            target=self._summarize_session_skills,
            args=(conversation_id, active_skill_ids),
            name=f"skill-summary-{conversation_id[:8]}",
            daemon=True,
        )
        t.start()
        
        print(f"[SkillSummary] 后台线程已启动: name={t.name}, ident={t.ident}, active_skill_ids={active_skill_ids}")
        print(f"[SkillSummary] 主线程继续执行 (总结线程独立运行)")

    def run(self, user_query: str, log_callback: Optional[Callable[[str, str], Any]] = None, stop_check_callback: Optional[Callable[[], bool]] = None) -> str:
        import traceback
        print(f"[DEBUG-exec] ===== run() 开始执行 =====")
        print(f"[DEBUG-exec] user_query 长度: {len(user_query)}, 前50字: {user_query[:50]}")
        print(f"[DEBUG-exec] conversation_id: {self._conversation_id}")
        
        self._stop_event.clear()
        self._recent_commands = []
        self._recent_tool_calls = []
        self._consecutive_repeat_count = 0
        self._token_usage = TokenUsage.empty()

        def _check_stop() -> bool:
            if self._stop_event.is_set():
                return True
            if stop_check_callback is not None and stop_check_callback():
                return True
            return False

        def _emit_token_usage():
            if log_callback and getattr(config, "TOKEN_USAGE_ENABLED", False):
                from dataclasses import asdict
                token_usage_json = json.dumps(asdict(self._token_usage), ensure_ascii=False)
                log_callback(token_usage_json, "token_usage")

        try:
            # 保存当前用户查询，用于后续更新系统提示词时的语义检索
            self._last_user_query = user_query
            
            model = get_chat_model()
            disabled = self._disabled_skill_ids_frozen()
            skills_visible = [s for s in self.registry.list_skills() if s.skill_id not in disabled]
            catalog = build_skills_catalog_text(skills_visible)
            
            tool_catalog = model.build_tool_catalog()
            tool_catalog_text = self._build_tool_catalog_text(tool_catalog)
            system_prompt = self._build_dynamic_system_prompt(catalog, user_query=user_query, tool_catalog=tool_catalog_text)
            print(f"[DEBUG-exec] 初始系统提示词：{system_prompt}")
            
            tools = model.build_skill_agent_tools_initial()
            self._supplied_tool_definitions: dict[str, dict] = {}
            
            print(f"[DEBUG-tool-catalog] ===== 目录+补发 渐进披露机制初始化 =====")
            print(f"[DEBUG-tool-catalog] 工具目录已构建，包含 {len(tool_catalog)} 个工具的简要描述")
            print(f"[DEBUG-tool-catalog] 初始工具集已准备，包含 request_tool_details + CONTROL 工具")
            print(f"[DEBUG-tool-catalog] 原子工具将按需通过 request_tool_details 获取")
            
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query.strip()},
            ]
            active_skill_text: list[str] = []
            active_skill_ids: list[str] = []

            # 从数据库恢复已保存的 active skills
            if self.memory is not None:
                saved_skill_ids = self.memory.get_active_skills(self._conversation_id)
                if saved_skill_ids:
                    for sid in saved_skill_ids:
                        skill = self.registry.get(sid)
                        if skill:
                            formatted_skill = format_skill_for_prompt(skill)
                            active_skill_text.append(formatted_skill)
                            active_skill_ids.append(sid)
                    # 更新动态提示词
                    if active_skill_text and active_skill_ids:
                        active_skills_section = self._build_active_skills_text(active_skill_text, active_skill_ids)
                        self._dynamic_prompt.update_active_skills(active_skills_section)
                        print(f"[DEBUG-exec] 恢复 active skills: {active_skill_ids}")

            if self.memory is not None:
                self._append_model_messages(messages, system_prompt=system_prompt, user_query=user_query)
                prior_messages = self.memory.get_message_records(self._conversation_id)
                print(f"[DEBUG-exec] 加载历史消息: {len(prior_messages)} 条")
                if prior_messages and len(prior_messages) >= 2:
                    last_msg = prior_messages[-1]
                    prev_msg = prior_messages[-2]
                    if last_msg.get("role") == "user" and prev_msg.get("role") == "tool":
                        prev_meta = prev_msg.get("metadata") or {}
                        if prev_meta.get("name") == "ask_user":
                            user_choice = user_query.strip()
                            print(f"[DEBUG-exec] 检测到 ask_user 历史，用户选择: {user_choice}")
                            if user_choice == "确认执行":
                                for record in reversed(prior_messages[:-2]):
                                    if record.get("role") == "assistant":
                                        meta = record.get("metadata") or {}
                                        if meta.get("type") == "tool_call":
                                            fname = meta.get("name")
                                            args_str = meta.get("args", "{}")
                                            try:
                                                args = json.loads(args_str)
                                            except json.JSONDecodeError:
                                                args = {}
                                            if fname == "run_command":
                                                command = str(args.get("command", "") or "").strip()
                                                result = execute_atomic_tool(fname, args, self._tool_ctx, self.registry)
                                                self.memory.append_message(self._conversation_id, "tool", str(result), metadata={"name": fname})
                                                messages.append({"role": "tool", "name": fname, "content": str(result)})
                                                if log_callback:
                                                    log_callback(f"执行命令: {command}", "base_tool")
                                                    log_callback(str(result), "base_tool")
                                                break
                            elif user_choice == "确认安装":
                                for record in reversed(prior_messages[:-2]):
                                    if record.get("role") == "assistant":
                                        meta = record.get("metadata") or {}
                                        if meta.get("type") == "tool_call":
                                            fname = meta.get("name")
                                            args_str = meta.get("args", "{}")
                                            try:
                                                args = json.loads(args_str)
                                            except json.JSONDecodeError:
                                                args = {}
                                            if fname == "run_command":
                                                skill_id = args.get("skill_id", "")
                                                command = str(args.get("command", "") or "").strip()
                                                
                                                if skill_id:
                                                    success, msg = install_skill_dependencies(str(skill_id), self.registry)
                                                    if not success:
                                                        err_msg = f"依赖安装失败: {msg}"
                                                        if log_callback:
                                                            log_callback(err_msg, "assistant")
                                                        metadata = {"token_usage": asdict(self._token_usage)}
                                                        self.memory.append_message(self._conversation_id, "assistant", err_msg, metadata=metadata)
                                                        _emit_token_usage()
                                                        print(f"[DEBUG-exec] 📤 返回 (依赖安装失败): {err_msg}")
                                                        return err_msg
                                                    if log_callback:
                                                        log_callback(f"依赖安装成功: {msg}", "base_tool")
                                                    self.memory.append_message(self._conversation_id, "tool", f"依赖安装成功: {msg}", metadata={"name": "install_dependencies"})
                                                    messages.append({"role": "tool", "name": "install_dependencies", "content": f"依赖安装成功: {msg}"})
                                                    
                                                    result = execute_atomic_tool(fname, args, self._tool_ctx, self.registry)
                                                    self.memory.append_message(self._conversation_id, "tool", str(result), metadata={"name": fname})
                                                    messages.append({"role": "tool", "name": fname, "content": str(result)})
                                                    if log_callback:
                                                        log_callback(f"执行命令: {command}", "base_tool")
                                                        log_callback(str(result), "base_tool")
                                                else:
                                                    result = execute_atomic_tool(fname, args, self._tool_ctx, self.registry)
                                                    self.memory.append_message(self._conversation_id, "tool", str(result), metadata={"name": fname})
                                                    messages.append({"role": "tool", "name": fname, "content": str(result)})
                                                    if log_callback:
                                                        log_callback(f"执行命令: {command}", "base_tool")
                                                        log_callback(str(result), "base_tool")
                                                _emit_token_usage()
                                                print(f"[DEBUG-exec] 📤 返回 (确认安装后执行结果): {str(result)[:100]}")
                                                return result
                            elif user_choice == "取消":
                                cancel_msg = "操作已取消"
                                if log_callback:
                                    log_callback(cancel_msg, "assistant")
                                if self.memory is not None:
                                    metadata = {"token_usage": asdict(self._token_usage)}
                                    self.memory.append_message(self._conversation_id, "assistant", cancel_msg, metadata=metadata)
                                _emit_token_usage()
                                print(f"[DEBUG-exec] 📤 返回 (操作已取消)")
                                return cancel_msg

            if self._should_compact(messages):
                if log_callback:
                    log_callback("检测到上下文过长，正在自动压缩...", "info")
                messages = self._perform_compaction(messages, log_callback)

            for step in range(self.max_steps):
                print(f"[DEBUG-exec] ===== Step {step}/{self.max_steps} 开始 =====")
                print(f"[DEBUG-exec] messages 数量: {len(messages)}")
                
                if _check_stop():
                    stop_msg = "用户已停止推理"
                    if log_callback:
                        log_callback(stop_msg, "assistant")
                    if self.memory is not None:
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(self._conversation_id, "assistant", stop_msg, metadata=metadata)
                    self._start_summary_in_background(self._conversation_id, active_skill_ids)
                    _emit_token_usage()
                    print(f"[DEBUG-exec] 📤 用户停止推理，退出循环")
                    return stop_msg
                
                thinking_parts: list[str] = []
                content_parts: list[str] = []
                
                # 获取当前的 enable_thinking 设置
                from llm.llm_config_manager import get_current_config
                current_config = get_current_config()
                show_thinking = current_config.enable_thinking

                def _stream_callback(content: str, msg_type: str) -> None:
                    if log_callback:
                        # 只有当启用思考模式时才发送 think 类型的消息
                        if msg_type == "think" and not show_thinking:
                            pass  # 不发送思考消息
                        else:
                            log_callback(content, msg_type)
                    if msg_type == "think":
                        thinking_parts.append(content)
                    elif msg_type == "content":
                        content_parts.append(content)

                print(f"[DEBUG-exec] 准备调用 LLM, 当前消息数: {len(messages)}")
                if len(messages) > 0:
                    last_msg = messages[-1]
                    print(f"[DEBUG-exec] 最后一条消息: role={last_msg.get('role')}, content 前50字={str(last_msg.get('content', ''))[:50]}")

                self._update_system_message(messages)


                function_call = model.stream_request_llm_with_tools(messages, tools, _stream_callback)

                print(f"[DEBUG-exec] LLM 返回:")
                if function_call is None:
                    print(f"[DEBUG-exec]   - function_call is None")
                else:
                    print(f"[DEBUG-exec]   - name: {function_call.get('name')}")
                    print(f"[DEBUG-exec]   - has content: {function_call.get('content') is not None}")
                    if function_call.get('arguments'):
                        args_preview = str(function_call.get('arguments', ''))[:100]
                        print(f"[DEBUG-exec]   - arguments 前100字: {args_preview}")

                if function_call is not None and function_call.get("token_usage") is not None:
                    self._token_usage = self._token_usage + function_call["token_usage"]

                full_thinking = "".join(thinking_parts).strip()

                is_text_only = (
                    function_call is not None and
                    function_call.get("name") is None and
                    function_call.get("content") is not None
                )

                if is_text_only or (function_call is None):
                    final_text = ""
                    if is_text_only:
                        final_text = function_call.get("content", "")
                    if not final_text:
                        final_text = "".join(content_parts).strip()
                    if not full_thinking:
                        full_thinking = "".join(thinking_parts).strip()

                    if full_thinking and self.memory is not None:
                        self.memory.append_message(
                            self._conversation_id,
                            "assistant",
                            full_thinking,
                            metadata={"type": "think"},
                        )

                    if not final_text:
                        err = "模型未返回内容，无法继续。"
                        if log_callback:
                            log_callback(err, "assistant")
                        if self.memory is not None:
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", err, metadata=metadata)
                        self._start_summary_in_background(self._conversation_id, active_skill_ids)
                        _emit_token_usage()
                        return err

                    if self.memory is not None:
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(self._conversation_id, "assistant", final_text, metadata=metadata)
                    self._start_summary_in_background(self._conversation_id, active_skill_ids)
                    _emit_token_usage()
                    print(f"[DEBUG-exec] 📤 返回文本内容 (长度: {len(final_text)})")
                    return final_text

                fname = function_call.get("name")
                arg_str = function_call.get("arguments", "{}")
                try:
                    args = json.loads(arg_str)
                except json.JSONDecodeError:
                    args = {}
                print(f"[DEBUG-exec] 解析工具调用: fname={fname}, args keys={list(args.keys()) if isinstance(args, dict) else type(args)}")

                if full_thinking and self.memory is not None:
                    self.memory.append_message(
                        self._conversation_id,
                        "assistant",
                        full_thinking,
                        metadata={"type": "think"},
                    )

                if fname == "request_tool_details":
                    tool_names = args.get("tool_names", [])
                    if not isinstance(tool_names, list):
                        tool_names = [str(tool_names)]
                    
                    print(f"[DEBUG-exec] request_tool_details: 请求工具定义 {tool_names}")
                    print(f"[DEBUG-tool-catalog] ===== 目录+补发 渐进披露机制 - 补发阶段 =====")
                    print(f"[DEBUG-tool-catalog] LLM 请求获取工具的完整定义: {tool_names}")
                    
                    definitions_found = []
                    definitions_missing = []
                    
                    for tool_name in tool_names:
                        tool_def = model.get_tool_full_definition(tool_name)
                        if tool_def:
                            definitions_found.append(tool_def)
                            self._supplied_tool_definitions[tool_name] = tool_def
                            print(f"[DEBUG-exec]   ✓ 找到工具定义: {tool_name}")
                            print(f"[DEBUG-tool-catalog]   工具定义已缓存到 _supplied_tool_definitions")
                        else:
                            definitions_missing.append(tool_name)
                            print(f"[DEBUG-exec]   ✗ 未找到工具定义: {tool_name}")
                    
                    result_parts = []
                    if definitions_found:
                        result_parts.append("以下工具的完整定义已获取：\n")
                        for def_item in definitions_found:
                            def_json = json.dumps(def_item, ensure_ascii=False, indent=2)
                            result_parts.append(f"### {def_item.get('name', 'unknown')}\n```json\n{def_json}\n```\n")
                    
                    if definitions_missing:
                        result_parts.append(f"\n⚠️ 以下工具未找到定义：{', '.join(definitions_missing)}")
                    
                    result = "\n".join(result_parts)
                    
                    for tool_name, tool_def in self._supplied_tool_definitions.items():
                        tool_schema = model.format_tool_for_request(tool_def)
                        already_in_tools = any(
                            model.get_tool_name_from_formatted(t) == tool_name
                            for t in tools
                        )
                        if not already_in_tools:
                            tools.append(tool_schema)
                            print(f"[DEBUG-exec] 添加工具到 tools 列表: {tool_name}")
                            print(f"[DEBUG-tool-catalog]   工具 [{tool_name}] 已动态添加到可用工具集")
                            print(f"[DEBUG-tool-catalog]   当前 tools 列表大小: {len(tools)}")
                    
                    if self.memory is not None:
                        self.memory.append_message(
                            self._conversation_id,
                            "tool",
                            str(result),
                            metadata={"type": "tool_definition", "name": fname, "args": arg_str},
                        )
                    messages.append({"role": "tool", "name": fname, "content": str(result)})
                    
                    if log_callback:
                        found_names = [d.get("name", "") for d in definitions_found]
                        log_callback(f"获取工具定义: {', '.join(found_names)}", "tool")
                        log_callback(str(result), "base_tool")
                    
                    continue

                if log_callback:
                    try:
                        args_s = json.dumps(args, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_s = str(args)
                    pass
                    if fname == "finish":
                        content_preview = "".join(content_parts)[:200] if content_parts else "(空)"
                        log_callback(f"[DEBUG-finish] LLM 调用 finish，原始 args: {args_s} | content_parts 预览: {content_preview!r}", "tool")
                    elif fname != "select_skill":
                        log_callback(f"调用工具 `{fname}` · {args_s}", "tool")
                    else:
                        log_callback(f"选择 Skill: {args.get('skill_id', '')}", "tool")
                if self.memory is not None:
                    try:
                        args_display = json.dumps(args, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_display = arg_str
                    self.memory.append_message(
                        self._conversation_id,
                        "assistant",
                        f"调用工具 `{fname}` · {args_display}",
                        metadata={
                            "type": "tool_call",
                            "name": fname,
                            "args": arg_str,
                            "reasoning_content": full_thinking
                        }
                    )
            
                if fname == "run_command":
                    command = str(args.get("command", "") or "").strip()
                    skill_id = args.get("skill_id", "")
                    
                    if skill_id:
                        need_install, packages_to_install, err_msg = check_skill_dependencies(
                            str(skill_id), self.registry
                        )
                        if err_msg:
                            _emit_token_usage()
                            return f"错误: {err_msg}"
                        
                        if need_install and packages_to_install:
                            packages_str = ", ".join(packages_to_install)
                            ask_args = {
                                "question": f"Skill「{skill_id}」需要安装以下依赖包：\n\n{packages_str}\n\n是否确认安装？",
                                "choices": ["确认安装", "取消"]
                            }
                            result, terminate, final = execute_skill_control_tool(
                                "ask_user",
                                ask_args,
                                registry=self.registry,
                                active_skill_text=active_skill_text,
                                active_skill_ids=active_skill_ids,
                                disabled_skill_ids=self._disabled_skill_ids_frozen(),
                            )
                            if str(result).startswith("错误"):
                                _emit_token_usage()
                                return result
                            if self.memory is not None:
                                self._persist_after_tool_turn(
                                    "ask_user",
                                    ask_args,
                                    str(result),
                                    active_skill_text,
                                    active_skill_ids,
                                    messages,
                                )
                            else:
                                messages.append({"role": "tool", "name": "ask_user", "content": str(result)})
                            if log_callback:
                                log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
                            _emit_token_usage()
                            return SKILL_AGENT_AWAITING_USER_REPLY
                    
                    is_pkg_install, packages = self._is_package_install_command(command)
                    if is_pkg_install:
                        packages_str = ", ".join(packages) if packages else "（未解析到包名）"
                        ask_args = {
                            "question": f"即将安装以下包：\n\n{packages_str}\n\n命令：{command}\n\n是否确认执行？",
                            "choices": ["确认安装", "取消"]
                        }
                        result, terminate, final = execute_skill_control_tool(
                            "ask_user",
                            ask_args,
                            registry=self.registry,
                            active_skill_text=active_skill_text,
                            active_skill_ids=active_skill_ids,
                            disabled_skill_ids=self._disabled_skill_ids_frozen(),
                        )
                        if str(result).startswith("错误"):
                            _emit_token_usage()
                            return result
                        if self.memory is not None:
                            self._persist_after_tool_turn(
                                "ask_user",
                                ask_args,
                                str(result),
                                active_skill_text,
                                active_skill_ids,
                                messages,
                            )
                        else:
                            messages.append({"role": "tool", "name": "ask_user", "content": str(result)})
                        if log_callback:
                            log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
                        _emit_token_usage()
                        return SKILL_AGENT_AWAITING_USER_REPLY
                    
                    if self._is_dangerous_command(command):
                        ask_args = {
                            "question": f"即将执行以下命令，可能会修改或删除文件：\n\n{command}\n\n是否确认执行？",
                            "choices": ["确认执行", "取消"]
                        }
                        result, terminate, final = execute_skill_control_tool(
                            "ask_user",
                            ask_args,
                            registry=self.registry,
                            active_skill_text=active_skill_text,
                            active_skill_ids=active_skill_ids,
                            disabled_skill_ids=self._disabled_skill_ids_frozen(),
                        )
                        if str(result).startswith("错误"):
                            _emit_token_usage()
                            return result
                        if self.memory is not None:
                            self._persist_after_tool_turn(
                                "ask_user",
                                ask_args,
                                str(result),
                                active_skill_text,
                                active_skill_ids,
                                messages,
                            )
                        else:
                            messages.append({"role": "tool", "name": "ask_user", "content": str(result)})
                        if log_callback:
                            log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
                        _emit_token_usage()
                        return SKILL_AGENT_AWAITING_USER_REPLY
                
                print(f"[DEBUG-exec] 准备执行工具: {fname}")
                if fname == "run_command":
                    cmd = str(args.get("command", ""))[:80]
                    print(f"[DEBUG-exec]   命令: {cmd}...")

                # 检测重复工具调用（可通过配置禁用）
                _control_tools = ("select_skill", "finish", "ask_user", "load_skill_memory")
                is_repeated = False
                repeat_warning = None
                last_result = None

                if config.TOOL_CALL_DEDUPLICATION_ENABLED and fname not in _control_tools:
                    is_repeated, repeat_warning, last_result = self._check_repeated_tool_call(fname, args)
                    if is_repeated:
                        print(f"[DEBUG-repeat] ⚠️ 检测到重复工具调用: {fname}")
                        print(f"[DEBUG-repeat]   连续重复次数: {self._consecutive_repeat_count}")

                        result = repeat_warning or f"检测到重复的 {fname} 调用"
                        terminate = False
                        final = None

                        max_repeats = config.MAX_CONSECUTIVE_REPEATS
                        if self._consecutive_repeat_count >= max_repeats:
                            auto_finish_msg = (
                                f"检测到连续 {self._consecutive_repeat_count} 次重复执行工具 [{fname}]，已自动结束任务。\n\n"
                                f"最后一次执行结果摘要：\n{(last_result or '')[:200]}"
                            )
                            print(f"[DEBUG-repeat] 🚨 触发自动终止: {auto_finish_msg}")

                            if log_callback:
                                log_callback(auto_finish_msg, "assistant")
                            if self.memory is not None:
                                metadata = {"token_usage": asdict(self._token_usage)}
                                self.memory.append_message(self._conversation_id, "assistant", auto_finish_msg, metadata=metadata)
                            self._start_summary_in_background(self._conversation_id, active_skill_ids)
                            _emit_token_usage()
                            return auto_finish_msg
                else:
                    is_repeated = False

                # 工具执行流程：
                # 1. 通用重复检测（适用于所有工具）→ 已在前面实现
                # 2. 执行工具 → self._dispatch()
                # 3. 结果格式化 → 已实现
                # 4. 写入操作特例检测（仅限 run_command + 写入操作）→ 原有逻辑

                if not is_repeated:
                    result, terminate, final = self._dispatch(fname, args, active_skill_text, active_skill_ids)

                    if fname not in _control_tools:
                        self._record_tool_call(fname, args, str(result))

                # 标准化工具返回结果格式（排除控制类工具和已经是标准格式的结果）
                if fname not in ("select_skill", "finish", "ask_user", "load_skill_memory"):
                    result_str = str(result)
                    if not result_str.startswith(("✅", "❌", "⚠️")):
                        # 判断是否为成功结果（简单启发式规则）
                        is_success = (
                            "exit_code: 0" in result_str or  # 命令执行成功
                            (len(result_str) > 10 and "error" not in result_str.lower()[:100])  # 有实质内容且无明显错误
                        )
                        original_len = len(result_str)
                        if is_success and len(result_str.strip()) > 0:
                            result = self._format_tool_result(True, result_str)
                            print(f"[DEBUG-format] 格式化工具结果: {fname}, 成功=True, 原始长度={original_len}, 格式化后长度={len(str(result))}")
                        elif not is_success:
                            # 保持原始错误信息，但添加前缀
                            if not result_str.startswith("错误"):
                                result = f"❌ 操作失败\n\n{result}"
                                print(f"[DEBUG-format] 格式化工具结果: {fname}, 成功=False, 原始长度={original_len}, 添加失败前缀")

                print(f"[DEBUG-exec] 工具执行完成:")
                print(f"[DEBUG-exec]   - result 长度: {len(str(result))}")
                print(f"[DEBUG-exec]   - result 前100字: {str(result)[:100]}")
                print(f"[DEBUG-exec]   - terminate: {terminate}")
                print(f"[DEBUG-exec]   - final: {final is not None}")

                if log_callback and fname == "select_skill":
                    if str(result).startswith("错误"):
                        log_callback(f"选择 Skill 失败：{result}", "tool")
                    else:
                        ids_join = "、".join(active_skill_ids)
                        n = len(active_skill_ids)
                        log_callback(
                            f"命中 Skill「{args.get('skill_id', '')}」｜本轮已累计 id：{ids_join}（共 {n} 个）",
                            "tool",
                        )
                        prefix = (
                            f"［第 {n} 次加载｜本轮已累计 {n} 份｜id 顺序：{ids_join}］\n\n"
                        )
                        log_callback(prefix + str(result), "doc")

                if log_callback and fname not in ("finish", "select_skill", "ask_user"):
                    r = str(result)
                    if len(r) > 12000:
                        r = r[:12000] + "\n\n…（内容已截断）"
                    if fname == "run_command":
                        command = str(args.get("command", "") or "").strip()
                        log_callback(f"执行命令: {command}", "base_tool")
                        
                        if "exit_code: 0" in r:
                            stdout_match = r.split("--- stdout ---")
                            stdout = ""
                            if len(stdout_match) >= 2:
                                stdout = stdout_match[1].split("--- stderr ---")[0].strip()
                            
                            if not stdout and self._is_write_operation(command):
                                print(f"[DEBUG-write] 检测到写入操作: {command[:80]}...")
                                file_path = self._extract_file_path(command)
                                if file_path:
                                    print(f"[DEBUG-write] 提取到文件路径: {file_path}")
                                    check_result = self._verify_file_exists(file_path, args.get("cwd", "."))
                                    if log_callback:
                                        log_callback(f"检查结果: {check_result}", "base_tool")
                                    r = r + "\n\n" + check_result
                                    result = r
                                    print(f"[DEBUG-write] 验证结果已合并到工具结果")
                                else:
                                    print(f"[DEBUG-write] 无法提取文件路径，跳过验证")
                        
                        # 写入操作特例检测（保留原有逻辑）
                        # 此检测与通用重复检测协同工作，专门针对写入操作提供更严格的保护
                        auto_end_msg = self._check_repeated_write_success(command, str(result))
                        if auto_end_msg:
                            print(f"[DEBUG-write] 检测到重复写入，自动结束: {auto_end_msg}")
                            log_callback(auto_end_msg, "assistant")
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", auto_end_msg, metadata=metadata)
                            self._start_summary_in_background(self._conversation_id, active_skill_ids)
                            _emit_token_usage()
                            return auto_end_msg
                    log_callback(r, "base_tool")

                if terminate and final is not None:
                    if self.memory is not None:
                        cid = self._conversation_id
                        self.memory.append_message(cid, "tool", str(result), metadata={"name": fname})
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(cid, "assistant", str(final), metadata=metadata)
                    self._start_summary_in_background(self._conversation_id, active_skill_ids)
                    if log_callback:
                        log_callback(str(final), "assistant")
                    _emit_token_usage()
                    print(f"[DEBUG-exec] 📤 工具要求终止 (terminate=True), 返回 final (长度: {len(str(final))})")
                    return final

                if fname == "ask_user" and not str(result).startswith("错误"):
                    if self.memory is not None:
                        self._persist_after_tool_turn(
                            fname,
                            args,
                            str(result),
                            active_skill_text,
                            active_skill_ids,
                            messages,
                            log_callback,
                        )
                    else:
                        messages.append({"role": "tool", "name": fname, "content": str(result)})
                    if log_callback:
                        log_callback(_ask_user_ui_log_payload(args), "await_user")
                    _emit_token_usage()
                    print(f"[DEBUG-exec] 📤 等待用户回复 (ask_user)")
                    return SKILL_AGENT_AWAITING_USER_REPLY

                if self.memory is not None:
                    self._persist_after_tool_turn(fname, args,str(result), active_skill_text, active_skill_ids, messages, log_callback)
                else:
                    messages.append({"role": "tool", "name": fname, "content": str(result)})
                    if fname == "select_skill" and active_skill_text and not str(result).startswith("错误"):
                        active_skills_text = self._build_active_skills_text(active_skill_text, active_skill_ids)
                        self._dynamic_prompt.update_active_skills(active_skills_text)
                        for i, msg in enumerate(messages):
                            if msg.get("role") == "system":
                                messages[i] = {"role": "system", "content": self._dynamic_prompt.build()}
                                print(f"[DEBUG-exec] 更新系统提示词_dynamic_prompt：{self._dynamic_prompt.build()}")
                                break

            print(f"[DEBUG-exec] ⚠️  达到最大步数限制 ({self.max_steps})，退出循环")
            tail = f"已达到最大执行步数限制（{self.max_steps}），已停止。"
            if log_callback:
                log_callback(tail, "assistant")
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", tail, metadata=metadata)
            self._start_summary_in_background(self._conversation_id, active_skill_ids)
            _emit_token_usage()
            print(f"[DEBUG-exec] 📤 正常退出循环，返回 tail 消息")
            return tail
        
        except Exception as e:
            print(f"[DEBUG-exec] ❌ 发生未捕获异常: {type(e).__name__}: {e}")
            print(f"[DEBUG-exec] 📋 堆栈跟踪:\n{traceback.format_exc()}")
            
            err_msg = f"执行出错: {type(e).__name__}: {e}"
            if log_callback:
                log_callback(err_msg, "assistant")
                log_callback(f"详细错误日志已记录，如需排查请查看终端输出。", "info")
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", err_msg, metadata=metadata)
            
            try:
                self._start_summary_in_background(self._conversation_id, active_skill_ids)
            except Exception as summary_err:
                print(f"[DEBUG-exec] ⚠️  尝试启动总结线程时出错: {summary_err}")
            
            _emit_token_usage()
            print(f"[DEBUG-exec] 📤 异常退出，返回 err_msg")
            return err_msg
        finally:
            self._uploaded_files_content = ""
            print(f"[DEBUG-exec] ===== run() 结束执行 =====")
