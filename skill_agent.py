from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import config
from base_tool import ToolContext, execute_atomic_tool
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

# `SkillAgent.run` 在调用 `ask_user` 且成功挂起时返回该常量（非自然语言，便于 UI 识别）。
SKILL_AGENT_AWAITING_USER_REPLY = "__SKILL_AGENT_AWAITING_USER_REPLY__"


def _ask_user_ui_log_payload(args: dict[str, Any]) -> str:
    """供界面解析：问题 + 可选上下文 + 建议选项列表（JSON）。"""
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


def _parse_instruction_call(content: str) -> Optional[tuple[str, dict]]:
    """
    从模型输出中解析工具调用指令。
    指令格式：<function name="工具名称">工具参数(JSON格式)</function>
    
    返回：(工具名称, 参数字典) 或 None
    """
    import re
    
    pattern = r'<function name="([^"]+)">\s*(\{.*?\})\s*</function>'
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        tool_name = match.group(1).strip()
        args_json = match.group(2).strip()
        try:
            args = json.loads(args_json)
            return (tool_name, args)
        except json.JSONDecodeError:
            return None
    return None


def _build_system_prompt(catalog: str) -> str:
    return f"""你是 SkillAgent：根据用户的业务提问，从下列 Skill 中选择并执行合适流程。

{catalog}

## 工具使用约定
0. 部分Skill里面描述中若说明仍需其它 Skill，可再 `select_skill`（已自动加载的 id 再选不会重复追加）。
1. 按需调用 `select_skill` 加载 Skill 全文（可加载一个或多个）。若用户任务明显需要多套规范，请依次 `select_skill`；下文会同时列出本轮已加载的全部 Skill，须一并遵守（若有冲突，以更具体或后加载的说明为准）。
2. 执行过程中使用 `run_command` 执行 Windows CMD 命令完成具体操作（如读取文件、写入文件、列出目录、运行脚本等）。
3. **关键规则**：当读取当前加载的 Skill 包内的文件时，**必须**指定 `skill_id` 参数，否则路径将无法正确解析。
4. 当你认为已满足用户目标时，调用 `finish`，在参数 `message` 中给出完整、用户可读的最终答复。
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

## 输出格式要求
你必须使用以下指令格式调用工具，**不要使用 JSON 格式的 function call**：

<function name="工具名称">
工具参数（JSON格式）
</function>

例如：
<function name="select_skill">
{{"skill_id": "skill_example"}}
</function>

<function name="run_command">
{{"command": "dir", "cwd": ".", "timeout_sec": 30}}
</function>

<function name="ask_user">
{{"question": "请问您希望保存到哪个位置？", "choices": ["桌面", "文档"]}}
</function>

<function name="finish">
{{"message": "任务已完成。我已经为您创建了所需的文件。"}}
</function>

## run_command 常用命令示例
- 列出目录: `{{"command": "dir", "cwd": "."}}`
- 创建文件: `{{"command": "echo hello > test.txt", "cwd": "."}}`
- 读取文件内容: `{{"command": "type test.txt", "cwd": "."}}`
- 写入文件: `{{"command": "echo content > file.txt", "cwd": "."}}`
- 删除文件: `{{"command": "del test.txt", "cwd": "."}}`
- 创建目录: `{{"command": "mkdir new_folder", "cwd": "."}}`
- 运行 Python 脚本: `{{"command": "python script.py", "cwd": "./scripts"}}`
- 读取 Skill 包内文件: `{{"command": "type example/test.md", "skill_id": "skill_name", "cwd": "."}}`

请确保 JSON 参数格式正确，使用双引号，并且工具名称正确无误。
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

    def _disabled_skill_ids_frozen(self) -> frozenset[str]:
        return frozenset(load_disabled_skill_ids())

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    def reload_skills(self) -> None:
        self.registry.reload()

    def start_new_conversation(self) -> tuple[str, str]:
        """生成新的 conversation_id 并立即落库；返回 (id, 默认展示名，暂为 id)。"""
        if self.memory is None:
            self._conversation_id = ""
            return (self._conversation_id, "")
        self._conversation_id = str(uuid.uuid4())
        title = self.memory.ensure_conversation(self._conversation_id,title=f"新会话-{self._conversation_id[:5]}")
        return (self._conversation_id, title)

    def set_conversation_id(self, conversation_id: str) -> None:
        """切换到已有或新建的 conversation（与多标签页联动）。"""
        self._conversation_id = (conversation_id or "").strip()

    def list_saved_conversations(self) -> list[Conversation]:
        """从持久化层读取当前用户下全部会话（无 Memory 时为空）。"""
        if self.memory is None:
            return []
        return self.memory.list_user_conversations()

    def message_records_for_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        """某会话的完整消息记录（含 metadata），用于界面恢复历史。"""
        if self.memory is None:
            return []
        return self.memory.get_message_records((conversation_id or "").strip())

    @staticmethod
    def conversation_awaits_user_clarification(
        memory: Memory | None,
        conversation_id: str,
    ) -> bool:
        """最后一条持久化消息是否为成功的 `ask_user` 挂起（错误类 ask_user 不算）。"""
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
        """从 Memory 恢复历史（不含 system），再追加本轮用户输入；system 始终用当前 catalog 现算。"""
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
        model = get_chat_model()
        disabled = self._disabled_skill_ids_frozen()
        skills_visible = [s for s in self.registry.list_skills() if s.skill_id not in disabled]
        catalog = build_skills_catalog_text(skills_visible)
        system_prompt = _build_system_prompt(catalog)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query.strip()},
        ]
        active_skill_text: list[str] = []
        active_skill_ids: list[str] = []

        if self.memory is not None:
            self._append_model_messages(messages, system_prompt=system_prompt, user_query=user_query)

        for step in range(self.max_steps):
            msg = model.complete(messages)
            text = _message_text(msg)
            
            if not text:
                err = "模型未返回内容，无法继续。"
                if log_callback:
                    log_callback(err, "assistant")
                if self.memory is not None:
                    self.memory.append_message(self._conversation_id, "assistant", err)
                return err

            instruction_call = _parse_instruction_call(text)
            if not instruction_call:
                if log_callback:
                    log_callback(text, "assistant")
                if self.memory is not None:
                    self.memory.append_message(self._conversation_id, "assistant", text)
                return text

            fname, args = instruction_call

            if log_callback:
                if fname == "finish":
                    log_callback(str(args.get("message", "")), "assistant")
                elif fname != "select_skill":
                    try:
                        args_s = json.dumps(args, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_s = str(args)
                    log_callback(f"调用工具 `{fname}` · {args_s}", "tool")
                else:
                    log_callback(f"选择 Skill: {args.get('skill_id', '')}", "think")
            if self.memory is not None:
                self.memory.append_message(self._conversation_id, "assistant", text, metadata={"type": "think"})
            
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
                log_callback(r, "base_tool")

            if terminate and final is not None:
                # 正常执行结束，最后回答非空
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
