"""SkillAgent 核心类 — 从原 skill_agent.py 整体迁入。

此类保持完整不变，后续再按职责拆分为子管理器。
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from sys import platform
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
from llm.BaseChatModel import StreamResult
from llm.token_usage import TokenUsage
from memory import Memory
from agent_events import AgentEvent, AgentEventType, QueueMode

from memory.conversation import Conversation
from prompt import DynamicSystemPrompt
from prompt.template import (
    SKILL_CATALOG_SECTION_TEMPLATE,
    ACTIVE_SKILLS_SECTION_TEMPLATE,
)
from skill import (
    SkillRegistry,
    build_skills_catalog_text,
    execute_skill_control_tool,
    skills_auto_matched_for_query,
    format_skill_for_prompt,
)

from logger import get_module_logger

# 从包内 helpers 导入枚举、常量和纯函数
from skill_agent._helpers import (
    ConversationState,
    PlanMode,
    SKILL_AGENT_AWAITING_USER_REPLY,
    _ask_user_ui_log_payload,
    _message_text,
    _history_without_system,
    _build_system_prompt,
    _ensure_valid_json_args,
)

logger = get_module_logger("SkillAgent")


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
        event_callback: Optional[Callable[[AgentEvent], None]] = None,
    ) -> None:
        """初始化 SkillAgent，配置工作目录、技能注册表、工具上下文和状态机。

        Args:
            work_dir: 工作目录的绝对路径，用于工具执行和文件操作。
            skills_dir: 技能定义目录，默认使用 config.SKILLS_DIR。
            max_steps: 已弃用。循环终止由 MAX_TOKEN_BUDGET 和重复检测控制。保留参数仅向后兼容。
            executor: 命令执行器实例，用于执行 run_command 等需要子进程的工具。
            memory: 对话记忆管理器，用于持久化消息和技能状态。
            conversation_id: 会话唯一标识，用于关联对话历史。
            username: 用户名，注入系统提示词中供 LLM 个性化回复。
            file_upload_controller: 文件上传控制器，处理用户上传文件。
            event_callback: 结构化事件回调函数，接收 AgentEvent 参数。

        Side effects:
            初始化技能注册表、工具上下文、状态机和重复检测相关字段。
        """
        self.work_dir = str(Path(work_dir).resolve())
        sd = skills_dir if skills_dir is not None else config.SKILLS_DIR
        builtin_sd = config.BUILTIN_SKILLS_DIR
        self.registry = SkillRegistry(sd, builtin_sd)
        self.max_steps = int(max_steps if max_steps is not None else config.SKILL_AGENT_MAX_STEPS)
        self.executor = executor
        self.memory = memory
        self.username = username
        if memory is not None:
            self._conversation_id = (conversation_id or "").strip()
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
        self._token_usage = TokenUsage.empty()
        self._dynamic_prompt = DynamicSystemPrompt()
        self._conversation_constraints: str = ""
        self._last_user_query: str | None = None
        self._stop_event = threading.Event()
        self._recent_tool_calls: list[dict] = []
        self._consecutive_repeat_count: int = 0
        # 存储上传文件的结构化数据：{"text_content": str, "images": list}
        self._uploaded_files_content: dict = {"text_content": "", "images": []}
        # 当前轮强制引用的 ext 元数据（forced_refs），持久化时一次性消费
        self._pending_user_refs: list[dict[str, Any]] = []
        self._enable_thinking: bool = False
        self._step_plan: list[dict] = []
        self._current_step: int = 0
        self._success_criteria: str = ""
        # 计划确认环节相关状态
        self._pending_plan: list[dict] = []
        self._pending_success_criteria: str = ""
        self._pending_plan_analysis: str = ""
        self._plan_confirmed: bool = False
        # 运行时拦截确认相关状态（新方案）
        self._runtime_confirm_pending: bool = False  # 是否有待处理的运行时确认
        self._runtime_confirm_fname: str = ""  # 待执行的工具名
        self._runtime_confirm_args: dict = {}  # 待执行的参数
        self._runtime_confirm_messages: list[dict] = []  # 当时的消息列表快照
        # 运行时确认后继续执行的标志
        self._from_runtime_confirm_continue: bool = False
        # ask_user 等待恢复相关状态（区别于运行时确认：ask_user 由 LLM 工具调用触发）
        self._ask_user_confirm_pending: bool = False  # 是否有待恢复的 ask_user
        self._ask_user_confirm_messages: list[dict] = []  # ask_user 触发时的消息快照
        # 状态机
        self._state = ConversationState.IDLE
        # 双层循环：Steering 消息队列（用户中途干预）
        self._steering_queue: list[str] = []
        self._steering_mode: QueueMode = QueueMode.ONE_AT_A_TIME
        # 双层循环：FollowUp 消息队列（链式追加任务）
        self._followup_queue: list[str] = []
        self._followup_mode: QueueMode = QueueMode.ONE_AT_A_TIME
        # 结构化事件回调
        self._event_callback: Optional[Callable[[AgentEvent], None]] = event_callback

    def set_file_upload_controller(self, controller: Any) -> None:
        """Set the file upload controller for handling file upload operations.

        Args:
            controller: File upload controller instance to delegate upload tasks to.
        """
        self._tool_ctx.file_upload_controller = controller

    def set_uploaded_files_content(self, content: str | dict) -> None:
        """设置上传文件的结构化内容。

        Args:
            content: 文件内容，支持两种格式：
                - dict: 结构化数据，格式为 {"text_content": str, "images": list}
                  images 列表项格式：{"file_name": str, "base64_data": str, "mime_type": str}
                - str: 纯文本内容（向后兼容），会被转换为 {"text_content": content, "images": []}
        """
        if isinstance(content, dict):
            # 确保数据结构完整
            self._uploaded_files_content = {
                "text_content": content.get("text_content", ""),
                "images": content.get("images", []),
            }
        elif isinstance(content, str):
            # 向后兼容：将字符串转换为结构化数据
            logger.debug(f"向后兼容：将字符串内容转换为结构化数据，长度={len(content)}")
            self._uploaded_files_content = {
                "text_content": content,
                "images": [],
            }
        else:
            logger.warning(f"不支持的 content 类型: {type(content)}，使用空结构")
            self._uploaded_files_content = {"text_content": "", "images": []}

    def _consume_uploaded_files_content(
        self,
        user_content: str,
        enable_vision: bool = True,
    ) -> str | list:
        """将上传文件内容追加到用户消息内容中，并清空缓存（一次性消费）。

        文件内容嵌入用户消息而非系统提示词，原因：
        - 文件内容是用户数据，不属于系统指令
        - 仅在当前轮次出现一次，不会在 agent 多步循环中重复注入系统提示词
        - 覆盖所有路径（direct_reply / plan_confirm / agent loop）

        Args:
            user_content: 用户输入的文本内容
            enable_vision: 是否启用视觉能力（图片处理）

        Returns:
            str | list: OpenAI 消息内容格式
                - str: 纯文本消息（无图片或 enable_vision=False）
                - list: 多模态消息格式，包含文本和图片
        """
        if not self._uploaded_files_content:
            # 无上传文件，直接返回用户内容
            return user_content

        text_content = self._uploaded_files_content.get("text_content", "")
        images = self._uploaded_files_content.get("images", [])

        # 清空缓存（一次性消费）
        self._uploaded_files_content = {"text_content": "", "images": []}

        # 构建最终消息内容
        message_parts: list[dict] = []

        # 1. 处理用户文本内容
        if user_content and user_content.strip():
            message_parts.append({
                "type": "text",
                "text": user_content.strip(),
            })

        # 2. 处理文件文本内容（如果有）
        if text_content and text_content.strip():
            # 如果已有用户文本，追加到同一文本块中
            if message_parts and message_parts[0]["type"] == "text":
                existing_text = message_parts[0]["text"]
                message_parts[0]["text"] = existing_text + "\n\n" + text_content.strip()
            else:
                message_parts.append({
                    "type": "text",
                    "text": text_content.strip(),
                })

        # 3. 处理图片内容（仅在 enable_vision=True 时）
        if enable_vision and images:
            logger.debug(f"处理 {len(images)} 张图片，enable_vision={enable_vision}")
            for img in images:
                file_name = img.get("file_name", "unknown")
                base64_data = img.get("base64_data", "")
                mime_type = img.get("mime_type", "image/png")

                if not base64_data:
                    logger.warning(f"图片 {file_name} 缺少 base64_data，跳过")
                    continue

                # 构建 data URL 格式：data:{mime_type};base64,{base64_data}
                image_url = f"data:{mime_type};base64,{base64_data}"
                message_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                    },
                })
                logger.debug(f"添加图片到消息: {file_name}, MIME={mime_type}")
        elif images and not enable_vision:
            # enable_vision=False 时跳过图片处理，记录日志
            logger.info(f"enable_vision=False，跳过 {len(images)} 张图片的处理")

        # 4. 根据消息内容数量决定返回格式
        if not message_parts:
            # 无任何内容，返回空字符串
            return ""
        elif len(message_parts) == 1 and message_parts[0]["type"] == "text":
            # 只有文本内容，返回字符串格式（符合 OpenAI 规范）
            return message_parts[0]["text"]
        else:
            # 多模态内容，返回列表格式
            return message_parts



    def _disabled_skill_ids_frozen(self) -> frozenset[str]:
        """获取已禁用技能 ID 的不可变集合，用于技能过滤。

        Returns:
            包含所有已禁用技能 ID 的 frozenset，每次调用重新从配置加载。
        """
        return frozenset(load_disabled_skill_ids())

    def _get_conversation_type(self) -> str:
        """获取当前会话类型，如果没有会话则返回默认类型"""
        if self.memory is None:
            return 'agent_conversation'
        conv = self.memory.get_conversation(self._conversation_id)
        if conv:
            return conv.type or 'agent_conversation'
        return 'agent_conversation'

    def _get_skills_for_conversation_type(self, conversation_type: str) -> list[Any]:
        """根据会话类型获取可用的skill列表"""
        from skill_agent_preferences import get_default_skills_for_type
        disabled = self._disabled_skill_ids_frozen()
        
        # 获取该会话类型绑定的skill ID列表
        bound_skill_ids = get_default_skills_for_type(conversation_type)
        
        # 从registry中获取对应的skill对象
        skills = []
        for skill_id in bound_skill_ids:
            skill = self.registry.get(skill_id)
            if skill:
                skills.append(skill)
        
        return skills

    def _update_system_message(self, messages: list[dict]) -> None:
        """更新消息列表中的系统消息"""
        # 使用最近保存的用户查询来重新构建系统提示词
        # 根据会话类型过滤skill目录
        conv_type = self._get_conversation_type()
        skills_visible = self._get_skills_for_conversation_type(conv_type)
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

        # 根据会话类型设置模板
        self._dynamic_prompt.set_template_for_conversation_type(conv_type)

        # 重建工具目录，避免 clear_all_placeholders() 清空 TOOL_CATALOG 占位符
        model = get_chat_model(enable_thinking=self._enable_thinking)
        tool_catalog = model.build_tool_catalog()
        tool_catalog_text = self._build_tool_catalog_text(tool_catalog)

        new_system_prompt = self._build_dynamic_system_prompt(
            catalog,
            active_skill_text=active_skill_text if active_skill_text else None,
            active_skill_ids=active_skill_ids if active_skill_ids else None,
            user_query=self._last_user_query,
            tool_catalog=tool_catalog_text,
        )

        logger.debug(f"更新系统提示词（会话类型: {conv_type}）：{new_system_prompt[:200]}...")
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = new_system_prompt
        else:
            messages.insert(0, {"role": "system", "content": new_system_prompt})

    def _build_active_skills_text(self, active_skill_text: list[str], active_skill_ids: list[str]) -> str:
        """将已加载技能列表格式化为系统提示词中的技能段落。

        Args:
            active_skill_text: 已格式化的技能文本列表，每个元素对应一个技能的提示词。
            active_skill_ids: 与 active_skill_text 一一对应的技能 ID 列表。

        Returns:
            格式化后的 ACTIVE_SKILLS_SECTION 文本；如果 active_skill_text 为空则返回空字符串。
        """
        if not active_skill_text:
            return ""
        parts = [
            f"### 已加载 Skill #{i + 1}: {active_skill_ids[i]}\n\n{t.strip()}"
            for i, t in enumerate(active_skill_text)
        ]
        merged = "\n\n---\n\n".join(parts)
        return ACTIVE_SKILLS_SECTION_TEMPLATE.format(skills=merged)

    def _fill_user_memory(self, query: str | None = None, limit: int = 5) -> str:
        """用户长期记忆功能已移除，返回空字符串。"""
        return ""

    def _fill_recent_memory_summary(self) -> str:
        """近期记忆摘要功能已移除，返回空字符串。"""
        return ""

    def _build_tool_catalog_text(self, tool_catalog: list[dict]) -> str:
        """将工具目录列表格式化为 Markdown 简要描述文本。

        Args:
            tool_catalog: 工具定义列表，每项包含 name 和 brief 字段。

        Returns:
            Markdown 格式的工具目录文本；如果 tool_catalog 为空则返回空字符串。
        """
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
        """Return a formatted string containing the user's basic system information.

        Returns:
            Multi-line string with username, current system time, and OS type.
        """
        import platform
        base_info = f"用户名：{self.username}\n"
        base_info+=f"当前系统时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        base_info+=f"当前系统类型：{platform.system()}"
        return base_info
    def _build_dynamic_system_prompt(
        self,
        catalog: str,
        active_skill_text: list[str] | None = None,
        active_skill_ids: list[str] | None = None,
        user_query: str | None = None,
        tool_catalog: str | None = None,
    ) -> str:
        """组装完整的动态系统提示词，填充所有占位符。

        按会话类型选择模板，依次填入基础信息、技能目录、工具目录、
        已加载技能、用户记忆、近期摘要和对话约束。

        Args:
            catalog: 技能目录文本。
            active_skill_text: 已加载技能的提示词文本列表，可选。
            active_skill_ids: 已加载技能的 ID 列表，可选。
            user_query: 最近用户查询，用于语义检索，可选。
            tool_catalog: 工具目录文本，可选。

        Returns:
            完整组装的系统提示词字符串。
        """
        # 根据会话类型设置模板
        conv_type = self._get_conversation_type()
        self._dynamic_prompt.set_template_for_conversation_type(conv_type)

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
        return self._dynamic_prompt.build()

    @property
    def conversation_id(self) -> str:
        """Return the current conversation's unique identifier.

        Returns:
            The UUID string of the active conversation, or empty string if none.
        """
        return self._conversation_id

    def reload_skills(self) -> None:
        """Reload all skill definitions from the registry, refreshing the available skill set.

        Side effects:
            Re-reads skill configurations from disk and updates the in-memory registry.
        """
        self.registry.reload()

    def start_new_conversation(self, *, conversation_type: str = 'agent_conversation', default_skills: list[dict] | None = None) -> tuple[str, str]:
        """Create a new conversation with a generated UUID, persisting it in memory.

        Args:
            conversation_type: Type label for the conversation (e.g. 'agent_conversation').
            default_skills: Optional list of dicts (id, name) for skills enabled by default;
                if None, loaded from global preferences for the given type.

        Returns:
            A tuple of (conversation_id, conversation_title).

        Side effects:
            Sets the internal conversation ID and updates the dynamic prompt template.
        """
        if self.memory is None:
            self._conversation_id = ""
            return (self._conversation_id, "")

        # 如果没有传入 default_skills，就从全局配置中加载该会话类型的默认技能
        if default_skills is None:
            from skill_agent_preferences import get_default_skills_for_type
            skill_ids = get_default_skills_for_type(conversation_type)
            default_skills = []
            for skill_id in skill_ids:
                skill = self.registry.get(skill_id)
                if skill:
                    skill_name = getattr(skill, "name", skill_id)
                    default_skills.append({"id": skill_id, "name": skill_name})

        self._conversation_id = str(uuid.uuid4())
        title = self.memory.ensure_conversation(
            self._conversation_id,
            title=f"{self._conversation_id[:5]}",
            conversation_type=conversation_type,
            default_skills=default_skills
        )

        # 根据会话类型设置模板
        self._dynamic_prompt.set_template_for_conversation_type(conversation_type)

        return (self._conversation_id, title)

    def maybe_set_conversation_title(self, query: str) -> None:
        """会话首条 query 到达时，用 query 内容替换默认标题（会话 ID 前缀）。

        仅当会话尚无消息记录时生效，不覆盖用户手动命名的标题。
        标题取 query 首行，剥离 <Files> 等文件标签与 <Skill:id/>、
        <File:id/>、<Cli:name/> 占位符，超长由前端渲染时截断。
        """
        if self.memory is None or not self._conversation_id:
            return
        try:
            if self.memory.count_messages(self._conversation_id) > 0:
                return
            cleaned = re.sub(r"<Files>.*?</Files>", "", query or "", flags=re.S).strip()
            # 剥离 /skill:id /cli:name 等命令前缀（标题中不展示引用编码）
            cleaned = re.sub(r"(?:^|\s)\/(skill|cli):[A-Za-z0-9_\-]+", " ", cleaned)
            # 剥离占位符（无 ext 背书判断：title 场景宁可多剥，不出现在标题里）
            cleaned = re.sub(r"<(?:Skill|File|Cli):[A-Za-z0-9_\-]+/>", " ", cleaned)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            first_line = cleaned.splitlines()[0].strip() if cleaned else ""
            if not first_line:
                return
            title = first_line[:30]
            self.memory.update_conversation_title(self._conversation_id, title)
            logger.info(
                f"会话标题已按首条 query 设置: conversation_id={self._conversation_id[:8]}, title={title}"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"按 query 设置会话标题失败: {e}")

    def set_conversation_id(self, conversation_id: str) -> None:
        """Set the active conversation ID, stripping surrounding whitespace.

        Args:
            conversation_id: The conversation UUID to activate; empty string if None.
        """
        self._conversation_id = (conversation_id or "").strip()

    def set_enable_thinking(self, enabled: bool) -> None:
        """Enable or disable the model's extended thinking mode.

        Args:
            enabled: True to enable thinking, False to disable.
        """
        self._enable_thinking = enabled

    def request_stop(self) -> None:
        """Signal a stop request to interrupt the current conversation processing loop.

        Side effects:
            Sets the internal stop event, causing is_stop_requested to return True.
        """
        self._stop_event.set()

    def _drain_steering_queue(self) -> list[str]:
        """排空 Steering 队列，根据队列模式返回消息列表。

        Returns:
            Steering 消息列表。
        """
        if not self._steering_queue:
            return []
        if self._steering_mode == QueueMode.ALL:
            messages = list(self._steering_queue)
            self._steering_queue.clear()
            return messages
        else:  # ONE_AT_A_TIME
            return [self._steering_queue.pop(0)]

    def _drain_followup_queue(self) -> list[str]:
        """排空 FollowUp 队列，根据队列模式返回消息列表。

        Returns:
            FollowUp 消息列表。
        """
        if not self._followup_queue:
            return []
        if self._followup_mode == QueueMode.ALL:
            messages = list(self._followup_queue)
            self._followup_queue.clear()
            return messages
        else:  # ONE_AT_A_TIME
            return [self._followup_queue.pop(0)]

    def is_stop_requested(self) -> bool:
        """Check whether a stop request has been issued for the current conversation.

        Returns:
            True if request_stop was called and not yet cleared, False otherwise.
        """
        return self._stop_event.is_set()

    def steer(self, message: str) -> None:
        """注入 Steering 消息，用于在 Agent 执行期间实时干预。

        Steering 消息会中断当前工具链，让 LLM 根据用户干预调整执行方向。

        Args:
            message: 用户的干预消息文本。
        """
        self._steering_queue.append(message.strip())
        logger.debug("Steering 消息已入队: %s (队列长度: %d)", message[:50], len(self._steering_queue))
        self._emit_event(AgentEventType.STEERING_RECEIVED, message=message[:200], queue_length=len(self._steering_queue))

    def followUp(self, message: str) -> None:
        """注入 FollowUp 消息，用于在当前任务完成后追加后续任务。

        当内层循环完成后，外层循环会检查 FollowUp 队列，若有消息则注入上下文并重启内层循环。

        Args:
            message: 后续任务消息文本。
        """
        self._followup_queue.append(message.strip())
        logger.debug("FollowUp 消息已入队: %s (队列长度: %d)", message[:50], len(self._followup_queue))
        self._emit_event(AgentEventType.FOLLOWUP_RECEIVED, message=message[:200], queue_length=len(self._followup_queue))

    def abort(self) -> None:
        """取消当前 LLM 调用并终止 Agent 执行。

        通过设置 stop_event 实现立即终止，效果等同于 request_stop()。
        """
        self._stop_event.set()
        logger.debug("Agent 已请求 abort")

    def _emit_event(self, event_type: AgentEventType, **data: Any) -> None:
        """发出结构化事件，通过回调通知外部监听者。

        若未设置事件回调（_event_callback 为 None），则静默跳过。
        回调执行中的异常被捕获并记录为警告，避免影响 Agent 主流程。

        Args:
            event_type: 事件类型枚举值。
            **data: 事件附加数据，作为 AgentEvent.data 传递。
        """
        if self._event_callback is not None:
            try:
                event = AgentEvent(
                    event_type=event_type,
                    data=data,
                    conversation_id=self._conversation_id,
                )
                self._event_callback(event)
            except Exception as e:
                logger.warning("事件回调执行失败: %s", e)

    def set_event_callback(self, callback: Optional[Callable[[AgentEvent], None]]) -> None:
        """设置结构化事件回调函数。

        Args:
            callback: 事件回调函数，接收 AgentEvent 参数；设为 None 则关闭事件通知。
        """
        self._event_callback = callback

    def set_conversation_constraints(self, constraints: str) -> None:
        """Set textual constraints that guide the conversation behavior.

        Args:
            constraints: Constraint text to apply; whitespace is stripped.
        """
        self._conversation_constraints = (constraints or "").strip()

    def clear_conversation_constraints(self) -> None:
        """Remove all conversation constraints, resetting to no constraints.

        Side effects:
            Sets the internal constraints string to empty.
        """
        self._conversation_constraints = ""

    def clear_runtime_cache(self) -> None:
        """清理运行时缓存，释放内存"""
        self._recent_tool_calls.clear()
        self._recent_commands.clear()
        self._dynamic_prompt.clear_all_placeholders()

    def _classify_input(self, user_query: str) -> PlanMode:
        """对用户输入进行分类，判断是否需要规划。
        
        Returns:
            PlanMode: 分类结果
        """
        # AI-BRANCH-MARKER: 输入分类开关分支 — INPUT_CLASSIFICATION_ENABLED=False时直接返回SIMPLE_TASK，跳过LLM分类调用
        if not config.INPUT_CLASSIFICATION_ENABLED:
            return PlanMode.SIMPLE_TASK
        
        try:
            model = get_chat_model(enable_thinking=self._enable_thinking)
            from prompt.template import INPUT_CLASSIFICATION_TEMPLATE
            
            prompt = INPUT_CLASSIFICATION_TEMPLATE.format(user_query=user_query.strip()[:2000])
            
            messages = [
                {"role": "system", "content": "你是一个输入分类器，请严格按JSON格式输出。"},
                {"role": "user", "content": prompt},
            ]

            response = model.get_client().chat.completions.create(
                model=model.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=100,
            )
            
            content = response.choices[0].message.content.strip() if response.choices else ""
            logger.debug("分类器原始响应: %r", content)
            
            # 空响应检查
            if not content:
                logger.warning("分类器返回空响应，使用默认模式")
                return PlanMode.SIMPLE_TASK
            
            # 去除可能的 markdown code block 包裹
            original_content = content
            content = content.strip()
            if content.startswith("```"):
                # 处理 ```json 或 ``` 开头的情况
                first_newline = content.find("\n")
                if first_newline != -1:
                    content = content[first_newline+1:]
                content = content.replace("```", "").strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
            
            if content != original_content:
                logger.debug("去除markdown包裹后: %r", content)
            
            # 尝试解析 JSON - 使用更健壮的匹配方式
            import re
            # 尝试匹配最外层的完整 JSON 对象
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                json_str = json_match.group()
                logger.debug("匹配到的JSON字符串: %r", json_str)
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError as je:
                    logger.warning("JSON解析失败: %s, JSON内容: %r", je, json_str)
                    return PlanMode.SIMPLE_TASK
                
                # 校验 result 必须是 dict
                if not isinstance(result, dict):
                    logger.warning("分类结果不是JSON对象: %s", type(result).__name__)
                    return PlanMode.SIMPLE_TASK
                
                mode_str = result.get("type", "simple_task")
                # 校验 mode_str 必须是有效的分类值
                if not isinstance(mode_str, str):
                    logger.warning("分类type字段类型错误: %s", type(mode_str).__name__)
                    return PlanMode.SIMPLE_TASK
                
                mode_str = mode_str.strip()
                logger.debug("输入分类结果: %s (原因: %s)", mode_str, result.get("reason", ""))
                
                if mode_str == "chat":
                    return PlanMode.NO_PLAN
                elif mode_str == "complex_task":
                    return PlanMode.COMPLEX_TASK
                else:
                    return PlanMode.SIMPLE_TASK
            
            return PlanMode.SIMPLE_TASK
        except Exception as e:
            logger.warning("输入分类失败，使用默认模式: %s", e)
            return PlanMode.SIMPLE_TASK

    def _direct_reply(self, user_query: str, log_callback: Optional[Callable[[str, str], Any]] = None) -> str:
        """无需规划模式：直接由 LLM 生成文本回答。"""
        try:
            model = get_chat_model(enable_thinking=self._enable_thinking)

            # _append_model_messages 内部会消费上传文件内容，这里无需提前处理
            messages: list[dict[str, Any]] = []
            self._append_model_messages(
                messages,
                system_prompt=f"你是一个友好的助手。请直接用简洁的语言回答用户问题。\n\n{self.get_base_info()}",
                user_query=user_query.strip(),
                enable_vision=model.enable_vision,
            )

            # 使用流式 API 进行回复
            def stream_callback(content: str, msg_type: str) -> None:
                """流式回调：将 'content' 映射为 'assistant'，'think' 保持不变"""
                logger.debug("[_direct_reply.stream_callback] 回调被触发: type=%s, content前50字=%s",
                             msg_type, content[:50] if content else "(空)")
                if log_callback:
                    # BaseChatModel 的回调类型是 "content" 或 "think"
                    # 前端期望的类型是 "assistant" 或 "think"
                    mapped_type = msg_type if msg_type == "think" else "assistant"
                    logger.debug("[_direct_reply.stream_callback] 映射类型: %s -> %s, log_callback已提供",
                                 msg_type, mapped_type)
                    log_callback(content, mapped_type)
                else:
                    logger.debug("[_direct_reply.stream_callback] log_callback 未提供，跳过发送")

            result = model.stream_complete(messages, stream_callback)

            reply = result.content or ""

            # 发送 token_usage 触发 stream_renderer.complete()，使 badge 被应用到卡片
            if log_callback and config.TOKEN_USAGE_ENABLED and result.token_usage:
                from dataclasses import asdict
                log_callback(json.dumps(asdict(result.token_usage), ensure_ascii=False), "token_usage")

            if self.memory is not None:
                # user 消息已在 _append_model_messages 中持久化，这里只追加 assistant 回复
                self.memory.append_message(self._conversation_id, "assistant", reply)

            logger.debug("直接回复完成，回复长度: %s", len(reply))
            return reply
        except Exception as e:
            err = f"回复出错: {e}"
            if log_callback:
                log_callback(err, "assistant")
            logger.error("直接回复失败: %s", e)
            return err

    def _plan_steps(self, user_query: str, tool_catalog_text: str = "", log_callback: Optional[Callable[[str, str], Any]] = None) -> Optional[dict]:
        """对复杂任务制定结构化执行计划。
        
        Returns:
            包含 analysis/plan/total_steps/success_criteria 的 dict，如果解析失败则返回 None
        """
        if not config.INPUT_CLASSIFICATION_ENABLED:
            return None
        
        try:
            model = get_chat_model(enable_thinking=self._enable_thinking)
            from prompt.template import COMPLEX_TASK_PLANNING_TEMPLATE
            
            prompt = COMPLEX_TASK_PLANNING_TEMPLATE.format(
                user_query=user_query.strip()[:2000],
                tool_catalog=tool_catalog_text[:2000] if tool_catalog_text else "（暂无工具目录信息）"
            )
            
            messages = [
                {"role": "system", "content": "你是一个复杂任务规划器，请严格按JSON格式输出计划。"},
                {"role": "user", "content": prompt},
            ]

            response = model.get_client().chat.completions.create(
                model=model.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=1000,
            )
            
            content = response.choices[0].message.content.strip() if response.choices else ""
            
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                plan_data = json.loads(json_match.group())

                # 保存计划到实例变量
                self._step_plan = plan_data.get("plan", [])
                self._current_step = 0
                self._success_criteria = plan_data.get("success_criteria", "")
                # 同步保存到 pending 变量，供确认环节使用
                self._pending_plan = list(self._step_plan)
                self._pending_success_criteria = self._success_criteria
                self._pending_plan_analysis = plan_data.get("analysis", "")

                total = plan_data.get("total_steps", len(self._step_plan))
                logger.debug("执行计划制定完成: %s 步, 成功标准: %s", total, self._success_criteria)
                return plan_data
            
            return None
        except Exception as e:
            logger.warning("制定执行计划失败，跳过计划阶段: %s", e)
            return None

    def _format_plan_display(self, plan_data: dict) -> str:
        """将结构化计划格式化为用户可读的展示文本。"""
        analysis = plan_data.get("analysis", "") or self._pending_plan_analysis
        steps = plan_data.get("plan", []) or self._pending_plan
        total = plan_data.get("total_steps", len(steps))
        success_criteria = plan_data.get("success_criteria", "") or self._pending_success_criteria

        plan_display = f"📋 **执行计划**（共 {total} 步）\n\n{analysis}\n\n"
        for s in steps:
            plan_display += f"**步骤{s.get('step', '?')}**: {s.get('action', '')}\n"
            plan_display += f"  工具: {s.get('tool', '?')} | 预期: {s.get('expected_result', '?')}\n"
            plan_display += f"  验证: {s.get('checkpoint', '?')}\n\n"
        plan_display += f"**成功标准**: {success_criteria}"
        return plan_display

    def _build_plan_constraints(self) -> str:
        """将已确认的计划构建为系统提示词约束文本，指导 LLM 按计划执行。"""
        steps = self._pending_plan
        if not steps:
            return ""
        lines = [
            "",
            "【已确认的执行计划 - 必须严格按照计划逐步执行】",
            f"任务分析：{self._pending_plan_analysis}",
            "",
        ]
        for s in steps:
            step_no = s.get("step", "?")
            action = s.get("action", "")
            tool = s.get("tool", "?")
            expected = s.get("expected_result", "")
            checkpoint = s.get("checkpoint", "")
            lines.append(f"步骤{step_no}: {action}")
            lines.append(f"  使用工具: {tool}")
            lines.append(f"  预期结果: {expected}")
            lines.append(f"  验证方式: {checkpoint}")
            lines.append("")
        lines.append(f"成功标准: {self._pending_success_criteria}")
        lines.append("")
        lines.append("执行要求：")
        lines.append("1. 请严格按照上述步骤顺序执行，不要遗漏或跳跃")
        lines.append("2. 每完成一步，对照 checkpoint 验证是否成功")
        lines.append("3. 如某步骤失败，分析原因并调整，但不要偏离整体计划")
        lines.append("4. 所有步骤完成后，对照成功标准确认任务完成，再调用 finish 结束")
        return "\n".join(lines)

    def _request_plan_confirmation(
        self,
        user_query: str,
        plan_data: dict,
        log_callback: Optional[Callable[[str, str], Any]] = None,
        enable_vision: bool = True,
        persist_query: Optional[str] = None,
    ) -> str:
        """生成计划后，请求用户确认。返回 SKILL_AGENT_AWAITING_USER_REPLY 以暂停等待用户。"""
        plan_display = self._format_plan_display(plan_data)

        # 展示计划
        if log_callback:
            log_callback(plan_display, "plan")

        confirm_payload = {
            "question": "以上是为您制定的执行计划，请确认是否开始执行：",
            "context": plan_display,
            "choices": ["确认执行", "取消", "调整计划"],
        }

        if self.memory is not None:
            conversation_id = self._conversation_id
            # 持久化原用户需求（此时 run() 尚未走到 _append_model_messages）
            metadata: dict[str, Any] = {}
            if hasattr(self, "_last_uploaded_files") and self._last_uploaded_files is not None:
                metadata["files"] = self._last_uploaded_files
                self._last_uploaded_files = None
            # 将上传文件内容追加到用户消息（一次性消费）；
            # 强制引用时 memory 保留原始占位符文本（前端渲染 chip）
            user_content = self._consume_uploaded_files_content(
                user_query.strip(),
                enable_vision=enable_vision,
            )
            persist_content = persist_query.strip() if persist_query is not None else user_content
            # 引用元数据合并进 metadata（ext.forced_refs 背书）
            self._consume_pending_user_refs(metadata)
            self.memory.append_message(conversation_id, "user", persist_content, metadata=metadata)
            # 持久化计划展示
            self.memory.append_message(conversation_id, "assistant", plan_display, metadata={"type": "plan"})
            # 持久化确认请求（type=plan_confirm 区别于普通 ask_user，避免被现有 ask_user 历史检测误触）
            self.memory.append_message(
                conversation_id,
                "tool",
                json.dumps(confirm_payload, ensure_ascii=False),
                metadata={
                    "type": "plan_confirm",
                    "name": "plan_confirm",
                    "args": json.dumps(confirm_payload, ensure_ascii=False),
                },
            )

        # 触发 UI 确认卡片
        if log_callback:
            log_callback(json.dumps(confirm_payload, ensure_ascii=False), "await_user")
            if config.TOKEN_USAGE_ENABLED:
                log_callback(json.dumps(asdict(self._token_usage), ensure_ascii=False), "token_usage")

        logger.debug("计划已生成，等待用户确认")
        return SKILL_AGENT_AWAITING_USER_REPLY

    def _check_plan_confirmation_resume(self, user_query: str) -> Optional[str]:
        """检测当前是否为「计划确认后的续跑」。
        
        Returns:
            "execute" - 用户确认执行，应跳过分类与重新规划直接进入执行
            "cancel"  - 用户取消
            "replan"  - 用户要求调整计划
            None      - 非计划确认续跑，走正常分类流程
        """
        if self.memory is None:
            return None
        conversation_id = self._conversation_id
        if not conversation_id:
            return None
        records = self.memory.get_message_records(conversation_id)
        if not records:
            return None
        last = records[-1]
        if last.get("role") != "tool":
            return None
        meta = last.get("metadata") or {}
        if meta.get("type") != "plan_confirm":
            return None

        choice = (user_query or "").strip()
        if choice == "确认执行":
            self._plan_confirmed = True
            logger.debug("用户确认执行计划，进入续跑")
            return "execute"
        elif choice == "取消":
            logger.debug("用户取消计划执行")
            self._pending_plan = []
            self._pending_success_criteria = ""
            self._pending_plan_analysis = ""
            return "cancel"
        elif choice == "调整计划":
            logger.debug("用户要求调整计划")
            self._pending_plan = []
            self._pending_success_criteria = ""
            self._pending_plan_analysis = ""
            return "replan"
        # 用户输入了其他内容，视为正常新输入
        return None

    def get_conversation_constraints(self) -> str:
        """Return the current conversation constraints text.

        Returns:
            The constraint string, or empty string if none are set.
        """
        return self._conversation_constraints

    def list_saved_conversations(self) -> list[Conversation]:
        """Retrieve all saved conversations for the current user.

        Returns:
            List of Conversation objects, or empty list if memory is not initialized.
        """
        if self.memory is None:
            return []
        return self.memory.list_user_conversations()

    def message_records_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch message records for a specific conversation with optional pagination.

        Args:
            conversation_id: UUID of the target conversation.
            limit: Maximum number of records to return; None for all.
            offset: Number of records to skip from the beginning.

        Returns:
            List of message record dicts, or empty list if memory is not initialized.
        """
        if self.memory is None:
            return []
        return self.memory.get_message_records(
            (conversation_id or "").strip(),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def conversation_awaits_user_clarification(
        memory: Memory | None,
        conversation_id: str,
    ) -> bool:
        """Check whether a conversation is waiting for user clarification before proceeding.

        Args:
            memory: Memory instance to query, or None.
            conversation_id: UUID of the conversation to check.

        Returns:
            True if the conversation is in a state awaiting user input, False otherwise.
        """
        if memory is None:
            return False
        conv_id = (conversation_id or "").strip()
        if not conv_id:
            return False
        records = memory.get_message_records(conv_id)
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
        """检测命令是否匹配危险命令模式，支持前缀和包含两种匹配。

        危险命令检查开关由 config.DANGEROUS_COMMAND_CHECK_ENABLED 控制，
        关闭时直接返回 False，跳过所有匹配逻辑。

        Args:
            command: 待检测的命令字符串。

        Returns:
            True 表示命令匹配危险模式，应触发用户确认；False 表示安全。
        """
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
        """检测命令是否为文件写入操作，用于写入确认拦截。

        通过匹配重定向符号和写入类命令关键字来判断。

        Args:
            command: 待检测的命令字符串。

        Returns:
            True 表示命令包含写入操作指示符；False 表示只读或无关操作。
        """
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
        logger.debug("_check_repeated_write_success 被调用")
        logger.debug("  注意：这是写入操作的专用检测，与通用重复检测(_check_repeated_tool_call)协同工作")
        logger.debug(f"  command: {command[:80]}...")

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
                    logger.debug(f"触发写入重复检测: {msg}")
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

        # AI-BRANCH-MARKER: 重复检测分级响应分支 — 第1-2次返回警告，≥3次自动终止，防止工具调用死循环
        max_repeats = config.MAX_CONSECUTIVE_REPEATS
        logger.debug(f"配置信息: 去重启用={config.TOOL_CALL_DEDUPLICATION_ENABLED}, 最大重复次数={max_repeats}, 历史窗口大小={config.REPEAT_DETECTION_WINDOW_SIZE}")

        args_hash = hashlib.md5(json.dumps({"name": tool_name, **args}, sort_keys=True).encode()).hexdigest()

        logger.debug(f"检查工具调用重复: {tool_name}, args_hash={args_hash[:8]}...")
        logger.debug(f"历史记录数: {len(self._recent_tool_calls)}")

        for record in self._recent_tool_calls:
            if record["name"] == tool_name and record["args_hash"] == args_hash:
                self._consecutive_repeat_count += 1
                last_result = record.get("result", "")

                warning_msg = (
                    f"⚠️ 检测到重复的工具调用 [{tool_name}]。"
                    f"该工具已在之前成功执行并返回结果，请直接使用已有结果完成任务，或调用 finish 工具结束对话。\n\n"
                    f"上次执行结果：\n{last_result}"
                )

                logger.debug(f"✓ 发现重复调用: {tool_name}")
                logger.debug(f"连续重复次数: {self._consecutive_repeat_count}")
                logger.debug(f"上次结果长度: {len(last_result)}")

                return (True, warning_msg, last_result)

        self._consecutive_repeat_count = 0
        logger.debug(f"✗ 未发现重复调用: {tool_name}")
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

        logger.debug(f"记录工具调用: {tool_name}, args_hash={args_hash[:8]}, result长度={min(len(result), 500)}, 当前历史数={len(self._recent_tool_calls)}")

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
            if len(content) > config.TOOL_OUTPUT_MAX_LENGTH:
                if config.TOOL_TRUNCATE_SHOW_DETAILS:
                    content = content[:config.TOOL_OUTPUT_MAX_LENGTH] + f"\n\n…（内容已截断：原始长度 {len(content)} 字符，显示 {config.TOOL_OUTPUT_MAX_LENGTH} 字符）"
                else:
                    content = content[:config.TOOL_OUTPUT_MAX_LENGTH] + "\n\n…（内容已截断）"
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
        """从命令文本中提取输出文件路径，支持多种重定向语法。

        支持的语法：-Path 'file'、>> 'file'、> 'file'、>> file、> file。

        Args:
            command: 包含文件路径的命令字符串。

        Returns:
            提取到的文件路径字符串；如果未匹配到任何模式则返回 None。
        """
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

    def _verify_file_exists(self, file_path: str, work_dir: str) -> str:
        """验证文件是否存在于指定路径，返回验证结果消息。

        Args:
            file_path: 相对文件路径。
            work_dir: 当前工作目录，"." 表示使用 self.work_dir。

        Returns:
            包含 ✓ 或 ✗ 的验证结果消息，附带文件大小或不存在说明。
        """
        from pathlib import Path

        if work_dir == ".":
            full_path = Path(self.work_dir) / file_path
        else:
            full_path = Path(self.work_dir) / work_dir / file_path
        
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
        """分发工具调用到控制工具或原子工具执行器。

        控制工具（select_skill、finish、ask_user）走 execute_skill_control_tool，
        其余走 execute_atomic_tool。

        Args:
            name: 工具名称。
            args: 工具调用参数字典。
            active_skill_text: 已加载技能的提示词文本列表。
            active_skill_ids: 已加载技能的 ID 列表。

        Returns:
            (result_text, is_ask_user, ask_user_payload) 三元组：
            - result_text: 工具执行结果文本
            - is_ask_user: 是否触发了 ask_user 等待用户回复
            - ask_user_payload: ask_user 的 JSON 负载，否则为 None
        """
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

    def _consume_pending_user_refs(self, metadata: dict[str, Any]) -> None:
        """把当前轮强制引用元数据合并进持久化 metadata（一次性消费）。

        ext.forced_refs 是占位符的权威背书：历史轮短标记渲染（Message.
        _process_refs）与前端 chip 渲染都以此为校验依据。
        """
        refs = getattr(self, "_pending_user_refs", None)
        if not refs:
            return
        merged = list(metadata.get("forced_refs") or [])
        merged.extend(r for r in refs if r not in merged)
        metadata["forced_refs"] = merged
        self._pending_user_refs = []

    def _build_image_parts_from_refs(self, enable_vision: bool) -> list[dict]:
        """根据图片引用元数据构建多模态 image_url 部分（持久层懒加载）。"""
        if not enable_vision:
            return []
        refs = getattr(self, "_pending_user_refs", None) or []
        image_refs = [r for r in refs if r.get("type") == "file" and r.get("is_image")]
        if not image_refs:
            return []
        parts: list[dict] = []
        try:
            from document_parser.file_storage import get_upload_base64_url
        except Exception as e:  # noqa: BLE001
            logger.warning(f"导入图片加载服务失败: {e}")
            return []
        for r in image_refs:
            try:
                url = get_upload_base64_url(str(r.get("id", "")))
                if url:
                    parts.append({"type": "image_url", "image_url": {"url": url}})
            except Exception as e:  # noqa: BLE001
                logger.warning(f"加载引用图片失败: {r.get('id')} - {e}")
        return parts

    def _append_model_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        system_prompt: str,
        user_query: str,
        enable_vision: bool = True,
        persist_query: Optional[str] = None,
    ) -> None:
        """重建消息列表，拼接系统提示词 + 历史对话 + 当前用户消息。

        从 memory 加载历史消息（过滤 system），清空 messages 后重新拼接，
        并将上传文件内容一次性消费到用户消息中。

        Args:
            messages: 待重建的消息列表（会被清空并重新填充）。
            system_prompt: 系统提示词文本。
            user_query: 当前用户输入文本（发送给 LLM 的版本）。
            enable_vision: 是否启用图片处理，默认 True。
            persist_query: 持久化到 memory 的用户消息文本（回显版本）。
                用于「/」强制引用场景：LLM 收到注入文档后的版本，
                而 memory 保留含 /skill:id 标记的原文供前端渲染引用 chip。
                为 None 时持久化 user_query 本身。

        Side effects:
            清空并重建 messages 列表；消费 _uploaded_files_content 缓存；
            若 memory 存在，将用户消息追加到 memory。
        """
        conversation_id = self._conversation_id
        prior: list[dict[str, Any]] = []
        if self.memory is not None:
            prior = [
                m for m in _history_without_system(self.memory.get_messages(conversation_id))
                # plan_confirm 以 tool 角色持久化，但没有对应的 assistant(tool_calls) 消息，
                # 发送给 LLM 会违反 OpenAI tool calling 协议，因此构建上下文时过滤掉。
                if not (
                    m.get("role") == "tool"
                    and m.get("metadata", {}).get("type") == "plan_confirm"
                )
            ]
        messages.clear()
        messages.append({"role": "system", "content": system_prompt})
        messages.extend(prior)
        # Append message metadata (with files if any)
        metadata = {}
        if hasattr(self, "_last_uploaded_files") and self._last_uploaded_files is not None:
            metadata["files"] = self._last_uploaded_files
            # Clear after using
            self._last_uploaded_files = None
        # 将上传文件内容追加到用户消息（一次性消费，计划确认流程已在 _request_plan_confirmation 中消费）
        user_content = self._consume_uploaded_files_content(
            user_query.strip(),
            enable_vision=enable_vision,
        )
        # 图片强制引用（<File:fid/> 且 mime 为 image/*）：装配多模态 image_url 部分
        _image_parts = self._build_image_parts_from_refs(enable_vision)
        if _image_parts:
            if isinstance(user_content, str):
                user_content = (
                    [{"type": "text", "text": user_content}] if user_content else []
                ) + _image_parts
            elif isinstance(user_content, list):
                user_content = user_content + _image_parts
        if self.memory is not None:
            # 强制引用：memory 保留原始占位符文本（前端渲染 chip），
            # LLM 消息使用注入文档后的 user_content
            persist_content = persist_query.strip() if persist_query is not None else user_content
            # 引用元数据合并进 metadata（一次性消费，含 ext.forced_refs 背书）
            self._consume_pending_user_refs(metadata)
            self.memory.append_message(conversation_id, "user", persist_content, metadata=metadata)
        messages.append({"role": "user", "content": user_content})

    def _persist_after_tool_turn(
        self,
        fname: str,
        args:dict,
        result: str,
        active_skill_text: list[str],
        active_skill_ids: list[str],
        messages: list[dict[str, Any]],
        log_callback: Optional[Callable[[str, str], Any]] = None,
        *,
        tool_call_id: str | None = None,
        reasoning_content: str | None = None,
        content: str | None = None,
        arg_str: str | None = None,
    ) -> None:
        """持久化并追加一轮工具调用的完整消息序列。

        关键修复：同时向 messages 追加 assistant(tool_calls) 与 tool(result) 两条消息，
        并为二者持久化相同的 tool_call_id，使跨轮重建历史时仍能正确关联。
        遵守 OpenAI tool calling 协议：tool 消息前必须有带 tool_calls 的 assistant 消息。
        """
        assert self.memory is not None
        conversation_id = self._conversation_id
        if arg_str is None:
            args_str = json.dumps(args, ensure_ascii=False, indent=2)
        else:
            # 验证 arg_str 是否为有效 JSON，防止非 JSON 字符串导致 API 报错
            try:
                json.loads(arg_str)
                args_str = arg_str
            except (json.JSONDecodeError, TypeError):
                # arg_str 不是有效 JSON，使用 args 重新序列化
                args_str = json.dumps(args, ensure_ascii=False, indent=2)
        if tool_call_id is None:
            tool_call_id = f"call_{uuid.uuid4().hex[:12]}"

        # 1) 持久化 assistant 工具调用消息（带 tool_calls 元数据，供 get_messages 还原）
        # content 优先：模型在调用工具前输出的说明文本需要保留到历史中
        assistant_content = content or reasoning_content or None
        assistant_metadata: dict[str, Any] = {
            "type": "tool_call",
            "name": fname,
            "args": args_str,
            "tool_call_id": tool_call_id,
        }
        if reasoning_content:
            assistant_metadata["reasoning_content"] = reasoning_content
        self.memory.append_message(
            conversation_id,
            "assistant",
            content or reasoning_content or "",
            metadata=assistant_metadata,
        )

        # 2) 追加 assistant tool_call 到 messages（OpenAI 协议必需）
        # 确保 arguments 是有效的 JSON 字符串
        valid_args = args_str if args_str else "{}"
        try:
            json.loads(valid_args)
        except (json.JSONDecodeError, TypeError):
            valid_args = "{}"
        messages.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": fname, "arguments": valid_args},
            }],
        })

        # 3) 持久化 tool 结果消息
        if fname == "select_skill":
            meta_type = "skill"
        elif fname == "ask_user":
            meta_type = "ask_user"
        else:
            meta_type = "base_tool"
        self.memory.append_message(
            conversation_id,
            "tool",
            str(result),
            metadata={"type": meta_type, "name": fname, "args": args_str, "tool_call_id": tool_call_id},
        )

        # 4) 追加 tool 结果到 messages（带 tool_call_id 关联）
        messages.append({
            "role": "tool",
            "name": fname,
            "tool_call_id": tool_call_id,
            "content": str(result),
        })

        if fname == "select_skill" and active_skill_text and not str(result).startswith("错误"):
            self.memory.set_active_skills(conversation_id, list(active_skill_ids))
            active_skills_text = self._build_active_skills_text(active_skill_text, active_skill_ids)
            self._dynamic_prompt.update_active_skills(active_skills_text)
            for i, msg in enumerate(messages):
                if msg.get("role") == "system":
                    messages[i] = {"role": "system", "content": self._dynamic_prompt.build()}
                    logger.debug("更新系统提示词_dynamic_prompt：%s", self._dynamic_prompt.build())
                    break

    def _append_tool_pair(
        self,
        fname: str,
        args: dict | str,
        result: str,
        messages: list[dict[str, Any]],
        *,
        reasoning_content: str | None = None,
        tool_call_id: str | None = None,
    ) -> str:
        """向 messages 追加 assistant(tool_calls)+tool(result) 完整序列（不持久化）。

        用于不进入 LLM 循环的「用户确认后立即执行」等特殊路径，避免出现孤立 tool 消息。
        返回生成的 tool_call_id。
        """
        if tool_call_id is None:
            tool_call_id = f"call_{uuid.uuid4().hex[:12]}"
        arg_str = _ensure_valid_json_args(args)
        messages.append({
            "role": "assistant",
            "content": reasoning_content or None,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": fname, "arguments": arg_str},
            }],
        })
        messages.append({
            "role": "tool",
            "name": fname,
            "tool_call_id": tool_call_id,
            "content": str(result),
        })
        return tool_call_id

    def _persist_tool_pair_only(
        self,
        fname: str,
        args: dict | str,
        result: str,
        messages: list[dict[str, Any]],
        *,
        meta_type: str = "base_tool",
        tool_call_id: str | None = None,
        reasoning_content: str | None = None,
    ) -> str:
        """持久化并追加 assistant(tool_calls)+tool(result) 序列，但不动 active skills。

        专用于 ask_user 历史恢复等特殊路径，避免重复触发 select_skill 逻辑。
        """
        assert self.memory is not None
        conversation_id = self._conversation_id
        if isinstance(args, str):
            arg_str = args
        else:
            arg_str = json.dumps(args, ensure_ascii=False, indent=2)
        if tool_call_id is None:
            tool_call_id = f"call_{uuid.uuid4().hex[:12]}"

        assistant_metadata: dict[str, Any] = {
            "type": "tool_call",
            "name": fname,
            "args": arg_str,
            "tool_call_id": tool_call_id,
        }
        if reasoning_content:
            assistant_metadata["reasoning_content"] = reasoning_content
        self.memory.append_message(
            conversation_id,
            "assistant",
            reasoning_content or "",
            metadata=assistant_metadata,
        )
        self.memory.append_message(
            conversation_id,
            "tool",
            str(result),
            metadata={"type": meta_type, "name": fname, "args": arg_str, "tool_call_id": tool_call_id},
        )
        self._append_tool_pair(
            fname,
            arg_str,
            result,
            messages,
            reasoning_content=reasoning_content,
            tool_call_id=tool_call_id,
        )
        return tool_call_id


    def _append_tool_result_to_messages(
        self,
        fname: str,
        args: dict,
        result_str: str,
        full_thinking: str | None,
        arg_str: str,
        messages: list[dict],
        active_skill_text: list[str],
        active_skill_ids: list[str],
        log_callback: Optional[Callable[[str, str], Any]] = None,
        content_parts: list[str] | None = None,
    ) -> None:
        """将工具调用结果持久化到 messages 列表和 memory。

        统一处理 memory 和非 memory 两种分支，消除 run() 中的重复代码。

        Business purpose:
            工具调用结果的持久化逻辑只在一处维护，避免两处代码不一致。

        Parameters:
            fname: 工具名称
            args: 工具参数字典
            result_str: 工具执行结果字符串
            full_thinking: LLM 思考过程内容（可选）
            arg_str: 工具参数 JSON 字符串
            messages: 消息列表（会被修改）
            active_skill_text: 活跃 Skill 文本列表
            active_skill_ids: 活跃 Skill ID 列表
            log_callback: 前端回调
            content_parts: 本轮 LLM 在工具调用前输出的文本片段列表

        Side effects:
            修改 messages 列表（追加 assistant + tool 消息）
            当 memory 存在时，通过 _persist_after_tool_turn 持久化
            当 fname == "select_skill" 时，更新动态系统提示词

        Modification notes:
            2026-07-29: 从 run() 主循环中两处重复逻辑提取合并

        Related tests:
            tests/test_skill_agent.py (待补充)
        """
        assistant_content = "".join(content_parts) if content_parts else None
        if self.memory is not None:
            self._persist_after_tool_turn(
                fname,
                args,
                result_str,
                active_skill_text,
                active_skill_ids,
                messages,
                log_callback,
                reasoning_content=full_thinking or None,
                content=assistant_content,
                arg_str=arg_str,
            )
        else:
            _call_id = f"call_{uuid.uuid4().hex[:12]}"
            messages.append({
                "role": "assistant",
                "content": assistant_content or full_thinking or None,
                "tool_calls": [{
                    "id": _call_id,
                    "type": "function",
                    "function": {"name": fname, "arguments": _ensure_valid_json_args(arg_str)},
                }],
            })
            messages.append({
                "role": "tool",
                "name": fname,
                "tool_call_id": _call_id,
                "content": str(result_str),
            })

    def _handle_text_result(
        self,
        result: StreamResult,
        full_thinking: str,
        content_parts: list[str],
        messages: list[dict],
        has_called_tool_in_run: bool,
        log_callback: Optional[Callable[[str, str], Any]],
        emit_token_usage: Callable[[], None],
    ) -> tuple[str, str | None]:
        """处理 LLM 返回的文本/截断结果。

        Business purpose:
            统一处理文本响应、截断响应和自动 finish 逻辑。

        Parameters:
            result: LLM 流式结果
            full_thinking: 思考过程全文
            content_parts: 内容分片列表
            messages: 消息列表
            has_called_tool_in_run: 本轮是否调用过工具
            log_callback: 前端回调
            emit_token_usage: token 使用量发射函数

        Returns:
            (action, value) 元组:
            - ("return", 返回值): 应立即返回
            - ("continue", None): 应继续主循环
            - ("none", None): 不处理（不应到达此分支）

        Side effects:
            可能修改 messages 和 memory

        Modification notes:
            2026-07-29: 从 run() 主循环中提取

        Related tests:
            tests/test_skill_agent.py (待补充)
        """
        is_truncated = result.result_type == "truncated"
        final_text = result.content or ""
        if not final_text:
            final_text = "".join(content_parts).strip()

        if full_thinking and self.memory is not None:
            self.memory.append_message(
                self._conversation_id,
                "assistant",
                full_thinking,
                metadata={"type": "think"},
            )

        if not final_text:
            thinking_preview = (full_thinking or "")[:200]
            logger.warning(
                "[SkillAgent] final_text 为空，模型未返回内容。"
                "thinking 前 200 字: %r", thinking_preview,
            )
            err = "模型未返回内容，无法继续。"
            if log_callback:
                log_callback(err, "assistant")
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", err, metadata=metadata)
            emit_token_usage()
            return ("return", err)

        # AI-BRANCH-MARKER: 自动finish分支 — 已调用工具后的文本输出自动包装为finish返回，避免LLM在工具调用后输出无意义文本
        # 自动 finish：如果已调用工具，自动包装文本为 finish 调用
        if has_called_tool_in_run:
            logger.info("检测到工具调用后的文本输出，自动包装为finish工具调用")
            logger.debug(f"文本长度: {len(final_text)}, 工具调用历史: {len(self._recent_tool_calls)}")
            if log_callback:
                log_callback(final_text, "assistant")
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", final_text, metadata=metadata)
            emit_token_usage()
            return ("return", final_text)

        # 推理文本检测：依赖 enable_thinking 机制和 result_type 判断
        # 当 enable_thinking 启用时，thinking 内容已通过 thinking_parts 单独收集
        # 此处仅对截断响应做特殊处理（继续循环让 LLM 完成）
        if is_truncated:
            logger.debug("检测到推理文本或被截断的响应 (长度: %s, truncated: %s)",
                         len(final_text), is_truncated)
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", final_text, metadata=metadata)
            return ("continue", None)
        else:
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", final_text, metadata=metadata)
            emit_token_usage()
            logger.debug("返回文本内容 (长度: %s)", len(final_text))
            return ("return", final_text)

    def _classify_and_prepare_context(
        self,
        user_query: str,
        log_callback: Optional[Callable[[str, str], Any]],
        emit_token_usage: Callable[[], None],
        persist_query: Optional[str] = None,
    ) -> dict:
        """输入分类与主循环上下文准备。

        处理计划确认续跑、输入分类、复杂任务计划生成、模型/工具/消息初始化。

        Returns:
            dict: 包含 action 键的结果字典：
                - {"action": "return", "value": str}: 应立即返回
                - {"action": "continue", "model": ..., "tools": ..., "messages": ...,
                   "active_skill_text": ..., "active_skill_ids": ...}: 继续主循环
        """
        # AI-BRANCH-MARKER: 计划续跑分支 — 计划确认后续跑时跳过输入分类，直接进入工具循环
        # 计划确认续跑检测：若上一轮在等待用户确认计划，根据用户选择决定走向
        plan_resume = self._check_plan_confirmation_resume(user_query)
        if plan_resume == "cancel":
            cancel_msg = "已取消任务执行。"
            if log_callback:
                log_callback(cancel_msg, "assistant")
            if self.memory is not None:
                self.memory.append_message(self._conversation_id, "user", user_query.strip())
                self.memory.append_message(
                    self._conversation_id, "assistant", cancel_msg,
                    metadata={"token_usage": asdict(self._token_usage)},
                )
            emit_token_usage()
            return {"action": "return", "value": cancel_msg}
        if plan_resume == "replan":
            replan_msg = "好的，请重新描述您的需求或补充说明，我将重新制定执行计划。"
            if log_callback:
                log_callback(replan_msg, "assistant")
            if self.memory is not None:
                self.memory.append_message(self._conversation_id, "user", user_query.strip())
                self.memory.append_message(
                    self._conversation_id, "assistant", replan_msg,
                    metadata={"token_usage": asdict(self._token_usage)},
                )
            emit_token_usage()
            return {"action": "return", "value": replan_msg}

        # 输入分类：判断是否需要规划
        if plan_resume == "execute":
            plan_mode = PlanMode.COMPLEX_TASK
            logger.debug("计划确认续跑，跳过分类，直接进入复杂任务执行")
        else:
            plan_mode = self._classify_input(user_query)
        logger.debug("输入分类: %s", plan_mode.value)

        if log_callback:
            mode_labels = {
                PlanMode.NO_PLAN: "💬 闲聊/问答模式（无需规划，直接回复）",
                PlanMode.SIMPLE_TASK: "⚡ 简单任务模式（单步工具调用）",
                PlanMode.COMPLEX_TASK: "📋 复杂任务模式（结构化规划+分步执行）",
            }
            log_callback(mode_labels.get(plan_mode, plan_mode.value), "mode")

        if plan_mode == PlanMode.NO_PLAN:
            logger.debug("无需规划模式，直接回复")
            return {"action": "return", "value": self._direct_reply(user_query, log_callback)}

        # 复杂任务：注入执行约束
        if plan_mode == PlanMode.COMPLEX_TASK:
            if self._plan_confirmed:
                plan_constraints = self._build_plan_constraints()
                existing_constraints = self._conversation_constraints
                if existing_constraints:
                    self._conversation_constraints = existing_constraints + plan_constraints
                else:
                    self._conversation_constraints = plan_constraints.lstrip()
            else:
                planning_instruction = """

【复杂任务执行要求 - 强制执行】
1. 你必须在执行任何工具调用前，先在思考过程中制定完整的执行计划
2. 计划必须包含：具体步骤列表、每步使用的工具、期望结果、验证方式
3. 每执行完一个步骤，必须对照计划检查是否达到预期结果
4. 如果某步骤失败，请分析原因并调整后续计划
5. 所有步骤完成后，必须对照计划的 success_criteria 逐项确认任务是否成功
6. 只有确认所有步骤完成后，才能调用 finish 结束任务"""
                existing_constraints = self._conversation_constraints
                if existing_constraints:
                    self._conversation_constraints = existing_constraints + planning_instruction
                else:
                    self._conversation_constraints = planning_instruction.lstrip()

        model = get_chat_model(enable_thinking=self._enable_thinking)
        conv_type = self._get_conversation_type()
        skills_visible = self._get_skills_for_conversation_type(conv_type)
        catalog = build_skills_catalog_text(skills_visible)
        tool_catalog = model.build_tool_catalog()
        tool_catalog_text = self._build_tool_catalog_text(tool_catalog)
        system_prompt = self._build_dynamic_system_prompt(catalog, user_query=user_query, tool_catalog=tool_catalog_text)
        logger.debug("初始系统提示词：%s", system_prompt)

        # 复杂任务：制定结构化执行计划并请求用户确认
        if plan_mode == PlanMode.COMPLEX_TASK:
            early_return = self._handle_complex_task_planning(
                user_query, tool_catalog_text, log_callback, model.enable_vision,
                persist_query=persist_query,
            )
            if early_return is not None:
                # 用户原始 query 的持久化统一由下方 _append_model_messages 处理，
                # 避免在提前返回分支中重复追加。
                return {"action": "return", "value": early_return}

        tools = model.build_skill_agent_tools_initial()
        self._supplied_tool_definitions: dict[str, dict] = {}
        logger.debug("===== 目录+补发 渐进披露机制初始化 =====")
        logger.debug("工具目录已构建，包含 %s 个工具的简要描述", len(tool_catalog))
        logger.debug("初始工具集已准备，包含 request_tool_details + CONTROL 工具")
        logger.debug("原子工具将按需通过 request_tool_details 获取")

        messages: list[dict[str, Any]] = []
        self._append_model_messages(
            messages,
            system_prompt=system_prompt,
            user_query=user_query,
            enable_vision=model.enable_vision,
            persist_query=persist_query,
        )
        active_skill_text, active_skill_ids = self._recover_active_skills()

        return {
            "action": "continue",
            "model": model,
            "tools": tools,
            "messages": messages,
            "active_skill_text": active_skill_text,
            "active_skill_ids": active_skill_ids,
        }

    def _handle_complex_task_planning(
        self,
        user_query: str,
        tool_catalog_text: str,
        log_callback: Optional[Callable[[str, str], Any]],
        enable_vision: bool,
        persist_query: Optional[str] = None,
    ) -> Optional[str]:
        """处理复杂任务的计划生成与确认流程。

        Returns:
            若需要提前返回（如等待用户确认计划），返回应返回的值；
            若 None，表示继续执行。
        """
        if self._plan_confirmed:
            # 续跑：计划已确认，展示已有计划后直接进入执行
            if log_callback and self._pending_plan:
                plan_display = self._format_plan_display({
                    "analysis": self._pending_plan_analysis,
                    "plan": self._pending_plan,
                    "total_steps": len(self._pending_plan),
                    "success_criteria": self._pending_success_criteria,
                })
                log_callback("✅ 计划已确认，开始按计划执行：\n\n" + plan_display, "plan")
            return None

        # 首次：生成计划
        plan_data = self._plan_steps(user_query, tool_catalog_text, log_callback)
        if plan_data is None:
            return None

        # 启用确认环节：请求用户确认后再执行
        if config.PLAN_CONFIRMATION_ENABLED:
            return self._request_plan_confirmation(
                user_query,
                plan_data,
                log_callback,
                enable_vision=enable_vision,
                persist_query=persist_query,
            )

        # 未启用确认环节：展示计划后直接执行（保持原有行为）
        plan_display = self._format_plan_display(plan_data)
        if log_callback:
            log_callback(plan_display, "plan")
        if self.memory is not None:
            self.memory.append_message(
                self._conversation_id,
                plan_display,
                metadata={"type": "plan"},
            )
        return None



    def _recover_active_skills(self):
        """从数据库恢复已保存的 active skills，若无则加载默认技能。

        Returns:
            tuple[list[str], list[str]]: (active_skill_text, active_skill_ids)
        """
        active_skill_text: list[str] = []
        active_skill_ids: list[str] = []

        if self.memory is None:
            return active_skill_text, active_skill_ids

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
                logger.debug("恢复 active skills: %s", active_skill_ids)
        else:
            # 如果没有保存的 active skills，从全局配置动态读取该会话类型的默认技能
            conv = self.memory.get_conversation(self._conversation_id)
            if conv:
                from skill_agent_preferences import get_default_skills_for_type
                conv_type = conv.type or 'agent_conversation'
                skill_ids = get_default_skills_for_type(conv_type)
                for sid in skill_ids:
                    skill = self.registry.get(sid)
                    if skill:
                        formatted_skill = format_skill_for_prompt(skill)
                        active_skill_text.append(formatted_skill)
                        active_skill_ids.append(sid)
                # 将默认技能保存到 active_skill_ids 中
                if active_skill_ids:
                    self.memory.set_active_skills(self._conversation_id, active_skill_ids)
                    active_skills_section = self._build_active_skills_text(active_skill_text, active_skill_ids)
                    self._dynamic_prompt.update_active_skills(active_skills_section)
                    logger.debug("加载默认技能: %s", active_skill_ids)

        return active_skill_text, active_skill_ids

    def _reset_runtime_confirm_state(self):
        """重置运行时确认相关状态。"""
        self._runtime_confirm_pending = False
        self._runtime_confirm_fname = ""
        self._runtime_confirm_args = {}
        self._runtime_confirm_messages = []

    def _handle_runtime_confirmation(self, user_query, log_callback, emit_token_usage_fn):
        """Handle pending runtime confirmation from previous turn.

        When a previous turn triggered a runtime confirmation (dangerous command,
        package install, etc.), this method processes the user's response without
        sending it to the LLM.

        Args:
            user_query: The user's response (e.g. "确认执行", "确认安装", "取消", or other input)
            log_callback: Frontend logging callback
            emit_token_usage_fn: Callable to emit token usage to frontend

        Returns:
            dict: Result dict with key "action" indicating what the caller should do:
                - {"action": "no_pending"}: No pending confirmation, proceed normally
                - {"action": "skip_to_main_loop", "messages": ..., "active_skill_text": ...,
                   "active_skill_ids": ..., "model": ..., "tools": ...}:
                   User confirmed, skip to main loop with pre-configured context
                - {"action": "return", "value": "操作已取消"}: User cancelled, return early
                - {"action": "clear"}: User entered other content, clear state and proceed normally
        """
        # AI-BRANCH-MARKER: 运行时确认状态分支 — _runtime_confirm_pending控制是否进入确认处理流程
        if not self._runtime_confirm_pending:
            return {"action": "no_pending"}

        logger.debug("检测到运行时拦截确认待处理，用户回复: %s", user_query[:50])
        user_choice = user_query.strip()

        if user_choice in ("确认执行", "确认安装"):
            # 用户确认：直接执行命令
            fname = self._runtime_confirm_fname
            args = self._runtime_confirm_args
            messages_snapshot = self._runtime_confirm_messages

            logger.debug("运行时确认：用户确认，执行命令 %s", fname)
            result, terminate, final = self._dispatch(fname, args, [], [])

            # 追加工具结果到消息列表（持久化 + 追加到 messages）
            if self.memory is not None:
                self._persist_after_tool_turn(
                    fname, args, str(result), [], [], messages_snapshot, log_callback
                )

            # 重置运行时确认状态
            self._reset_runtime_confirm_state()

            # 设置标志：跳过后续输入分类，直接进入主循环
            self._from_runtime_confirm_continue = True

            # 将工具执行结果发给前端展示
            if log_callback:
                log_callback(str(result), "base_tool")

            # 不再直接 return，而是继续进入主循环让 LLM 解读结果并决定下一步
            logger.debug("运行时确认执行完成，继续进入主循环让 LLM 推理")
            # 注意：messages_snapshot 就是后面主循环使用的 messages 列表
            # 因为 _persist_after_tool_turn 已经追加了 assistant(tool_calls)+tool 序列
            # 所以主循环可以直接使用它继续推理
            messages = messages_snapshot
            active_skill_text, active_skill_ids = self._recover_active_skills()

            # 初始化主循环所需的工具和模型相关变量
            model = get_chat_model(enable_thinking=self._enable_thinking)
            tools = model.build_skill_agent_tools_initial()
            self._supplied_tool_definitions = {}

            return {
                "action": "skip_to_main_loop",
                "messages": messages,
                "active_skill_text": active_skill_text,
                "active_skill_ids": active_skill_ids,
                "model": model,
                "tools": tools,
            }

        if user_choice == "取消":
            # 用户取消：返回取消消息
            cancel_msg = "操作已取消"
            if log_callback:
                log_callback(cancel_msg, "assistant")

            # 重置运行时确认状态
            self._reset_runtime_confirm_state()

            emit_token_usage_fn()
            return {"action": "return", "value": cancel_msg}

        # 用户输入了其他内容，视为新的对话输入，清除运行时确认状态
        logger.debug("用户输入了其他内容，清除运行时确认状态")
        self._reset_runtime_confirm_state()
        return {"action": "clear"}

    def _handle_ask_user_resume(self, user_query, log_callback, emit_token_usage_fn):
        """处理上一轮 ask_user 等待后的用户回复，继续主循环推理。

        与 _handle_runtime_confirmation（危险命令/包安装确认）不同，
        ask_user 由 LLM 工具调用触发，用户回复即为对该问题的回答。
        将用户回复作为 user 消息注入到 ask_user 触发时的消息快照之后，
        让 LLM 基于完整上下文（含 ask_user 的 tool 结果 + 用户回答）继续推理，
        而不是把回复当作全新对话输入重新分类/规划/再次询问。

        Args:
            user_query: 用户对 ask_user 的回复。
            log_callback: 前端日志回调。
            emit_token_usage_fn: 发送 token 用量回调。

        Returns:
            dict: 与 _handle_runtime_confirmation 同构的结果字典：
                - {"action": "no_pending"}: 无待恢复的 ask_user，正常流程
                - {"action": "skip_to_main_loop", "messages": ..., "model": ...,
                   "tools": ..., "active_skill_text": ..., "active_skill_ids": ...}:
                   用户已回答，注入回复后直接进入主循环继续推理
        """
        if not self._ask_user_confirm_pending:
            return {"action": "no_pending"}

        logger.debug("检测到 ask_user 待恢复，用户回复: %s", user_query[:50])
        messages = self._ask_user_confirm_messages
        user_content = user_query.strip()
        # 用户回答作为 user 消息注入，LLM 结合 ask_user 的 tool 结果理解回答并继续推进
        messages.append({"role": "user", "content": user_content})
        if self.memory is not None:
            self.memory.append_message(self._conversation_id, "user", user_content)

        # 重置待恢复状态
        self._ask_user_confirm_pending = False
        self._ask_user_confirm_messages = []

        # 初始化主循环所需的工具和模型（与 skip_to_main_loop 分支保持一致）
        model = get_chat_model(enable_thinking=self._enable_thinking)
        tools = model.build_skill_agent_tools_initial()
        self._supplied_tool_definitions = {}
        active_skill_text, active_skill_ids = self._recover_active_skills()

        return {
            "action": "skip_to_main_loop",
            "messages": messages,
            "active_skill_text": active_skill_text,
            "active_skill_ids": active_skill_ids,
            "model": model,
            "tools": tools,
        }

    def _format_and_send_tool_result(self, fname, args, result, log_callback, emit_token_usage_fn):
        """Format tool execution result and send to frontend via log_callback.

        Handles result truncation, run_command special formatting (command prefix,
        write operation verification), and repeated write detection.

        Args:
            fname: Tool function name
            args: Tool arguments dict
            result: Tool execution result (may be modified for run_command)
            log_callback: Frontend logging callback
            emit_token_usage_fn: Callable to emit token usage to frontend

        Returns:
            tuple: (result, early_return_value) where result may be modified
                   for run_command formatting, and early_return_value is a string
                   if repeated write was detected (caller should return this value),
                   or None otherwise.
        """
        try:
            r = str(result)
            if len(r) > config.TOOL_OUTPUT_MAX_LENGTH:
                if config.TOOL_TRUNCATE_SHOW_DETAILS:
                    r = r[:config.TOOL_OUTPUT_MAX_LENGTH] + f"\n\n…（内容已截断：原始长度 {len(r)} 字符，显示 {config.TOOL_OUTPUT_MAX_LENGTH} 字符）"
                else:
                    r = r[:config.TOOL_OUTPUT_MAX_LENGTH] + "\n\n…（内容已截断）"
            if fname == "run_command":
                command = str(args.get("command", "") or "").strip()

                if "exit_code: 0" in r:
                    stdout_match = r.split("--- stdout ---")
                    stdout = ""
                    if len(stdout_match) >= 2:
                        stdout = stdout_match[1].split("--- stderr ---")[0].strip()

                    if not stdout and self._is_write_operation(command):
                        logger.debug("检测到写入操作: %s...", command[:80])
                        file_path = self._extract_file_path(command)
                        if file_path:
                            logger.debug("提取到文件路径: %s", file_path)
                            check_result = self._verify_file_exists(file_path, args.get("cwd", "."))
                            # 将命令信息和检查结果合并到结果中，一次性发送
                            r = f"执行命令: {command}\n\n{r}\n\n{check_result}"
                            result = r
                            logger.debug("验证结果已合并到工具结果")
                        else:
                            logger.debug("无法提取文件路径，跳过验证")
                            r = f"执行命令: {command}\n\n{r}"
                    else:
                        r = f"执行命令: {command}\n\n{r}"
                else:
                    r = f"执行命令: {command}\n\n{r}"

                # 写入操作特例检测（保留原有逻辑）
                # 此检测与通用重复检测协同工作，专门针对写入操作提供更严格的保护
                auto_end_msg = self._check_repeated_write_success(command, str(result))
                if auto_end_msg:
                    logger.debug(f"检测到重复写入，自动结束: {auto_end_msg}")
                    # 补发 TURN_START：自动结束文案作为独立卡片渲染，与持久化（独立 assistant 消息）一致
                    self._emit_event(AgentEventType.TURN_START, token_usage=self._token_usage.total_tokens)
                    if log_callback:
                        try:
                            log_callback(auto_end_msg, "assistant")
                        except Exception as e:
                            logger.warning("log_callback 调用失败: %s", e)
                    metadata = {"token_usage": asdict(self._token_usage)}
                    if self.memory is not None:
                        self.memory.append_message(self._conversation_id, "assistant", auto_end_msg, metadata=metadata)
                    emit_token_usage_fn()
                    return (result, auto_end_msg)
            if log_callback:
                try:
                    log_callback(r, "base_tool")
                except Exception as e:
                    logger.warning("log_callback 调用失败: %s", e)
            return (result, None)
        except Exception as e:
            logger.exception("_format_and_send_tool_result 异常: %s", e)
            return (result, None)

    def _handle_run_command_confirmation(self, fname, args, log_callback, emit_token_usage_fn, messages):
        """Check if run_command needs user confirmation before execution.

        Handles three confirmation scenarios:
        1. Skill dependency installation - when a skill requires packages to be installed
        2. Package install command - when the command itself installs packages
        3. Dangerous command - when the command may modify or delete files

        Args:
            fname: Tool function name (should be "run_command")
            args: Tool arguments dict containing "command" and optionally "skill_id"
            log_callback: Frontend logging callback
            emit_token_usage_fn: Callable to emit token usage to frontend
            messages: Conversation messages list (used for snapshot on confirmation)

        Returns:
            tuple or None: (action, value) where action is "return" and value is the
                           return value for run(), or None if no confirmation is needed
                           and tool execution should proceed.
        """
        # AI-BRANCH-MARKER: 命令确认三路分支 — 用户可确认执行、修改或取消，不同选择走不同执行路径
        command = str(args.get("command", "") or "").strip()
        skill_id = args.get("skill_id", "")

        # 检查是否已通过历史记录确认（旧方案保留，用于兼容）
        skip_ask_user = self._tool_ctx.should_skip_ask_user_for_run_command()
        if skip_ask_user:
            logger.debug("跳过二次确认：命令已通过历史记录确认")

        # 新方案：运行时拦截确认（用户确认不发往 LLM）
        if skill_id:
            need_install, packages_to_install, err_msg = check_skill_dependencies(
                str(skill_id), self.registry
            )
            if err_msg:
                emit_token_usage_fn()
                return ("return", f"错误: {err_msg}")

            if need_install and packages_to_install and not skip_ask_user:
                packages_str = ", ".join(packages_to_install)
                ask_args = {
                    "question": f"Skill「{skill_id}」需要安装以下依赖包：\n\n{packages_str}\n\n是否确认安装？",
                    "choices": ["确认安装", "取消"]
                }
                # 保存待执行命令信息
                self._runtime_confirm_pending = True
                self._runtime_confirm_fname = fname
                self._runtime_confirm_args = args
                self._runtime_confirm_messages = list(messages)  # 快照
                # 触发确认 UI（不保存到历史，不发给 LLM）
                if log_callback:
                    log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
                emit_token_usage_fn()
                return ("return", SKILL_AGENT_AWAITING_USER_REPLY)

        is_pkg_install, packages = self._is_package_install_command(command)
        if is_pkg_install and not skip_ask_user:
            packages_str = ", ".join(packages) if packages else "（未解析到包名）"
            ask_args = {
                "question": f"即将安装以下包：\n\n{packages_str}\n\n命令：{command}\n\n是否确认执行？",
                "choices": ["确认安装", "取消"]
            }
            # 保存待执行命令信息
            self._runtime_confirm_pending = True
            self._runtime_confirm_fname = fname
            self._runtime_confirm_args = args
            self._runtime_confirm_messages = list(messages)  # 快照
            # 触发确认 UI（不保存到历史，不发给 LLM）
            if log_callback:
                log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
            emit_token_usage_fn()
            return ("return", SKILL_AGENT_AWAITING_USER_REPLY)

        if self._is_dangerous_command(command) and not skip_ask_user:
            ask_args = {
                "question": f"即将执行以下命令，可能会修改或删除文件：\n\n{command}\n\n是否确认执行？",
                "choices": ["确认执行", "取消"]
            }
            # 保存待执行命令信息
            self._runtime_confirm_pending = True
            self._runtime_confirm_fname = fname
            self._runtime_confirm_args = args
            self._runtime_confirm_messages = list(messages)  # 快照
            # 触发确认 UI（不保存到历史，不发给 LLM）
            if log_callback:
                log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
            emit_token_usage_fn()
            return ("return", SKILL_AGENT_AWAITING_USER_REPLY)

        return None

    def _handle_install_confirmation(self, fname, args, log_callback, emit_token_usage_fn, messages):
        """安装类工具（install_skill_from_zip / install_cli_package）的运行时确认拦截。

        安装会向用户数据目录写入文件，落盘前必须经用户确认。
        复用运行时确认机制：用户回复「确认安装」后由
        _handle_runtime_confirmation 直接重新分发工具调用。

        Args:
            fname: 工具名（install_skill_from_zip 或 install_cli_package）
            args: 工具参数字典，含 zip_path
            log_callback: 前端日志回调
            emit_token_usage_fn: 发送 token 用量回调
            messages: 对话消息列表（确认时做快照）

        Returns:
            tuple 或 None: (action, value)，action="return" 时应立即返回；
                           None 表示无安装意图（如缺少 zip_path），继续正常执行。
        """
        zip_path = str(args.get("zip_path", "") or "").strip()
        if not zip_path:
            # 参数缺失时交给 handler 返回错误，不触发确认
            return None

        pkg_kind = "Skill 包" if fname == "install_skill_from_zip" else "CLI 包"
        overwrite = str(args.get("overwrite", "false")).strip().lower() in ("true", "1", "yes")
        overwrite_hint = "（将覆盖已存在的同名包）" if overwrite else ""

        ask_args = {
            "question": (
                f"即将安装{pkg_kind}：\n\n{zip_path}\n\n"
                f"该操作会向用户数据目录写入文件{overwrite_hint}。是否确认安装？"
            ),
            "choices": ["确认安装", "取消"]
        }
        # 保存待执行工具信息，等用户确认后由 _handle_runtime_confirmation 重新分发
        self._runtime_confirm_pending = True
        self._runtime_confirm_fname = fname
        self._runtime_confirm_args = args
        self._runtime_confirm_messages = list(messages)  # 快照
        # 触发确认 UI（不保存到历史，不发给 LLM）
        if log_callback:
            log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
        emit_token_usage_fn()
        return ("return", SKILL_AGENT_AWAITING_USER_REPLY)

    def _handle_request_tool_details_step(self, fname, args, model, tools, full_thinking, arg_str, messages, active_skill_text, active_skill_ids, log_callback, content_parts=None):
        """Handle request_tool_details: progressive disclosure of tool definitions.

        When LLM requests full tool definitions via request_tool_details, this method:
        1. Looks up requested tool definitions from the model
        2. Caches found definitions in _supplied_tool_definitions
        3. Dynamically adds missing tool schemas to the tools list
        4. Persists the tool result to messages and memory
        5. Sends the result to the frontend via log_callback

        Args:
            fname: Tool function name (should be "request_tool_details")
            args: Tool arguments dict containing "tool_names" list
            model: Chat model instance for tool definition lookup
            tools: List of tool schemas (mutable - may be appended with new tools)
            full_thinking: Thinking content string from LLM
            arg_str: Raw JSON arguments string
            messages: Conversation messages list
            active_skill_text: List of active skill text blocks
            active_skill_ids: List of active skill IDs
            log_callback: Frontend logging callback

        Returns:
            bool: True, indicating the caller should continue the loop
        """
        tool_names = args.get("tool_names", [])
        if not isinstance(tool_names, list):
            tool_names = [str(tool_names)]

        logger.debug("request_tool_details: 请求工具定义 %s", tool_names)
        logger.debug("===== 目录+补发 渐进披露机制 - 补发阶段 =====")
        logger.debug("LLM 请求获取工具的完整定义: %s", tool_names)

        definitions_found = []
        definitions_missing = []

        for tool_name in tool_names:
            tool_def = model.get_tool_full_definition(tool_name)
            if tool_def:
                definitions_found.append(tool_def)
                self._supplied_tool_definitions[tool_name] = tool_def
                logger.debug("  ✓ 找到工具定义: %s", tool_name)
                logger.debug("  工具定义已缓存到 _supplied_tool_definitions")
            else:
                definitions_missing.append(tool_name)
                logger.debug("  ✗ 未找到工具定义: %s", tool_name)

        result_parts = []
        if definitions_found:
            result_parts.append("以下工具的完整定义已获取：\n")
            for def_item in definitions_found:
                def_json = json.dumps(def_item, ensure_ascii=False, indent=2)
                result_parts.append(f"### {def_item.get('name', 'unknown')}\n```json\n{def_json}\n```\n")

        if definitions_missing:
            result_parts.append(f"\n⚠️ 以下工具未找到定义：{', '.join(definitions_missing)}")

        tool_result = "\n".join(result_parts)

        for tool_name, tool_def in self._supplied_tool_definitions.items():
            tool_schema = model.format_tool_for_request(tool_def)
            already_in_tools = any(
                model.get_tool_name_from_formatted(t) == tool_name
                for t in tools
            )
            if not already_in_tools:
                tools.append(tool_schema)
                logger.debug("添加工具到 tools 列表: %s", tool_name)
                logger.debug("  工具 [%s] 已动态添加到可用工具集", tool_name)
                logger.debug("  当前 tools 列表大小: %s", len(tools))

        # 持久化工具结果到 messages 和 memory
        self._append_tool_result_to_messages(
            fname, args, tool_result, full_thinking, arg_str,
            messages, active_skill_text, active_skill_ids, log_callback,
            content_parts=content_parts,
        )

        if log_callback:
            found_names = [d.get("name", "") for d in definitions_found]
            logger.debug("获取工具定义: %s", ", ".join(found_names))
            log_callback(str(tool_result), "base_tool")

        return True

    def _process_tool_call_in_loop(
        self,
        result: StreamResult,
        full_thinking: str,
        content_parts: list[str],
        messages: list[dict[str, Any]],
        active_skill_text: list[str],
        active_skill_ids: list[str],
        model,
        tools: list[dict],
        log_callback,
        _emit_token_usage: Callable[[], None],
    ) -> dict:
        """处理主循环中的工具调用。

        Args:
            result: StreamResult 对象，包含工具调用信息。
            full_thinking: 本轮推理内容。
            content_parts: 本轮文本内容片段列表。
            messages: 当前消息列表。
            active_skill_text: 当前激活的技能文本列表。
            active_skill_ids: 当前激活的技能ID列表。
            model: 当前使用的模型实例。
            tools: 当前工具定义列表。
            log_callback: 日志回调函数。
            _emit_token_usage: Token 使用量发送函数。

        Returns:
            dict: 包含 action 键的结果字典：
                - {"action": "continue", "tool_called": bool}: 继续主循环
                - {"action": "return", "value": str}: 应立即返回该值
        """
        # AI-BRANCH-MARKER: 控制工具分支 — select_skill/finish/ask_user 走不同的 action 路径
        # Handle tool call response
        fname = result.tool_name
        arg_str = result.tool_arguments or "{}"
        try:
            args = json.loads(arg_str)
        except json.JSONDecodeError:
            # arg_str 不是有效 JSON，回退为空字典并重新序列化为 JSON 字符串
            args = {}
            arg_str = json.dumps(args, ensure_ascii=False)
        logger.debug("解析工具调用: fname=%s, args keys=%s", fname, list(args.keys()) if isinstance(args, dict) else type(args))

        # 状态机：LLM 调用工具前设置为 TOOL_CALLED
        try:
            self._state = ConversationState.TOOL_CALLED
            logger.debug(f"状态转换: {self._state.value}")
        except Exception as e:
            logger.warning(f"状态转换异常: {e}, 当前状态: {self._state.value}")

        # 关键修复：full_thinking 不再单独作为一条 assistant(think) 消息持久化，
        # 而是作为 assistant tool_call 消息的 content 一起写入，
        # 避免出现 tool 前面只有 think assistant 而无 tool_calls 的断裂结构。

        if fname == "request_tool_details":
            if self._handle_request_tool_details_step(
                fname, args, model, tools, full_thinking, arg_str,
                messages, active_skill_text, active_skill_ids, log_callback,
                content_parts=content_parts,
            ):
                return {"action": "continue", "tool_called": False}

        if log_callback:
            try:
                args_s = json.dumps(args, ensure_ascii=False)
            except (TypeError, ValueError):
                args_s = str(args)

            # 保留调试日志，移除一次性工具调用消息（已通过流式机制发送）
            if fname == "finish":
                content_preview = "".join(content_parts)[:200] if content_parts else "(空)"
                logger.debug("[finish] LLM 调用 finish，原始 args: %s | content_parts 预览: %r", args_s, content_preview)
            elif fname == "select_skill":
                logger.debug("选择 Skill: %s", args.get('skill_id', ''))
            else:
                logger.debug("调用工具 `%s` · %s", fname, args_s)
        # 注意：此处不再单独保存 assistant(tool_call) 消息，
        # 由下方 _persist_after_tool_turn 统一保存完整的
        # assistant(tool_calls) + tool(result) 序列，避免重复渲染。

        # AI-BRANCH-MARKER: 危险命令确认分支 — 需要用户确认的命令走确认路径
        if fname == "run_command":
            confirm_result = self._handle_run_command_confirmation(
                fname, args, log_callback, _emit_token_usage, messages,
            )
            if confirm_result is not None:
                action, value = confirm_result
                if action == "return":
                    return {"action": "return", "value": value}

        # 安装类工具确认分支：向用户数据目录写入文件前必须经用户确认
        elif fname in ("install_skill_from_zip", "install_cli_package"):
            confirm_result = self._handle_install_confirmation(
                fname, args, log_callback, _emit_token_usage, messages,
            )
            if confirm_result is not None:
                action, value = confirm_result
                if action == "return":
                    return {"action": "return", "value": value}

        logger.debug("准备执行工具: %s", fname)
        if fname == "run_command":
            cmd = str(args.get("command", ""))[:80]
            logger.debug("  命令: %s...", cmd)

        # 检测重复工具调用（可通过配置禁用）
        _control_tools = ("select_skill", "finish", "ask_user")
        is_repeated = False
        repeat_warning = None
        last_result = None
        tool_called = False

        # AI-BRANCH-MARKER: 重复检测分支 — 检测到重复工具调用时的处理路径
        if config.TOOL_CALL_DEDUPLICATION_ENABLED and fname not in _control_tools:
            is_repeated, repeat_warning, last_result = self._check_repeated_tool_call(fname, args)
            if is_repeated:
                logger.warning("检测到重复工具调用: %s", fname)
                logger.debug("连续重复次数: %s", self._consecutive_repeat_count)

                result = repeat_warning or f"检测到重复的 {fname} 调用"
                terminate = False
                final = None

                max_repeats = config.MAX_CONSECUTIVE_REPEATS
                if self._consecutive_repeat_count >= max_repeats:
                    auto_finish_msg = (
                        f"检测到连续 {self._consecutive_repeat_count} 次重复执行工具 [{fname}]，已自动结束任务。\n\n"
                        f"最后一次执行结果摘要：\n{(last_result or '')[:200]}"
                    )
                    logger.warning("触发自动终止: %s", auto_finish_msg)

                    # 补发 TURN_START：自动结束文案作为独立卡片渲染，与持久化（独立 assistant 消息）一致
                    self._emit_event(AgentEventType.TURN_START, token_usage=self._token_usage.total_tokens)
                    if log_callback:
                        log_callback(auto_finish_msg, "assistant")
                    if self.memory is not None:
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(self._conversation_id, "assistant", auto_finish_msg, metadata=metadata)
                    _emit_token_usage()
                    return {"action": "return", "value": auto_finish_msg}
        else:
            is_repeated = False

        # 工具执行流程：
        # 1. 通用重复检测（适用于所有工具）→ 已在前面实现
        # 2. 执行工具 → self._dispatch()
        # 3. 结果格式化 → 已实现
        # 4. 写入操作特例检测（仅限 run_command + 写入操作）→ 原有逻辑

        if not is_repeated:
            # 发出 TOOL_EXECUTE_START 事件
            self._emit_event(AgentEventType.TOOL_EXECUTE_START, tool_name=fname)
            try:
                result, terminate, final = self._dispatch(fname, args, active_skill_text, active_skill_ids)
            except Exception as e:
                # 双重保护：捕获所有未预期的异常，防止主进程崩溃
                logger.exception(f"工具 [{fname}] 调度异常: {e}")
                result = f"错误: 工具 {fname} 调度异常: {e}"
                terminate = False
                final = None
            finally:
                # 发出 TOOL_EXECUTE_END 事件
                self._emit_event(AgentEventType.TOOL_EXECUTE_END, tool_name=fname)

            # 状态机：工具执行完成后设置为 TOOL_EXECUTED
            try:
                self._state = ConversationState.TOOL_EXECUTED
                logger.debug(f"状态转换: {self._state.value}, 等待LLM调用finish工具或自动finish")
            except Exception as e:
                logger.warning(f"状态转换异常: {e}, 当前状态: {self._state.value}")

            # 方案 A：标记本轮已调用过工具（含 finish/ask_user/select_skill 等控制工具），
            # 用于下方判断是否允许 LLM 用纯文本直接结束。
            # 规则：一旦调用过工具，自动将文本输出作为最终结果返回。
            tool_called = True

            if fname not in _control_tools:
                self._record_tool_call(fname, args, str(result))

        # 标准化工具返回结果格式（排除控制类工具和已经是标准格式的结果）
        if fname not in ("select_skill", "finish", "ask_user"):
            result_str = str(result)
            # 保护结构化返回格式（如 run_command 的【执行结果】... 格式）
            if result_str.startswith("【执行结果】"):
                pass  # 保持原有结构化格式不变
            elif not result_str.startswith(("✅", "❌", "⚠️")):
                # 判断是否为成功结果（简单启发式规则）
                is_success = (
                    "exit_code: 0" in result_str or  # 命令执行成功
                    (len(result_str) > 10 and "error" not in result_str.lower()[:100])  # 有实质内容且无明显错误
                )
                original_len = len(result_str)
                if is_success and len(result_str.strip()) > 0:
                    result = self._format_tool_result(True, result_str)
                    logger.debug("格式化工具结果: %s, 成功=True, 原始长度=%s, 格式化后长度=%s", fname, original_len, len(str(result)))
                elif not is_success:
                    # 保持原始错误信息，但添加前缀
                    if not result_str.startswith("错误"):
                        result = f"❌ 操作失败\n\n{result}"
                        logger.debug("格式化工具结果: %s, 成功=False, 原始长度=%s, 添加失败前缀", fname, original_len)

        # 性能优化：移除高频DEBUG日志，降低I/O开销
        # logger.debug("工具执行完成:")
        # result_str = str(result)
        # result_len = len(result_str)
        # logger.debug("  - result 长度: %s", result_len)
        # if result_len <= 500:
        #     # 短结果：完整显示
        #     logger.debug("  - result: %s", result_str)
        # else:
        #     # 长结果：智能截断，显示前后各500字符
        #     result_head = result_str[:500]
        #     result_tail = result_str[-500:]
        #     omitted_count = result_len - 1000
        #     logger.debug("  - result: %s...(省略%d字符)...%s", result_head, omitted_count, result_tail)
        # logger.debug("  - terminate: %s", terminate)
        # logger.debug("  - final: %s", final is not None)

        if log_callback and fname == "select_skill":
            # 保留调试日志，移除一次性工具调用消息（已通过流式机制发送）
            if str(result).startswith("错误"):
                logger.warning("选择 Skill 失败: %s", result)
            else:
                ids_join = "、".join(active_skill_ids)
                n = len(active_skill_ids)
                logger.debug("命中 Skill「%s」｜本轮已累计 id：%s（共 %d 个）",
                           args.get('skill_id', ''), ids_join, n)
                prefix = (
                    f"［第 {n} 次加载｜本轮已累计 {n} 份｜id 顺序：{ids_join}］\n\n"
                )
                log_callback(prefix + str(result), "doc")

        if log_callback and fname not in ("finish", "select_skill", "ask_user"):
            result, auto_end_msg = self._format_and_send_tool_result(
                fname, args, result, log_callback, _emit_token_usage,
            )
            if auto_end_msg is not None:
                return {"action": "return", "value": auto_end_msg}

        # AI-BRANCH-MARKER: 终止型工具分支 — finish等工具设置terminate=True时直接返回
        if terminate and final is not None:
            # 关键修复：终止型工具（如 finish）也要先追加 assistant(tool_calls)+tool 完整序列
            self._append_tool_result_to_messages(
                fname, args, str(result), full_thinking, arg_str,
                messages, active_skill_text, active_skill_ids, log_callback,
                content_parts=content_parts,
            )
            if self.memory is not None:
                conversation_id = self._conversation_id
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(conversation_id, "assistant", str(final), metadata=metadata)
            # 最终回复持久化为独立 assistant 消息；补发 TURN_START 让前端
            # 把含本工具调用的流式卡片定稿并新建卡片，保证流式渲染与历史加载一致
            self._emit_event(AgentEventType.TURN_START, token_usage=self._token_usage.total_tokens)
            if log_callback:
                log_callback(str(final), "assistant")
            _emit_token_usage()
            logger.debug(f"工具要求终止 (terminate=True), 返回 final (长度: {len(str(final))})")
            return {"action": "return", "value": final}

        # AI-BRANCH-MARKER: ask_user等待分支 — 返回等待用户回复标记，挂起当前对话
        if fname == "ask_user" and not str(result).startswith("错误"):
            self._append_tool_result_to_messages(
                fname, args, str(result), full_thinking, arg_str,
                messages, active_skill_text, active_skill_ids, log_callback,
                content_parts=content_parts,
            )
            if log_callback:
                log_callback(_ask_user_ui_log_payload(args), "await_user")
            # 保存待恢复状态：用户回复后由 _handle_ask_user_resume 注入对话继续推理
            self._ask_user_confirm_pending = True
            self._ask_user_confirm_messages = list(messages)
            _emit_token_usage()
            logger.debug("等待用户回复 (ask_user)")
            return {"action": "return", "value": SKILL_AGENT_AWAITING_USER_REPLY}

        # AI-BRANCH-MARKER: 原子工具分支 — 普通工具执行后返回 continue
        self._append_tool_result_to_messages(
            fname, args, str(result), full_thinking, arg_str,
            messages, active_skill_text, active_skill_ids, log_callback,
            content_parts=content_parts,
        )
        return {"action": "continue", "tool_called": tool_called}

    # 强制引用指令模式：/skill:<id> 或 /cli:<name>（出现在消息开头或空白符之后）
    _FORCED_SKILL_RE = re.compile(r"(?:^|\s)/skill:([A-Za-z0-9_\-]+)", re.IGNORECASE)
    _FORCED_CLI_RE = re.compile(r"(?:^|\s)/cli:([A-Za-z0-9_\-]+)", re.IGNORECASE)
    # 新占位符语法：<Skill:id/>、<File:file_id/>、<Cli:name/>
    _REF_TAG_RE = re.compile(r"<(Skill|File|Cli):([A-Za-z0-9_\-]+)/>")

    def _extract_refs(self, user_query: str) -> tuple[str, str, list[dict[str, Any]]]:
        """提取强制引用并注入对应文档（新占位符 + 旧 / 语法双支持）。

        新语法在 LLM 查询中保留编号锚点（位置相关性），文档集中追加在
        消息尾部；旧 / 语法沿用剥离行为。两者都产出 ext 引用元数据
        （forced_refs），供历史轮短标记渲染与前端 chip 使用。

        Args:
            user_query: 原始用户输入（可能含占位符或旧标记）。

        Returns:
            (LLM 查询, 强制注入的文档块, ext 引用元数据列表)。
            无引用时文档块为空字符串、列表为空。
        """
        query = user_query or ""
        if not query:
            return ("", "", [])

        refs: list[dict[str, Any]] = []
        blocks: list[str] = []
        disabled_ids = self._disabled_skill_ids_frozen()

        def _ref_index(ref: dict[str, Any]) -> int:
            """去重：同一 (type, id) 复用同一编号与文档块。返回 1-based 编号。"""
            for i, r in enumerate(refs):
                if r.get("type") == ref.get("type") and r.get("id") == ref.get("id"):
                    return i + 1
            refs.append(ref)
            return len(refs)

        def _skill_anchor(sid: str) -> str:
            idx = _ref_index({"type": "skill", "id": sid})
            if sid in disabled_ids:
                return f"[引用#{idx}: Skill「{sid}」已在设置中禁用，未注入]"
            skill = self.registry.get(sid)
            if skill is None:
                return f"[引用#{idx}: 未找到 Skill「{sid}」，请检查引用名称]"
            name = getattr(skill, "name", sid)
            blocks.append(
                f"<引用文档 #{idx}: Skill {sid}>\n"
                "【用户强制引用的 Skill（已绕过自动匹配，必须按此文档执行）】\n"
                + format_skill_for_prompt(skill)
                + f"\n</引用文档 #{idx}>"
            )
            return f"[引用#{idx}: Skill「{name}」]"

        def _cli_anchor(name: str) -> str:
            idx = _ref_index({"type": "cli", "id": name})
            try:
                import cli_manager
                pkg = cli_manager.get_cli_package(name)
                if pkg is None:
                    return f"[引用#{idx}: 未找到 CLI 包「{name}」，请检查引用名称]"
                blocks.append(
                    f"<引用文档 #{idx}: CLI {name}>\n"
                    "【用户强制引用的 CLI 工具（已绕过自动匹配，按以下用法使用）】\n"
                    + cli_manager.format_cli_usage_text(pkg)
                    + f"\n</引用文档 #{idx}>"
                )
                return f"[引用#{idx}: CLI「{name}」]"
            except Exception as e:  # noqa: BLE001
                logger.warning(f"强制引用 CLI 包处理异常: {e}")
                return f"[引用#{idx}: CLI「{name}」注入失败]"

        def _file_anchor(fid: str) -> str:
            try:
                from document_parser.file_storage import get_upload_info, get_uploaded_text
                info = get_upload_info(fid)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"强制引用文件处理异常: {e}")
                info = None
            if info is None:
                _ref_index({"type": "file", "id": fid, "missing": True})
                return f"[文件已失效: {fid}]"
            name = info.get("file_name") or fid
            mime = info.get("mime_type") or ""
            is_image = mime.startswith("image/")
            if is_image:
                # 图片走多模态通道（_append_model_messages 按 is_image 构建 image_url），
                # 此处只留锚点与元数据，不注入文本块
                _ref_index({"type": "file", "id": fid, "file_name": name, "is_image": True})
                return f"[引用: 图片「{name}」]"
            idx = _ref_index({"type": "file", "id": fid, "file_name": name})
            text = ""
            try:
                text = get_uploaded_text(fid) or ""
            except Exception as e:  # noqa: BLE001
                logger.warning(f"读取上传文件文本失败: {fid} - {e}")
                text = f"[文件内容读取失败: {e}]"
            blocks.append(
                f"<引用文件 #{idx}: {name}>\n{text}\n</引用文件 #{idx}>"
            )
            return f"[引用#{idx}: 文件「{name}」]"

        def _sub(m: "re.Match") -> str:
            kind, ref_id = m.group(1), m.group(2)
            if kind == "Skill":
                return _skill_anchor(ref_id)
            if kind == "Cli":
                return _cli_anchor(ref_id)
            return _file_anchor(ref_id)

        # 新占位符 → 编号锚点（保留位置相关性）
        query = self._REF_TAG_RE.sub(_sub, query)

        # 旧 / 语法：剥离并追加文档块（行为兼容）
        legacy_skill_ids = [m.group(1) for m in self._FORCED_SKILL_RE.finditer(query)]
        legacy_cli_names = [m.group(1) for m in self._FORCED_CLI_RE.finditer(query)]
        if legacy_skill_ids or legacy_cli_names:
            cleaned = self._FORCED_SKILL_RE.sub(" ", query)
            cleaned = self._FORCED_CLI_RE.sub(" ", cleaned)
            query = re.sub(r"\s{2,}", " ", cleaned).strip()
            for sid in dict.fromkeys(legacy_skill_ids):
                _skill_anchor(sid)
            for name in dict.fromkeys(legacy_cli_names):
                _cli_anchor(name)

        return (query, "\n\n".join(blocks), refs)

    def run(self, user_query: str, log_callback: Optional[Callable[[str, str], Any]] = None, stop_check_callback: Optional[Callable[[], bool]] = None) -> str:
        """SkillAgent 主运行方法，执行输入分类、工具循环和结果返回。

        核心流程：
        1. 处理运行时确认续跑（如用户确认/取消/修改危险命令）
        2. 分类用户输入（简单任务 / 复杂任务 / 直接回复）
        3. 进入双层 While 循环架构：
           - 外层循环：FollowUp 驱动，内层完成后检查后续任务
           - 内层循环：ToolCall/Steering 驱动，执行 ReAct 流程
        4. 每步调用 LLM，根据返回结果分发到文本处理或工具执行
        5. 工具执行结果追加到消息列表，继续循环直到结束
        6. 错误恢复：LLM 错误注入上下文继续推理，而非直接终止

        Args:
            user_query: 用户输入文本。
            log_callback: 前端回调函数 (content, msg_type)，用于流式发送消息。
            stop_check_callback: 停止检测回调，返回 True 时终止循环。

        Returns:
            最终的回复文本字符串。

        Side effects:
            修改 memory（追加消息）、更新状态机、消费上传文件缓存、
            重置重复检测计数器和计划确认标志。
        """
        import traceback
        # 性能优化：移除高频DEBUG日志，降低I/O开销
        # logger.debug("===== run() 开始执行 =====")
        # logger.debug("user_query 长度: %s, 前50字: %s", len(user_query), user_query[:50])
        # logger.debug("conversation_id: %s", self._conversation_id)

        self._stop_event.clear()
        self._recent_commands = []
        self._recent_tool_calls = []
        self._consecutive_repeat_count = 0
        self._token_usage = TokenUsage.empty()
        # 清空 Steering/FollowUp 队列，避免上一轮遗留消息干扰
        self._steering_queue.clear()
        self._followup_queue.clear()
        # 状态机：方法开始时设置为 IDLE
        self._state = ConversationState.IDLE

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

            # 发出 AGENT_START 事件（必须在分类/直接回复之前，确保前端能接收所有流式事件）
            self._emit_event(AgentEventType.AGENT_START, user_query=user_query[:200])

            # 新方案：运行时拦截确认检测
            # 如果上一轮触发了运行时确认，根据用户回复直接处理，不发送给 LLM
            # AI-BRANCH-MARKER: 运行时确认续跑分支 — 根据上一轮确认状态决定是直接进入主循环还是重新分类
            _rt_confirm_result = self._handle_runtime_confirmation(user_query, log_callback, _emit_token_usage)
            _skip_to_main_loop = False
            if _rt_confirm_result["action"] == "return":
                return _rt_confirm_result["value"]
            elif _rt_confirm_result["action"] == "skip_to_main_loop":
                messages = _rt_confirm_result["messages"]
                active_skill_text = _rt_confirm_result["active_skill_text"]
                active_skill_ids = _rt_confirm_result["active_skill_ids"]
                model = _rt_confirm_result["model"]
                tools = _rt_confirm_result["tools"]
                _skip_to_main_loop = True

            # ask_user 待恢复处理：上一轮 LLM 调用 ask_user 后，本轮用户回复即为回答，
            # 注入回复后直接进入主循环继续推理（不重新分类/规划）
            # AI-BRANCH-MARKER: ask_user 续跑分支 — 用户回答注入后跳过输入分类直接进入主循环
            if not _skip_to_main_loop:
                _ask_user_resume = self._handle_ask_user_resume(user_query, log_callback, _emit_token_usage)
                if _ask_user_resume["action"] == "return":
                    return _ask_user_resume["value"]
                elif _ask_user_resume["action"] == "skip_to_main_loop":
                    messages = _ask_user_resume["messages"]
                    active_skill_text = _ask_user_resume["active_skill_text"]
                    active_skill_ids = _ask_user_resume["active_skill_ids"]
                    model = _ask_user_resume["model"]
                    tools = _ask_user_resume["tools"]
                    _skip_to_main_loop = True

            # 如果从运行时确认继续，跳过计划检测和输入分类，直接进入主循环
            # AI-BRANCH-MARKER: 输入分类分支 — 根据用户输入类型(text/plan_confirm/plan_reject)决定后续流程
            if not _skip_to_main_loop:
                # 强制引用（新占位符 <Skill:id/> / <File:fid/> / <Cli:name/>，
                # 兼容旧 /skill:id 语法）：占位符替换为编号锚点，
                # 文档/文件内容追加在消息尾部（位置相关性 + 集中注入）。
                # 持久化与回显保留原始占位符文本（前端渲染为引用 chip），
                # ext.forced_refs 记录引用元数据（历史轮短标记渲染依据）
                _persist_query = user_query
                user_query, _forced_ref_text, _refs = self._extract_refs(user_query)
                if _forced_ref_text:
                    self._last_user_query = user_query
                    user_query = (user_query + "\n\n" + _forced_ref_text).strip()
                    self._pending_user_refs = _refs
                else:
                    _persist_query = None
                    self._pending_user_refs = []

                ctx_result = self._classify_and_prepare_context(
                    user_query, log_callback, _emit_token_usage, persist_query=_persist_query
                )
                if ctx_result["action"] == "return":
                    return ctx_result["value"]
                model = ctx_result["model"]
                tools = ctx_result["tools"]
                messages = ctx_result["messages"]
                active_skill_text = ctx_result["active_skill_text"]
                active_skill_ids = ctx_result["active_skill_ids"]

            # 方案 A：记录本轮（主循环内）是否调用过任何工具，用于
            # 在 LLM 试图用纯文本结束对话时自动包装为 finish 工具调用。
            # 规则：一旦调用过工具，自动将文本输出作为最终结果返回。
            has_called_tool_in_run = False

            # ===== 双层 While 循环架构 =====
            # 外层循环：由 FollowUp 消息队列驱动
            # 内层循环：由 ToolCall/Steering 消息驱动
            _inner_loop_active = True

            # 最终返回值：用户停止/token 超限等 break 路径不会赋值，必须预初始化
            _last_return_value = None

            # 标记外层循环是否应强制退出（致命错误等）
            _outer_exit = False

            # 连续 LLM 通信错误计数：LLM 服务不可用时（连接失败/超时等），
            # 非致命错误会 continue 重试；连续超过上限则终止 run，
            # 避免无限重试导致前端一直处于"运行中"且停止按钮无法生效
            _consecutive_llm_errors = 0
            _max_consecutive_llm_errors = getattr(
                config, "LLM_CONSECUTIVE_ERROR_LIMIT", 3
            )

            while True:
                # 致命错误等强制退出
                if _outer_exit:
                    break

                # === 外层循环：检查 FollowUp 队列 ===
                if not _inner_loop_active and not self._followup_queue:
                    # 无 FollowUp 消息，退出外层循环
                    break

                # 注入 FollowUp 消息到上下文
                if self._followup_queue:
                    followup_messages = self._drain_followup_queue()
                    for fu_msg in followup_messages:
                        messages.append({"role": "user", "content": fu_msg})
                        if self.memory is not None:
                            self.memory.append_message(self._conversation_id, "user", fu_msg)
                        logger.debug("注入 FollowUp 消息: %s", fu_msg[:100])
                    _inner_loop_active = True

                # === 内层循环：ToolCall/Steering 驱动的 ReAct 流程 ===
                while _inner_loop_active:
                    # 检查终止条件
                    if _check_stop():
                        stop_msg = "用户已停止推理"
                        if log_callback:
                            log_callback(stop_msg, "assistant")
                        if self.memory is not None:
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", stop_msg, metadata=metadata)
                        _emit_token_usage()
                        logger.debug("用户停止推理，退出循环")
                        break

                    # AI-BRANCH-MARKER: Token预算分支 — 超限时走 steering 路径，正常走 followup 路径
                    # Token 消耗上限检查（替代 max_steps）
                    if self._token_usage.total_tokens > config.MAX_TOKEN_BUDGET:
                        budget_msg = f"已达到 token 消耗上限（{config.MAX_TOKEN_BUDGET}），已停止。"
                        logger.warning(budget_msg)
                        if log_callback:
                            log_callback(budget_msg, "assistant")
                        if self.memory is not None:
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", budget_msg, metadata=metadata)
                        _emit_token_usage()
                        break

                    # 检查 Steering 队列
                    if self._steering_queue:
                        steering_messages = self._drain_steering_queue()
                        for st_msg in steering_messages:
                            messages.append({"role": "user", "content": f"[用户干预] {st_msg}"})
                            if self.memory is not None:
                                self.memory.append_message(self._conversation_id, "user", f"[用户干预] {st_msg}")
                            logger.debug("注入 Steering 消息: %s", st_msg[:100])
                        # Steering 消息注入后继续内层循环，让 LLM 处理干预
                        # 不 break，继续让 LLM 推理

                    # 发出 TURN_START 事件
                    self._emit_event(AgentEventType.TURN_START, token_usage=self._token_usage.total_tokens)

                    thinking_parts: list[str] = []
                    content_parts: list[str] = []

                    show_thinking = self._enable_thinking

                    def _stream_callback(content: str, msg_type: str) -> None:
                        if log_callback:
                            if msg_type == "think" and not show_thinking:
                                pass
                            else:
                                if msg_type in ("think", "tool_call"):
                                    mapped_type = msg_type
                                else:
                                    mapped_type = "assistant"
                                log_callback(content, mapped_type)
                        if msg_type == "think":
                            thinking_parts.append(content)
                        elif msg_type == "content":
                            content_parts.append(content)

                    self._update_system_message(messages)

                    def _llm_state_update_callback(state_message: dict) -> None:
                        if log_callback:
                            import json
                            state_json = json.dumps(state_message, ensure_ascii=False)
                            log_callback(state_json, "llm_state_update")

                    model.set_state_update_callback(_llm_state_update_callback)

                    llm_result = model.stream_request_llm_with_tools(messages, tools, _stream_callback)

                    # Accumulate token usage
                    if llm_result.token_usage is not None:
                        self._token_usage = self._token_usage + llm_result.token_usage

                    full_thinking = "".join(thinking_parts).strip()

                    # 发出 TURN_END 事件
                    self._emit_event(AgentEventType.TURN_END, result_type=llm_result.result_type, token_usage=self._token_usage.total_tokens)

                    # 成功获得 LLM 响应（非 error），清零连续错误计数
                    if llm_result.result_type != "error":
                        _consecutive_llm_errors = 0

                    # AI-BRANCH-MARKER: 内层循环三路分支 — text(return)/tool_call(continue)/max_tokens(steering)
                    # Handle text response
                    if llm_result.result_type in ("text", "truncated"):
                        if not full_thinking:
                            full_thinking = "".join(thinking_parts).strip()

                        action, value = self._handle_text_result(
                            llm_result, full_thinking, content_parts, messages,
                            has_called_tool_in_run, log_callback, _emit_token_usage,
                        )
                        if action == "return":
                            _last_return_value = value
                            _inner_loop_active = False
                            # 不直接 return，由外层循环决定是否检查 FollowUp 后统一返回
                            break
                        elif action == "continue":
                            continue

                    # AI-BRANCH-MARKER: 错误恢复分支 — 致命错误(api_key/401)终止，非致命错误继续循环
                    # Handle error response — 优雅错误恢复：非致命错误不终止循环
                    if llm_result.result_type == "error":
                        err = llm_result.error_message or "模型返回未知错误"
                        if log_callback:
                            log_callback(err, "assistant")
                        if self.memory is not None:
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", err, metadata=metadata)
                        _emit_token_usage()
                        logger.debug("返回错误 (长度: %s)", len(err))
                        # 发出 ERROR 事件（字段名与前端 handleError 对齐为 message）
                        self._emit_event(AgentEventType.ERROR, message=err[:200])
                        # 致命错误（如 API key 无效）终止
                        if "api_key" in err.lower() or "authentication" in err.lower() or "401" in err:
                            _last_return_value = err
                            _inner_loop_active = False
                            _outer_exit = True  # 标记外层循环也应退出
                            break
                        # 连续非致命错误超限：LLM 服务持续不可用（如 llama.cpp 未启动），
                        # 终止 run 而非无限重试，保证 message.complete 能送达前端
                        _consecutive_llm_errors += 1
                        if _consecutive_llm_errors >= _max_consecutive_llm_errors:
                            logger.warning(
                                "连续 LLM 通信错误 %d 次（上限 %d），终止 run",
                                _consecutive_llm_errors, _max_consecutive_llm_errors,
                            )
                            _last_return_value = err
                            _inner_loop_active = False
                            _outer_exit = True
                            break
                        # 非致命错误继续内层循环，让 LLM 有机会恢复
                        continue

                    # Handle tool call response
                    _tool_call_result = self._process_tool_call_in_loop(
                        llm_result, full_thinking, content_parts, messages,
                        active_skill_text, active_skill_ids, model, tools,
                        log_callback, _emit_token_usage,
                    )
                    if _tool_call_result["action"] == "return":
                        _last_return_value = _tool_call_result["value"]
                        _inner_loop_active = False
                        # 不直接 return，由外层循环决定是否检查 FollowUp 后统一返回
                        break
                    if _tool_call_result.get("tool_called", False):
                        has_called_tool_in_run = True
                    # Tool call completed, continue inner loop

                # 内层循环结束，检查是否有 FollowUp 消息
                _inner_loop_active = False
                # 外层循环会在顶部检查 _followup_queue

            # 双层循环正常退出
            # 双层循环退出后，发出 AGENT_END 事件并返回最终结果
            _final_result = _last_return_value or ""
            self._emit_event(AgentEventType.AGENT_END, reason="loop_exit", token_usage=self._token_usage.total_tokens)
            return _final_result
        
        except Exception as e:
            logger.error(f"发生未捕获异常: {type(e).__name__}: {e}")
            logger.error(f"堆栈跟踪:\n{traceback.format_exc()}")
            
            err_msg = f"执行出错: {type(e).__name__}: {e}"
            if log_callback:
                log_callback(err_msg, "assistant")
                log_callback(f"详细错误日志已记录，如需排查请查看终端输出。", "info")
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", err_msg, metadata=metadata)
            
            _emit_token_usage()
            logger.debug("异常退出，返回 err_msg")
            return err_msg
        finally:
            # 清理 LLM 状态更新回调，防止内存泄漏
            try:
                model.set_state_update_callback(None)
            except (NameError, AttributeError):
                pass  # model 未定义或没有该方法，忽略

            # 状态机：会话完成时设置为 COMPLETED
            self._state = ConversationState.COMPLETED
            logger.debug(f"会话完成，最终状态: {self._state.value}, 总token使用: {self._token_usage}")

            self._uploaded_files_content = {"text_content": "", "images": []}
            # 重置计划确认标志（pending_plan 不清空，供续跑使用；下次首次规划会覆盖）
            self._plan_confirmed = False
            logger.debug("===== run() 结束执行 =====")
