from __future__ import annotations

import json
import threading
import uuid
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
    ) -> None:
        self.work_dir = str(Path(work_dir).resolve())
        sd = skills_dir if skills_dir is not None else config.SKILLS_DIR
        self.registry = SkillRegistry(sd)
        self.max_steps = int(max_steps if max_steps is not None else config.SKILL_AGENT_MAX_STEPS)
        self.executor = executor
        self.memory = memory
        self.username = username
        if memory is not None:
            cid = (conversation_id or "").strip()
            self._conversation_id = cid
        else:
            self._conversation_id = (conversation_id or "").strip()
        self._tool_ctx = ToolContext(work_dir=self.work_dir, executor=executor, memory=memory)
        self._recent_commands: list[tuple[str, str]] = []
        self._compactor: ContextCompactor | None = None
        self._token_usage = TokenUsage.empty()
        self._dynamic_prompt = DynamicSystemPrompt()
        self._conversation_constraints: str = ""

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
        new_system_prompt = self._dynamic_prompt.build()
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

    def _build_dynamic_system_prompt(
        self,
        catalog: str,
        active_skill_text: list[str] | None = None,
        active_skill_ids: list[str] | None = None,
        user_query: str | None = None,
    ) -> str:
        self._dynamic_prompt.clear_all_placeholders()
        self._dynamic_prompt.update_skill_catalog(catalog)
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

    def set_conversation_constraints(self, constraints: str) -> None:
        self._conversation_constraints = (constraints or "").strip()

    def clear_conversation_constraints(self) -> None:
        self._conversation_constraints = ""

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
        cmd_lower = command.lower().strip()
        dangerous_prefixes = [
            "del ",
            "erase ",
            "rmdir ",
            "rd ",
            "copy ",
            "move ",
            "ren ",
            "rename ",
            "mkdir ",
            "md ",
        ]
        for pattern in dangerous_prefixes:
            if cmd_lower.startswith(pattern):
                return True
        
        dangerous_contains = [
            " > ",
            " >> ",
            " >",
            " >>",
            " set-content ",
            " set-content-",
            " add-content ",
            " add-content-",
            " out-file ",
            " out-file-",
            " new-item ",
            " new-item-",
            " remove-item ",
            " remove-item-",
            " rm ",
        ]
        for pattern in dangerous_contains:
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
                    return "检测到重复的文件写入操作且已成功完成，任务自动结束。"
                seen.add(cmd)
        
        return None

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
        if name in ("select_skill", "finish", "ask_user"):
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

    def run(self, user_query: str, log_callback: Optional[Callable[[str, str], Any]] = None) -> str:
        import traceback
        print(f"[DEBUG-exec] ===== run() 开始执行 =====")
        print(f"[DEBUG-exec] user_query 长度: {len(user_query)}, 前50字: {user_query[:50]}")
        print(f"[DEBUG-exec] conversation_id: {self._conversation_id}")
        
        self._recent_commands = []
        self._token_usage = TokenUsage.empty()

        def _emit_token_usage():
            if log_callback and getattr(config, "TOKEN_USAGE_ENABLED", False):
                from dataclasses import asdict
                token_usage_json = json.dumps(asdict(self._token_usage), ensure_ascii=False)
                log_callback(token_usage_json, "token_usage")

        try:
            model = get_chat_model()
            disabled = self._disabled_skill_ids_frozen()
            skills_visible = [s for s in self.registry.list_skills() if s.skill_id not in disabled]
            catalog = build_skills_catalog_text(skills_visible)
            system_prompt = self._build_dynamic_system_prompt(catalog, user_query=user_query)
            print(f"[DEBUG-exec] 初始系统提示词：{system_prompt}")
            tools = model.build_skill_agent_tools()
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
                                                        self.memory.append_message(self._conversation_id, "assistant", err_msg)
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
                                    self.memory.append_message(self._conversation_id, "assistant", cancel_msg)
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
                thinking_parts: list[str] = []
                content_parts: list[str] = []

                def _stream_callback(content: str, msg_type: str) -> None:
                    if log_callback:
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
                            self.memory.append_message(self._conversation_id, "assistant", err)
                        self._start_summary_in_background(self._conversation_id, active_skill_ids)
                        _emit_token_usage()
                        return err

                    if self.memory is not None:
                        self.memory.append_message(self._conversation_id, "assistant", final_text)
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

                result, terminate, final = self._dispatch(fname, args, active_skill_text, active_skill_ids)

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
                                file_path = self._extract_file_path(command)
                                if file_path:
                                    check_result = self._verify_file_exists(file_path, args.get("cwd", "."))
                                    if log_callback:
                                        log_callback(f"检查结果: {check_result}", "base_tool")
                                    if self.memory is not None:
                                        self.memory.append_message(self._conversation_id, "tool", check_result, metadata={"name": "verify"})
                                    messages.append({"role": "tool", "name": "verify", "content": check_result})
                        
                        auto_end_msg = self._check_repeated_write_success(command, str(result))
                        if auto_end_msg:
                            log_callback(auto_end_msg, "assistant")
                            self.memory.append_message(self._conversation_id, "assistant", auto_end_msg)
                            self._start_summary_in_background(self._conversation_id, active_skill_ids)
                            _emit_token_usage()
                            return auto_end_msg
                    log_callback(r, "base_tool")

                if terminate and final is not None:
                    if self.memory is not None:
                        cid = self._conversation_id
                        self.memory.append_message(cid, "tool", str(result), metadata={"name": fname})
                        self.memory.append_message(cid, "assistant", str(final))
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
                self.memory.append_message(self._conversation_id, "assistant", tail)
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
                self.memory.append_message(self._conversation_id, "assistant", err_msg)
            
            try:
                self._start_summary_in_background(self._conversation_id, active_skill_ids)
            except Exception as summary_err:
                print(f"[DEBUG-exec] ⚠️  尝试启动总结线程时出错: {summary_err}")
            
            _emit_token_usage()
            print(f"[DEBUG-exec] 📤 异常退出，返回 err_msg")
            return err_msg
        finally:
            print(f"[DEBUG-exec] ===== run() 结束执行 =====")
