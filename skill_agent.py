from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from sys import platform
from enum import Enum
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
from logger import get_module_logger

logger = get_module_logger("SkillAgent")


class PlanMode(str, Enum):
    NO_PLAN = "no_plan"
    SIMPLE_TASK = "simple_task"
    COMPLEX_TASK = "complex_task"


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
        # 存储上传文件的结构化数据：{"text_content": str, "images": list}
        self._uploaded_files_content: dict = {"text_content": "", "images": []}
        self._enable_thinking: bool = False
        self._step_plan: list[dict] = []
        self._current_step: int = 0
        self._success_criteria: str = ""
        # 计划确认环节相关状态
        self._pending_plan: list[dict] = []
        self._pending_success_criteria: str = ""
        self._pending_plan_analysis: str = ""
        self._plan_confirmed: bool = False

    def set_file_upload_controller(self, controller: Any) -> None:
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

    @property
    def _get_compactor(self) -> ContextCompactor | None:
        if self._compactor is None and self.memory is not None:
            model = get_chat_model(enable_thinking=self._enable_thinking)
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
        return self._conversation_id

    def reload_skills(self) -> None:
        self.registry.reload()

    def start_new_conversation(self, *, conversation_type: str = 'agent_conversation', default_skills: list[dict] | None = None) -> tuple[str, str]:
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

    def set_conversation_id(self, conversation_id: str) -> None:
        self._conversation_id = (conversation_id or "").strip()

    def set_enable_thinking(self, enabled: bool) -> None:
        self._enable_thinking = enabled

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

    def _classify_input(self, user_query: str) -> PlanMode:
        """对用户输入进行分类，判断是否需要规划。
        
        Returns:
            PlanMode: 分类结果
        """
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
            
            response = model.client.chat.completions.create(
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

            # 将上传文件内容追加到用户消息（传递 enable_vision）
            user_content = self._consume_uploaded_files_content(
                user_query.strip(),
                enable_vision=model.enable_vision,
            )

            messages = [
                {"role": "system", "content": f"你是一个友好的助手。请直接用简洁的语言回答用户问题。\n\n{self.get_base_info()}"},
                {"role": "user", "content": user_content},
            ]

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
                self.memory.append_message(self._conversation_id, "user", user_content)
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
            
            response = model.client.chat.completions.create(
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
            cid = self._conversation_id
            # 持久化原用户需求（此时 run() 尚未走到 _append_model_messages）
            metadata: dict[str, Any] = {}
            if hasattr(self, "_last_uploaded_files") and self._last_uploaded_files is not None:
                metadata["files"] = self._last_uploaded_files
                self._last_uploaded_files = None
            # 将上传文件内容追加到用户消息（一次性消费）
            user_content = self._consume_uploaded_files_content(
                user_query.strip(),
                enable_vision=enable_vision,
            )
            self.memory.append_message(cid, "user", user_content, metadata=metadata)
            # 持久化计划展示
            self.memory.append_message(cid, "assistant", plan_display, metadata={"type": "plan"})
            # 持久化确认请求（type=plan_confirm 区别于普通 ask_user，避免被现有 ask_user 历史检测误触）
            self.memory.append_message(
                cid,
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
        cid = self._conversation_id
        if not cid:
            return None
        records = self.memory.get_message_records(cid)
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
        enable_vision: bool = True,
    ) -> None:
        assert self.memory is not None
        cid = self._conversation_id
        prior = _history_without_system(self.memory.get_messages(cid))
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
        self.memory.append_message(cid, "user", user_content, metadata=metadata)
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
        arg_str: str | None = None,
    ) -> None:
        """持久化并追加一轮工具调用的完整消息序列。

        关键修复：同时向 messages 追加 assistant(tool_calls) 与 tool(result) 两条消息，
        并为二者持久化相同的 tool_call_id，使跨轮重建历史时仍能正确关联。
        遵守 OpenAI tool calling 协议：tool 消息前必须有带 tool_calls 的 assistant 消息。
        """
        assert self.memory is not None
        cid = self._conversation_id
        if arg_str is None:
            args_str = json.dumps(args, ensure_ascii=False, indent=2)
        else:
            args_str = arg_str
        if tool_call_id is None:
            tool_call_id = f"call_{uuid.uuid4().hex[:12]}"

        # 1) 持久化 assistant 工具调用消息（带 tool_calls 元数据，供 get_messages 还原）
        assistant_content = reasoning_content or None
        assistant_metadata: dict[str, Any] = {
            "type": "tool_call",
            "name": fname,
            "args": args_str,
            "tool_call_id": tool_call_id,
        }
        if reasoning_content:
            assistant_metadata["reasoning_content"] = reasoning_content
        self.memory.append_message(
            cid,
            "assistant",
            reasoning_content or "",
            metadata=assistant_metadata,
        )

        # 2) 追加 assistant tool_call 到 messages（OpenAI 协议必需）
        messages.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": fname, "arguments": arg_str or args_str},
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
            cid,
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
            self.memory.set_active_skills(cid, list(active_skill_ids))
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
        if isinstance(args, str):
            arg_str = args
        else:
            arg_str = json.dumps(args, ensure_ascii=False)
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
        cid = self._conversation_id
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
            cid,
            "assistant",
            reasoning_content or "",
            metadata=assistant_metadata,
        )
        self.memory.append_message(
            cid,
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

    def _summarize_session_skills(self, conversation_id: str, active_skill_ids: list[str] | None = None) -> None:
        import threading
        current_thread = threading.current_thread()
        logger.info("_summarize_session_skills 开始: thread=%s, conversation_id=%s", current_thread.name, conversation_id)
        
        if not self.memory:
            logger.warning("跳过总结: memory 为空 (conversation_id=%s)", conversation_id)
            return

        if active_skill_ids is None:
            logger.debug("获取活跃 skill_ids (conversation_id=%s)", conversation_id)
            active_skill_ids = self.memory.get_active_skills(conversation_id)

        logger.info("开始总结: conversation_id=%s, active_skill_ids=%s", conversation_id, active_skill_ids)

        if not active_skill_ids:
            logger.warning("跳过总结: 无活跃 skill (conversation_id=%s)", conversation_id)
            return

        messages = self.memory.get_message_records(conversation_id)
        if not messages:
            logger.warning("跳过总结: 无会话消息 (conversation_id=%s)", conversation_id)
            return

        logger.info("加载会话消息完成: count=%s, conversation_id=%s", len(messages), conversation_id)

        model = get_chat_model(enable_thinking=self._enable_thinking)
        logger.debug("获取 LLM 模型完成, conversation_id=%s", conversation_id)

        success_count = 0
        for idx, skill_id in enumerate(active_skill_ids):
            try:
                logger.debug("正在总结 skill: %s (%s/%s)", skill_id, idx+1, len(active_skill_ids))
                memory = summarize_skill_execution(skill_id, messages, model)
                if memory:
                    saved_path = save_skill_memory(skill_id, memory, self.registry)
                    logger.debug("skill %s 总结完成, 保存至: %s", skill_id, saved_path)
                    success_count += 1
                else:
                    logger.debug("skill %s 总结结果为空, 未保存", skill_id)
            except Exception as e:
                import traceback
                logger.error("总结 skill %s 执行经验失败: %s", skill_id, e)
                logger.error("异常堆栈:\n%s", traceback.format_exc())
        
        logger.info("总结会话完成: conversation_id=%s, total=%s, success=%s", conversation_id, len(active_skill_ids), success_count)
        logger.debug("后台线程退出: thread=%s", current_thread.name)

    def _start_summary_in_background(self, conversation_id: str, active_skill_ids: list[str] | None = None) -> None:
        import threading
        import config
        
        # 检查是否启用自动总结
        if not config.SKILL_SUMMARY_ENABLED:
            logger.debug("自动总结已禁用，跳过总结 (conversation_id=%s)", conversation_id)
            return
        
        logger.info("准备启动后台总结线程: conversation_id=%s, active_skill_ids=%s", conversation_id, active_skill_ids)
        
        if not self.memory:
            logger.warning("跳过总结: memory 为空 (conversation_id=%s)", conversation_id)
            return
        
        if active_skill_ids is None:
            logger.debug("获取活跃 skill_ids (conversation_id=%s)", conversation_id)
            active_skill_ids = self.memory.get_active_skills(conversation_id)
        
        if not active_skill_ids:
            logger.warning("跳过总结: 无活跃 skill (conversation_id=%s)", conversation_id)
            return
        
        logger.debug("构建总结线程: conversation_id=%s, active_skill_ids=%s", conversation_id, active_skill_ids)
        
        t = threading.Thread(
            target=self._summarize_session_skills,
            args=(conversation_id, active_skill_ids),
            name=f"skill-summary-{conversation_id[:8]}",
            daemon=True,
        )
        t.start()
        
        logger.info("后台线程已启动: name=%s, ident=%s, active_skill_ids=%s", t.name, t.ident, active_skill_ids)
        logger.debug("主线程继续执行 (总结线程独立运行)")

    def _is_reasoning_text(self, text: str, has_called_tool: bool = False) -> bool:
        """判断文本是否为"计划/推理文本"而非最终回答。
        
        识别模式：包含"让我执行"、"我将"、"计划"等关键词，且没有明确的结论性回答。
        
        方案 A 规则增强：
        - 若本轮已调用过工具，则禁止用纯文本结束对话（必须调 finish），
          因此 has_called_tool=True 时直接返回 True，让上层走 continue 分支
          给 LLM 再一轮机会调用 finish。
        """
        if not text or not text.strip():
            return False
        
        # 方案 A：本轮已调用过工具，禁止纯文本直接结束
        if has_called_tool:
            return True
        
        text_lower = text.lower()
        
        # 推理/计划关键词（收紧：去掉"我先"/"让我先"这类过于宽义、易误伤闲聊的词）
        reasoning_keywords = [
            "让我执行",
            "让我调用",
            "我将执行",
            "我将调用",
            "我将使用",
            "我需要执行",
            "让我来获取",
            "让我来查询",
            "首先让我",
            "让我分析一下",
            "让我查看",
            "让我搜索",
            "让我运行",
            "让我尝试",
            "我来执行",
            "我来获取",
            "我来调用",
        ]
        
        for keyword in reasoning_keywords:
            if keyword in text:
                return True
        
        return False

    def run(self, user_query: str, log_callback: Optional[Callable[[str, str], Any]] = None, stop_check_callback: Optional[Callable[[], bool]] = None) -> str:
        import traceback
        logger.debug("===== run() 开始执行 =====")
        logger.debug("user_query 长度: %s, 前50字: %s", len(user_query), user_query[:50])
        logger.debug("conversation_id: %s", self._conversation_id)
        
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
                _emit_token_usage()
                return cancel_msg
            elif plan_resume == "replan":
                replan_msg = "好的，请重新描述您的需求或补充说明，我将重新制定执行计划。"
                if log_callback:
                    log_callback(replan_msg, "assistant")
                if self.memory is not None:
                    self.memory.append_message(self._conversation_id, "user", user_query.strip())
                    self.memory.append_message(
                        self._conversation_id, "assistant", replan_msg,
                        metadata={"token_usage": asdict(self._token_usage)},
                    )
                _emit_token_usage()
                return replan_msg

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
                return self._direct_reply(user_query, log_callback)
            
            if plan_mode == PlanMode.COMPLEX_TASK:
                if self._plan_confirmed:
                    # 续跑：用户已确认计划，注入已确认计划作为约束
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
            # 根据会话类型过滤skill目录
            conv_type = self._get_conversation_type()
            skills_visible = self._get_skills_for_conversation_type(conv_type)
            catalog = build_skills_catalog_text(skills_visible)
            
            tool_catalog = model.build_tool_catalog()
            tool_catalog_text = self._build_tool_catalog_text(tool_catalog)
            system_prompt = self._build_dynamic_system_prompt(catalog, user_query=user_query, tool_catalog=tool_catalog_text)
            logger.debug("初始系统提示词：%s", system_prompt)
            
            # 复杂任务：制定结构化执行计划并请求用户确认
            if plan_mode == PlanMode.COMPLEX_TASK:
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
                else:
                    # 首次：生成计划
                    plan_data = self._plan_steps(user_query, tool_catalog_text, log_callback)
                    if plan_data is not None:
                        # 启用确认环节：请求用户确认后再执行
                        if config.PLAN_CONFIRMATION_ENABLED:
                            return self._request_plan_confirmation(
                                user_query,
                                plan_data,
                                log_callback,
                                enable_vision=model.enable_vision,
                            )
                        # 未启用确认环节：展示计划后直接执行（保持原有行为）
                        plan_display = self._format_plan_display(plan_data)
                        if log_callback:
                            log_callback(plan_display, "plan")
                        if self.memory is not None:
                            self.memory.append_message(
                                self._conversation_id,
                                "assistant",
                                plan_display,
                                metadata={"type": "plan"},
                            )
            
            tools = model.build_skill_agent_tools_initial()
            self._supplied_tool_definitions: dict[str, dict] = {}
            
            logger.debug("===== 目录+补发 渐进披露机制初始化 =====")
            logger.debug("工具目录已构建，包含 %s 个工具的简要描述", len(tool_catalog))
            logger.debug("初始工具集已准备，包含 request_tool_details + CONTROL 工具")
            logger.debug("原子工具将按需通过 request_tool_details 获取")
            
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

            if self.memory is not None:
                self._append_model_messages(
                    messages,
                    system_prompt=system_prompt,
                    user_query=user_query,
                    enable_vision=model.enable_vision,
                )
                prior_messages = self.memory.get_message_records(self._conversation_id)
                logger.debug("加载历史消息: %s 条", len(prior_messages))
                if prior_messages and len(prior_messages) >= 2:
                    last_msg = prior_messages[-1]
                    prev_msg = prior_messages[-2]
                    if last_msg.get("role") == "user" and prev_msg.get("role") == "tool":
                        prev_meta = prev_msg.get("metadata") or {}
                        if prev_meta.get("name") == "ask_user":
                            user_choice = user_query.strip()
                            logger.debug("检测到 ask_user 历史，用户选择: %s", user_choice)
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
                                                # 关键修复：追加完整 assistant(tool_calls)+tool 序列
                                                self._persist_tool_pair_only(
                                                    fname, args, str(result), messages,
                                                    meta_type="base_tool",
                                                )
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
                                                        logger.debug("返回 (依赖安装失败): %s", err_msg)
                                                        return err_msg
                                                    if log_callback:
                                                        log_callback(f"依赖安装成功: {msg}", "base_tool")
                                                    # 关键修复：依赖安装结果也作为完整 tool pair 追加
                                                    self._persist_tool_pair_only(
                                                        "install_dependencies",
                                                        {"msg": msg},
                                                        f"依赖安装成功: {msg}",
                                                        messages,
                                                        meta_type="base_tool",
                                                    )
                                                    
                                                    result = execute_atomic_tool(fname, args, self._tool_ctx, self.registry)
                                                    self._persist_tool_pair_only(
                                                        fname, args, str(result), messages,
                                                        meta_type="base_tool",
                                                    )
                                                    if log_callback:
                                                        log_callback(f"执行命令: {command}", "base_tool")
                                                        log_callback(str(result), "base_tool")
                                                else:
                                                    result = execute_atomic_tool(fname, args, self._tool_ctx, self.registry)
                                                    self._persist_tool_pair_only(
                                                        fname, args, str(result), messages,
                                                        meta_type="base_tool",
                                                    )
                                                    if log_callback:
                                                        log_callback(f"执行命令: {command}", "base_tool")
                                                        log_callback(str(result), "base_tool")
                                                _emit_token_usage()
                                                logger.debug("返回 (确认安装后执行结果): %s", str(result)[:100])
                                                return result
                            elif user_choice == "取消":
                                cancel_msg = "操作已取消"
                                if log_callback:
                                    log_callback(cancel_msg, "assistant")
                                if self.memory is not None:
                                    metadata = {"token_usage": asdict(self._token_usage)}
                                    self.memory.append_message(self._conversation_id, "assistant", cancel_msg, metadata=metadata)
                                _emit_token_usage()
                                logger.debug("返回 (操作已取消)")
                                return cancel_msg

            if self._should_compact(messages):
                if log_callback:
                    log_callback("检测到上下文过长，正在自动压缩...", "info")
                messages = self._perform_compaction(messages, log_callback)

            reasoning_turn_count = 0  # 推理文本轮次计数器
            # 方案 A：记录本轮（主循环内）是否调用过任何工具，用于
            # 在 LLM 试图用纯文本结束对话时强制其改走 finish 工具。
            # 规则：一旦调用过工具，禁止用纯文本 return final_text 直接结束。
            has_called_tool_in_run = False

            for step in range(self.max_steps):
                logger.debug("===== Step %s/%s 开始 =====", step, self.max_steps)
                logger.debug("messages 数量: %s", len(messages))
                
                if _check_stop():
                    stop_msg = "用户已停止推理"
                    if log_callback:
                        log_callback(stop_msg, "assistant")
                    if self.memory is not None:
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(self._conversation_id, "assistant", stop_msg, metadata=metadata)
                    self._start_summary_in_background(self._conversation_id, active_skill_ids)
                    _emit_token_usage()
                    logger.debug("用户停止推理，退出循环")
                    return stop_msg
                
                thinking_parts: list[str] = []
                content_parts: list[str] = []
                
                show_thinking = self._enable_thinking

                def _stream_callback(content: str, msg_type: str) -> None:
                    logger.debug("[run._stream_callback] 回调被触发: type=%s, content前50字=%s",
                                 msg_type, content[:50] if content else "(空)")
                    if log_callback:
                        # 只有当启用思考模式时才发送 think 类型的消息
                        if msg_type == "think" and not show_thinking:
                            logger.debug("[run._stream_callback] think消息已禁用，跳过发送")
                            pass  # 不发送思考消息
                        else:
                            # 将 'content' 映射为 'assistant'，'think' 保持不变
                            mapped_type = msg_type if msg_type == "think" else "assistant"
                            logger.debug("[run._stream_callback] 发送到前端: type=%s -> %s", msg_type, mapped_type)
                            log_callback(content, mapped_type)
                    else:
                        logger.debug("[run._stream_callback] log_callback 未提供，跳过发送")
                    if msg_type == "think":
                        thinking_parts.append(content)
                    elif msg_type == "content":
                        content_parts.append(content)

                logger.debug("准备调用 LLM, 当前消息数: %s", len(messages))
                if len(messages) > 0:
                    last_msg = messages[-1]
                    logger.debug("最后一条消息: role=%s, content 前50字=%s", last_msg.get('role'), str(last_msg.get('content', ''))[:50])

                self._update_system_message(messages)


                result = model.stream_request_llm_with_tools(messages, tools, _stream_callback)

                # Debug output using StreamResult properties
                logger.debug("LLM 返回 StreamResult:")
                logger.debug("  - result_type: %s", result.result_type)
                if result.tool_name:
                    logger.debug("  - tool_name: %s", result.tool_name)
                if result.tool_arguments:
                    args_preview = str(result.tool_arguments)[:100]
                    logger.debug("  - arguments 前100字: %s", args_preview)
                if result.content:
                    logger.debug("  - has content: True")

                # Accumulate token usage
                if result.token_usage is not None:
                    self._token_usage = self._token_usage + result.token_usage

                full_thinking = "".join(thinking_parts).strip()

                # Handle text response
                if result.result_type in ("text", "truncated"):
                    is_truncated = result.result_type == "truncated"
                    final_text = result.content or ""
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
                        # 可观测性：记录 thinking 前 200 字，便于诊断"XML 进 reasoning 未被解析"等情况
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
                        self._start_summary_in_background(self._conversation_id, active_skill_ids)
                        _emit_token_usage()
                        return err

                    # 判断是否为推理/计划文本（而非最终回答）
                    # 方案 A：把 has_called_tool_in_run 传入，强制"调用过工具就走 continue，
                    # 直到 LLM 调 finish 才允许结束"，避免出现"调过工具又用纯文本结束"的不一致状态。
                    is_reasoning = self._is_reasoning_text(final_text, has_called_tool=has_called_tool_in_run)
                    
                    if is_reasoning or is_truncated:
                        # 推理文本或被截断的响应：将文本加入上下文，给 LLM 再一轮机会
                        logger.debug("检测到推理文本或被截断的响应 (长度: %s, truncated: %s, has_called_tool=%s)",
                                     len(final_text), is_truncated, has_called_tool_in_run)
                        if self.memory is not None:
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", final_text, metadata=metadata)
                        # 继续循环，让 LLM 有机会输出工具调用
                        reasoning_turn_count += 1
                        if reasoning_turn_count >= 2:
                            # 超过最大推理轮次，终止并提示
                            logger.warning("LLM 连续 %d 次输出推理文本，终止对话 (has_called_tool=%s)",
                                          reasoning_turn_count, has_called_tool_in_run)
                            if has_called_tool_in_run:
                                # 方案 A：本轮调过工具但 LLM 仍不肯调 finish，
                                # 此时直接结束会违反"调过工具必须用 finish 结束"的规则，
                                # 给出更明确的提示告知用户本次对话未走完正常收尾流程。
                                warning_msg = (
                                    "本次任务已执行工具调用，但助手未能按规则调用 finish 工具完成收尾，"
                                    "对话已被强制结束。如需完整答复，请重新提问或继续追问。"
                                )
                            else:
                                warning_msg = "LLM 未能执行计划，请重新描述您的需求。"
                            if log_callback:
                                log_callback(warning_msg, "assistant")
                            if self.memory is not None:
                                metadata = {"token_usage": asdict(self._token_usage)}
                                self.memory.append_message(self._conversation_id, "assistant", warning_msg, metadata=metadata)
                            self._start_summary_in_background(self._conversation_id, active_skill_ids)
                            _emit_token_usage()
                            return warning_msg
                        continue
                    else:
                        # 正常文本响应：结束对话
                        if self.memory is not None:
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", final_text, metadata=metadata)
                        self._start_summary_in_background(self._conversation_id, active_skill_ids)
                        _emit_token_usage()
                        logger.debug("返回文本内容 (长度: %s)", len(final_text))
                        return final_text

                # Handle error response
                if result.result_type == "error":
                    err = result.error_message or "模型返回未知错误"
                    if log_callback:
                        log_callback(err, "assistant")
                    if self.memory is not None:
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(self._conversation_id, "assistant", err, metadata=metadata)
                    self._start_summary_in_background(self._conversation_id, active_skill_ids)
                    _emit_token_usage()
                    logger.debug("返回错误 (长度: %s)", len(err))
                    return err

                # Handle tool call response
                fname = result.tool_name
                arg_str = result.tool_arguments or "{}"
                try:
                    args = json.loads(arg_str)
                except json.JSONDecodeError:
                    args = {}
                logger.debug("解析工具调用: fname=%s, args keys=%s", fname, list(args.keys()) if isinstance(args, dict) else type(args))

                # 关键修复：full_thinking 不再单独作为一条 assistant(think) 消息持久化，
                # 而是作为 assistant tool_call 消息的 content 一起写入，
                # 避免出现 tool 前面只有 think assistant 而无 tool_calls 的断裂结构。

                if fname == "request_tool_details":
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
                    
                    # 关键修复：通过 _persist_after_tool_turn 同时追加 assistant(tool_calls) + tool(result)
                    if self.memory is not None:
                        self._persist_after_tool_turn(
                            fname,
                            args,
                            tool_result,
                            active_skill_text,
                            active_skill_ids,
                            messages,
                            log_callback,
                            reasoning_content=full_thinking or None,
                            arg_str=arg_str,
                        )
                    else:
                        _call_id = f"call_{uuid.uuid4().hex[:12]}"
                        messages.append({
                            "role": "assistant",
                            "content": full_thinking or None,
                            "tool_calls": [{
                                "id": _call_id,
                                "type": "function",
                                "function": {"name": fname, "arguments": arg_str},
                            }],
                        })
                        messages.append({
                            "role": "tool",
                            "name": fname,
                            "tool_call_id": _call_id,
                            "content": str(tool_result),
                        })
                    
                    if log_callback:
                        found_names = [d.get("name", "") for d in definitions_found]
                        log_callback(f"获取工具定义: {', '.join(found_names)}", "tool")
                        log_callback(str(tool_result), "base_tool")
                    
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
                                    reasoning_content=full_thinking or None,
                                    arg_str=json.dumps(ask_args, ensure_ascii=False),
                                )
                            else:
                                self._append_tool_pair(
                                    "ask_user", ask_args, str(result), messages,
                                    reasoning_content=full_thinking or None,
                                )
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
                                reasoning_content=full_thinking or None,
                                arg_str=json.dumps(ask_args, ensure_ascii=False),
                            )
                        else:
                            self._append_tool_pair(
                                "ask_user", ask_args, str(result), messages,
                                reasoning_content=full_thinking or None,
                            )
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
                                reasoning_content=full_thinking or None,
                                arg_str=json.dumps(ask_args, ensure_ascii=False),
                            )
                        else:
                            self._append_tool_pair(
                                "ask_user", ask_args, str(result), messages,
                                reasoning_content=full_thinking or None,
                            )
                        if log_callback:
                            log_callback(_ask_user_ui_log_payload(ask_args), "await_user")
                        _emit_token_usage()
                        return SKILL_AGENT_AWAITING_USER_REPLY
                
                logger.debug("准备执行工具: %s", fname)
                if fname == "run_command":
                    cmd = str(args.get("command", ""))[:80]
                    logger.debug("  命令: %s...", cmd)

                # 检测重复工具调用（可通过配置禁用）
                _control_tools = ("select_skill", "finish", "ask_user", "load_skill_memory")
                is_repeated = False
                repeat_warning = None
                last_result = None

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

                    # 方案 A：标记本轮已调用过工具（含 finish/ask_user/select_skill 等控制工具），
                    # 用于下方判断是否允许 LLM 用纯文本直接结束。
                    has_called_tool_in_run = True

                    if fname not in _control_tools:
                        self._record_tool_call(fname, args, str(result))

                # 标准化工具返回结果格式（排除控制类工具和已经是标准格式的结果）
                if fname not in ("select_skill", "finish", "ask_user", "load_skill_memory"):
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

                logger.debug("工具执行完成:")
                logger.debug("  - result 长度: %s", len(str(result)))
                logger.debug("  - result 前100字: %s", str(result)[:100])
                logger.debug("  - terminate: %s", terminate)
                logger.debug("  - final: %s", final is not None)

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
                                logger.debug("检测到写入操作: %s...", command[:80])
                                file_path = self._extract_file_path(command)
                                if file_path:
                                    logger.debug("提取到文件路径: %s", file_path)
                                    check_result = self._verify_file_exists(file_path, args.get("cwd", "."))
                                    if log_callback:
                                        log_callback(f"检查结果: {check_result}", "base_tool")
                                    r = r + "\n\n" + check_result
                                    result = r
                                    logger.debug("验证结果已合并到工具结果")
                                else:
                                    logger.debug("无法提取文件路径，跳过验证")
                        
                        # 写入操作特例检测（保留原有逻辑）
                        # 此检测与通用重复检测协同工作，专门针对写入操作提供更严格的保护
                        auto_end_msg = self._check_repeated_write_success(command, str(result))
                        if auto_end_msg:
                            logger.debug(f"检测到重复写入，自动结束: {auto_end_msg}")
                            log_callback(auto_end_msg, "assistant")
                            metadata = {"token_usage": asdict(self._token_usage)}
                            self.memory.append_message(self._conversation_id, "assistant", auto_end_msg, metadata=metadata)
                            self._start_summary_in_background(self._conversation_id, active_skill_ids)
                            _emit_token_usage()
                            return auto_end_msg
                    log_callback(r, "base_tool")

                if terminate and final is not None:
                    # 关键修复：终止型工具（如 finish）也要先追加 assistant(tool_calls)+tool 完整序列
                    if self.memory is not None:
                        self._persist_after_tool_turn(
                            fname,
                            args,
                            str(result),
                            active_skill_text,
                            active_skill_ids,
                            messages,
                            log_callback,
                            reasoning_content=full_thinking or None,
                            arg_str=arg_str,
                        )
                        cid = self._conversation_id
                        metadata = {"token_usage": asdict(self._token_usage)}
                        self.memory.append_message(cid, "assistant", str(final), metadata=metadata)
                    else:
                        _call_id = f"call_{uuid.uuid4().hex[:12]}"
                        messages.append({
                            "role": "assistant",
                            "content": full_thinking or None,
                            "tool_calls": [{
                                "id": _call_id,
                                "type": "function",
                                "function": {"name": fname, "arguments": arg_str},
                            }],
                        })
                        messages.append({
                            "role": "tool",
                            "name": fname,
                            "tool_call_id": _call_id,
                            "content": str(result),
                        })
                    self._start_summary_in_background(self._conversation_id, active_skill_ids)
                    if log_callback:
                        log_callback(str(final), "assistant")
                    _emit_token_usage()
                    logger.debug(f"工具要求终止 (terminate=True), 返回 final (长度: {len(str(final))})")
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
                            reasoning_content=full_thinking or None,
                            arg_str=arg_str,
                        )
                    else:
                        _call_id = f"call_{uuid.uuid4().hex[:12]}"
                        messages.append({
                            "role": "assistant",
                            "content": full_thinking or None,
                            "tool_calls": [{
                                "id": _call_id,
                                "type": "function",
                                "function": {"name": fname, "arguments": arg_str},
                            }],
                        })
                        messages.append({
                            "role": "tool",
                            "name": fname,
                            "tool_call_id": _call_id,
                            "content": str(result),
                        })
                    if log_callback:
                        log_callback(_ask_user_ui_log_payload(args), "await_user")
                    _emit_token_usage()
                    logger.debug("等待用户回复 (ask_user)")
                    return SKILL_AGENT_AWAITING_USER_REPLY

                if self.memory is not None:
                    self._persist_after_tool_turn(
                        fname,
                        args,
                        str(result),
                        active_skill_text,
                        active_skill_ids,
                        messages,
                        log_callback,
                        reasoning_content=full_thinking or None,
                        arg_str=arg_str,
                    )
                else:
                    _call_id = f"call_{uuid.uuid4().hex[:12]}"
                    messages.append({
                        "role": "assistant",
                        "content": full_thinking or None,
                        "tool_calls": [{
                            "id": _call_id,
                            "type": "function",
                            "function": {"name": fname, "arguments": arg_str},
                        }],
                    })
                    messages.append({
                        "role": "tool",
                        "name": fname,
                        "tool_call_id": _call_id,
                        "content": str(result),
                    })
                    if fname == "select_skill" and active_skill_text and not str(result).startswith("错误"):
                        active_skills_text = self._build_active_skills_text(active_skill_text, active_skill_ids)
                        self._dynamic_prompt.update_active_skills(active_skills_text)
                        for i, msg in enumerate(messages):
                            if msg.get("role") == "system":
                                messages[i] = {"role": "system", "content": self._dynamic_prompt.build()}
                                logger.debug("更新系统提示词_dynamic_prompt：%s", self._dynamic_prompt.build())
                                break

            logger.debug(f"达到最大步数限制 ({self.max_steps})，退出循环")
            tail = f"已达到最大执行步数限制（{self.max_steps}），已停止。"
            if log_callback:
                log_callback(tail, "assistant")
            if self.memory is not None:
                metadata = {"token_usage": asdict(self._token_usage)}
                self.memory.append_message(self._conversation_id, "assistant", tail, metadata=metadata)
            self._start_summary_in_background(self._conversation_id, active_skill_ids)
            _emit_token_usage()
            logger.debug("正常退出循环，返回 tail 消息")
            return tail
        
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
            
            try:
                self._start_summary_in_background(self._conversation_id, active_skill_ids)
            except Exception as summary_err:
                logger.warning(f"尝试启动总结线程时出错: {summary_err}")
            
            _emit_token_usage()
            logger.debug("异常退出，返回 err_msg")
            return err_msg
        finally:
            self._uploaded_files_content = {"text_content": "", "images": []}
            # 重置计划确认标志（pending_plan 不清空，供续跑使用；下次首次规划会覆盖）
            self._plan_confirmed = False
            logger.debug("===== run() 结束执行 =====")
