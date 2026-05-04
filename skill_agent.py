from __future__ import annotations

import json
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
from memory import Memory
from memory.conversation import Conversation
from skill import (
    SkillRegistry,
    build_skills_catalog_text,
    execute_skill_control_tool,
    skills_auto_matched_for_query,
)

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


def _build_system_prompt(catalog: str) -> str:
    return f"""你是 SkillAgent：根据用户的业务提问，从下列 Skill 中选择并执行合适流程。

{catalog}

## 工具使用约定
0. 部分Skill里面描述中若说明仍需其它 Skill，可再 `select_skill`（已自动加载的 id 再选不会重复追加）。
1. 按需调用 `select_skill` 加载 Skill 全文（可加载一个或多个）。若用户任务明显需要多套规范，请依次 `select_skill`；下文会同时列出本轮已加载的全部 Skill，须一并遵守（若有冲突，以更具体或后加载的说明为准）。
2. 执行过程中使用 `run_command` 执行 Windows CMD 命令完成具体操作（如读取文件、写入文件、列出目录、运行脚本等）。
3. **关键规则**：当读取当前加载的 Skill 包内的文件时，**必须**指定 `skill_id` 参数，否则路径将无法正确解析。
4. **【最重要】当你完成用户任务后，必须调用 `finish` 工具结束，在参数 `message` 中给出完整、用户可读的最终答复。禁止在未调用 finish 的情况下结束对话。
5. 若当前没有可用 Skill，可直接用 `run_command` 与常识完成用户请求，并 `finish` 结束。
6. 若缺关键信息、存在多种合理策略需用户选择、或涉及敏感/不可逆操作需确认，调用 `ask_user` 提问；用户在下一条消息回复后你会从当前进度继续。勿滥用，同一任务内澄清宜少而精。

【最高优先级·Skill 加载铁律】
以下流程为**不可跳过、不可省略、不可中断**的强制执行步骤，违反即任务失败：

当你使用 select_skill 加载技能时，必须严格按顺序执行以下 6 步：
Step 1：完整阅读主文档全部内容，禁止跳段、禁止只读部分
Step 2：**逐行扫描**文档，提取所有被反引号包裹的文件路径（格式：`./xxx/xxx.md`）
        → 必须提取全部路径，禁止遗漏任何一个
Step 3：对**每一个**提取到的文件路径，**必须立即调用run_command工具读取内容**
        → 调用格式：`{{"command": "type 文件路径", "skill_id": "当前skill的id", "cwd": "."}}`
        → **必须**指定 skill_id 参数，否则文件将无法找到
        → 一个文件都不能少，不读取视为严重违规
Step 4：若文档要求运行 scripts/ 下的 .py 脚本
        → 必须使用run_command执行，禁止跳过
        → 调用格式：`{{"command": "python 脚本名.py", "skill_id": "当前skill的id", "cwd": "."}}`
Step 5：将所有读取到的文件内容 + 主文档，**完整合并**为最终上下文
Step 6：扫描合并后的内容，若发现新的 Skill 引用
        → 重复 Step1~Step5 递归加载，直到无新文件为止

【刚性约束】
1. 未完成全部文件读取前，禁止回答用户问题
2. 必须显性调用工具，禁止脑补文件内容
3. 必须加载所有关联 Skill，禁止只加载主文档
4. 每完成一步，必须确认：已完成 Step X
5. **任务完成后必须调用 finish 工具，禁止省略**

## run_command 常用命令示例
- 列出目录: `{{"command": "dir", "cwd": "."}}`
- 创建文件: `{{"command": "echo hello > test.txt", "cwd": "."}}`
- 读取文件内容: `{{"command": "type test.txt", "cwd": "."}}`
- 写入文件: `{{"command": "echo content > file.txt", "cwd": "."}}`
- 删除文件: `{{"command": "del test.txt", "cwd": "."}}`
- 创建目录: `{{"command": "mkdir new_folder", "cwd": "."}}`
- 运行 Python 脚本: `{{"command": "python script.py", "cwd": "./scripts"}}`
- 读取 Skill 包内文件: `{{"command": "type example/test.md", "skill_id": "skill_name", "cwd": "."}}`

请确保参数格式正确，使用双引号。
"""


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
        self._tool_ctx = ToolContext(work_dir=self.work_dir, executor=executor)
        self._recent_commands: list[tuple[str, str]] = []

    def _disabled_skill_ids_frozen(self) -> frozenset[str]:
        return frozenset(load_disabled_skill_ids())

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
        self.memory.set_active_skills(cid, [])
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
            parts = [
                f"### 已加载 Skill #{i + 1}\n\n{t.strip()}"
                for i, t in enumerate(active_skill_text)
            ]
            merged = "\n\n---\n\n".join(parts)
            extra_user = (
                "当前会话中已加载的 Skill 文档如下（按加载顺序，须同时遵守；"
                "若有冲突以更具体的条款或后加载的文档为准）：\n\n" + merged
            )
            self.memory.append_message(cid, "user", extra_user,metadata={"type":"skill_content"})
            messages.append({"role": "user", "content": extra_user})

    def run(self, user_query: str, log_callback: Optional[Callable[[str, str], Any]] = None) -> str:
        self._recent_commands = []
        model = get_chat_model()
        disabled = self._disabled_skill_ids_frozen()
        skills_visible = [s for s in self.registry.list_skills() if s.skill_id not in disabled]
        catalog = build_skills_catalog_text(skills_visible)
        system_prompt = _build_system_prompt(catalog)
        tools = model.build_skill_agent_tools()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query.strip()},
        ]
        active_skill_text: list[str] = []
        active_skill_ids: list[str] = []

        if self.memory is not None:
            self._append_model_messages(messages, system_prompt=system_prompt, user_query=user_query)
            prior_messages = self.memory.get_message_records(self._conversation_id)
            if prior_messages and len(prior_messages) >= 2:
                last_msg = prior_messages[-1]
                prev_msg = prior_messages[-2]
                if last_msg.get("role") == "user" and prev_msg.get("role") == "tool":
                    prev_meta = prev_msg.get("metadata") or {}
                    if prev_meta.get("name") == "ask_user":
                        user_choice = user_query.strip()
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
                                            break
                        elif user_choice == "取消":
                            cancel_msg = "操作已取消"
                            if log_callback:
                                log_callback(cancel_msg, "assistant")
                            if self.memory is not None:
                                self.memory.append_message(self._conversation_id, "assistant", cancel_msg)
                            return cancel_msg

        for step in range(self.max_steps):
            thinking_parts: list[str] = []
            content_parts: list[str] = []

            def _stream_callback(content: str, msg_type: str) -> None:
                if log_callback:
                    log_callback(content, msg_type)
                if msg_type == "think":
                    thinking_parts.append(content)
                elif msg_type == "content":
                    content_parts.append(content)

            function_call = model.stream_request_llm_with_tools(messages, tools, _stream_callback)

            full_thinking = "".join(thinking_parts).strip()

            # 判断是否为纯文本回复（无工具调用）
            is_text_only = (
                function_call is not None and
                function_call.get("name") is None and
                function_call.get("content") is not None
            )

            if is_text_only or (function_call is None):
                # 纯文本回复：内容已经在流式过程中显示过，只需入库
                final_text = ""
                if is_text_only:
                    final_text = function_call.get("content", "")
                else:
                    final_text = "".join(content_parts).strip()
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
                    return err

                if self.memory is not None:
                    self.memory.append_message(self._conversation_id, "assistant", final_text)
                return final_text

            fname = function_call.get("name")
            arg_str = function_call.get("arguments", "{}")
            try:
                args = json.loads(arg_str)
            except json.JSONDecodeError:
                args = {}

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
                    pass
                elif fname != "select_skill":
                    log_callback(f"调用工具 `{fname}` · {args_s}", "tool")
                else:
                    log_callback(f"选择 Skill: {args.get('skill_id', '')}", "tool")
            if self.memory is not None:
                self.memory.append_message(self._conversation_id, "assistant", f"调用工具: {fname}", metadata={"type": "tool_call", "name": fname, "args": arg_str,"reasoning_content":full_thinking})
            
            if fname == "run_command":
                command = str(args.get("command", "") or "").strip()
                skill_id = args.get("skill_id", "")
                
                if skill_id:
                    need_install, packages_to_install, err_msg = check_skill_dependencies(
                        str(skill_id), self.registry
                    )
                    if err_msg:
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
                    return SKILL_AGENT_AWAITING_USER_REPLY
            
            result, terminate, final = self._dispatch(fname, args, active_skill_text, active_skill_ids)

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
                        return auto_end_msg
                log_callback(r, "base_tool")

            if terminate and final is not None:
                if self.memory is not None:
                    cid = self._conversation_id
                    self.memory.append_message(cid, "tool", str(result), metadata={"name": fname})
                    self.memory.append_message(cid, "assistant", str(final))
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
                    )
                else:
                    messages.append({"role": "tool", "name": fname, "content": str(result)})
                if log_callback:
                    log_callback(_ask_user_ui_log_payload(args), "await_user")
                return SKILL_AGENT_AWAITING_USER_REPLY

            if self.memory is not None:
                self._persist_after_tool_turn(fname, args,str(result), active_skill_text, active_skill_ids, messages)
            else:
                messages.append({"role": "tool", "name": fname, "content": str(result)})
                if fname == "select_skill" and active_skill_text and not str(result).startswith("错误"):
                    parts = [
                        f"### 已加载 Skill #{i + 1}\n\n{t.strip()}"
                        for i, t in enumerate(active_skill_text)
                    ]
                    merged = "\n\n---\n\n".join(parts)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "当前会话中已加载的 Skill 文档如下（按加载顺序，须同时遵守；"
                                "若有冲突以更具体的条款或后加载的文档为准）：\n\n" + merged
                            ),
                        }
                    )

        tail = f"已达到最大执行步数限制（{self.max_steps}），已停止。"
        if log_callback:
            log_callback(tail, "assistant")
        if self.memory is not None:
            self.memory.append_message(self._conversation_id, "assistant", tail)
        return tail
