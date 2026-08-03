"""
ConversationViewModel — 对话相关业务逻辑的 ViewModel 层

封装 SkillAgent 的对话操作，使 UI 层（Mixin / MainWindow）
不直接依赖 SkillAgent 的内部实现细节。
"""
from __future__ import annotations

import json
from typing import Any, Callable, TYPE_CHECKING

from logger import get_logger
from ui_flet.utils.message_utils import try_parse_json_content

if TYPE_CHECKING:
    from skill_agent import SkillAgent
    from memory import SqliteMemory


class ConversationViewModel:
    """
    对话 ViewModel

    职责：
    - 创建 / 切换 / 列出 / 删除会话
    - 获取历史消息记录
    - 发送消息（内部启动 SkillAgent 工作线程）
    - 中断对话

    UI 层通过此 ViewModel 与 SkillAgent 交互，不直接访问 SkillAgent。
    """

    def __init__(
        self,
        skill_agent: SkillAgent | None = None,
        memory: SqliteMemory | None = None,
    ) -> None:
        self._skill_agent = skill_agent
        self._memory = memory
        self._logger = get_logger()

        # ---------- 回调（供 UI 订阅） ----------
        # 消息接收回调：签名 (message: str, msg_type: str, conversation_id: str) -> None
        self.on_message_received: Callable[[str, str, str], Any] | None = None
        # 工作完成回调：签名 (result: str, conversation_id: str) -> None
        self.on_worker_finished: Callable[[str, str], Any] | None = None

    # ==================================================================
    # SkillAgent 引用管理
    # ==================================================================

    def set_skill_agent(self, agent: SkillAgent | None) -> None:
        """设置 / 替换 SkillAgent 实例（供初始化或热替换）"""
        self._skill_agent = agent

    def set_memory(self, memory: SqliteMemory | None) -> None:
        """设置 Memory 实例"""
        self._memory = memory

    @property
    def skill_agent(self) -> SkillAgent | None:
        """只读属性：获取 SkillAgent（仅限 ViewModel 内部与极少数桥接场景）"""
        return self._skill_agent

    @property
    def is_available(self) -> bool:
        """SkillAgent 是否可用"""
        return self._skill_agent is not None

    # ==================================================================
    # 会话管理
    # ==================================================================

    def start_new_conversation(
        self,
        *,
        conversation_type: str = "agent_conversation",
        default_skills: list[dict] | None = None,
    ) -> tuple[str, str] | None:
        """
        创建新会话

        Returns:
            (conversation_id, title) 或 None（失败时）
        """
        if not self._skill_agent:
            self._logger.error("SkillAgent 未初始化，无法创建会话")
            return None
        try:
            conversation_id, title = self._skill_agent.start_new_conversation(
                conversation_type=conversation_type,
                default_skills=default_skills,
            )
            self._logger.info(f"ViewModel 创建新会话: {conversation_id}")
            return conversation_id, title
        except Exception as e:
            self._logger.exception(f"ViewModel 创建新会话失败: {e}")
            return None

    def set_conversation_id(self, conversation_id: str) -> None:
        """设置当前会话 ID"""
        if self._skill_agent:
            self._skill_agent.set_conversation_id(conversation_id)

    def list_saved_conversations(self) -> list[Any]:
        """列出所有已保存的会话"""
        if not self._skill_agent:
            return []
        return self._skill_agent.list_saved_conversations()

    def message_records_for_conversation(self, conversation_id: str) -> list[dict]:
        """获取指定会话的消息记录"""
        if not self._skill_agent:
            return []
        return self._skill_agent.message_records_for_conversation(conversation_id)

    # ==================================================================
    # 消息发送与中断
    # ==================================================================

    def send_message(
        self,
        query: str,
        conversation_id: str,
        log_callback: Callable[[str, str], Any] | None = None,
        stop_check_callback: Callable[[], bool] | None = None,
    ) -> str:
        """
        发送消息并运行 SkillAgent

        Args:
            query: 用户输入
            conversation_id: 会话 ID
            log_callback: 日志回调（消息类型, 内容）
            stop_check_callback: 停止检查回调

        Returns:
            SkillAgent.run() 的结果
        """
        if not self._skill_agent:
            self._logger.error("SkillAgent 未初始化，无法发送消息")
            return ""
        return self._skill_agent.run(
            query,
            log_callback=log_callback,
            stop_check_callback=stop_check_callback,
        )

    def abort(self) -> None:
        """中断当前对话"""
        if self._skill_agent:
            self._skill_agent.request_stop()
            self._logger.info("ViewModel 请求中断对话")

    def set_enable_thinking(self, enabled: bool) -> None:
        """设置思考模式"""
        if self._skill_agent:
            self._skill_agent.set_enable_thinking(enabled)

    def set_uploaded_files_content(self, content: str | dict) -> None:
        """设置上传文件内容"""
        if self._skill_agent:
            self._skill_agent.set_uploaded_files_content(content)

    # ==================================================================
    # 历史消息解析（静态工具方法，供 UI 层复用）
    # ==================================================================

    @staticmethod
    def parse_message_content(raw_content: Any) -> Any:
        """
        解析消息内容，支持多模态格式

        Args:
            raw_content: 原始消息内容（可能是 str / list / None）

        Returns:
            解析后的内容（str 或 list）
        """
        if raw_content is None:
            return ""
        if isinstance(raw_content, list):
            return raw_content
        if isinstance(raw_content, str):
            parsed = try_parse_json_content(raw_content)
            if isinstance(parsed, list):
                return parsed
            return raw_content
        return str(raw_content)

    @staticmethod
    def build_tool_call_display_text(metadata: dict) -> str:
        """
        根据 metadata 构建 tool_call 消息的展示文本

        Args:
            metadata: 消息元数据

        Returns:
            展示文本
        """
        tool_name = str(metadata.get("name", "") or "")
        args_value = metadata.get("args", "")
        if isinstance(args_value, (dict, list)):
            args_str = json.dumps(args_value, ensure_ascii=False)
        else:
            args_str = str(args_value or "")
        if tool_name:
            return f"调用工具 `{tool_name}` · {args_str}" if args_str else f"调用工具 `{tool_name}`"
        return "调用工具"

    @staticmethod
    def classify_message_type(role: str, metadata: dict) -> str | None:
        """
        根据 role 和 metadata 判断消息类型

        Returns:
            "user" / "assistant" / "think" / "tool_call" / "tool" / None（跳过）
        """
        if role == "user":
            return "user"
        elif role == "assistant":
            msg_type = metadata.get("type", "assistant")
            if msg_type in ("assistant", "think", "tool_call"):
                return msg_type
            return "assistant"
        elif role == "tool":
            return "tool"
        return None
