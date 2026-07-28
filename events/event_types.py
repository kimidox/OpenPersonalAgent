"""
事件类型定义

定义系统中所有的事件类型，分类组织。
"""
from enum import Enum, auto
from typing import Dict, Any, Optional


class EventPriority(Enum):
    """事件优先级"""
    LOW = 1      # 低优先级，如日志、统计
    NORMAL = 5   # 普通优先级，默认值
    HIGH = 10    # 高优先级，如用户交互、错误处理
    CRITICAL = 20  # 关键优先级，如系统错误、紧急通知


class EventData:
    """事件数据基类"""

    def __init__(
        self,
        source: str,
        data: Dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        初始化事件数据

        Args:
            source: 事件源（发布者标识）
            data: 事件负载数据
            priority: 事件优先级
            metadata: 额外元数据（可选）
        """
        self.source = source
        self.data = data
        self.priority = priority
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "source": self.source,
            "data": self.data,
            "priority": self.priority.value,
            "metadata": self.metadata
        }


class EventType(str, Enum):
    """事件类型枚举"""

    # ==================== Agent 事件 ====================
    # LLM 相关
    LLM_REQUEST_START = "llm_request_start"              # 开始请求 LLM
    LLM_RESPONSE_STREAM = "llm_response_stream"          # LLM 响应流式数据
    LLM_RESPONSE_COMPLETE = "llm_response_complete"      # LLM 响应完成
    LLM_ERROR = "llm_error"                              # LLM 错误

    # 工具调用相关
    TOOL_CALL_START = "tool_call_start"                  # 工具调用开始
    TOOL_CALL_STREAM = "tool_call_stream"                # 工具调用流式数据
    TOOL_CALL_COMPLETE = "tool_call_complete"            # 工具调用完成
    TOOL_ERROR = "tool_error"                            # 工具执行错误

    # Agent 状态
    AGENT_STATE_CHANGE = "agent_state_change"            # Agent 状态变化
    AGENT_ERROR = "agent_error"                          # Agent 错误
    AGENT_STOP_REQUEST = "agent_stop_request"            # 请求停止 Agent

    # Token 使用统计
    TOKEN_USAGE_UPDATE = "token_usage_update"            # Token 使用更新

    # ==================== UI 事件 ====================
    # 消息显示
    MESSAGE_APPEND = "message_append"                    # 追加消息
    MESSAGE_UPDATE = "message_update"                    # 更新消息
    MESSAGE_CLEAR = "message_clear"                      # 清空消息

    # UI 状态
    UI_STATE_CHANGE = "ui_state_change"                  # UI 状态变化
    THEME_CHANGE = "theme_change"                        # 主题变化
    INPUT_ENABLE_CHANGE = "input_enable_change"          # 输入框启用状态变化

    # 用户交互
    USER_INPUT_SUBMIT = "user_input_submit"              # 用户提交输入
    USER_ACTION_TRIGGER = "user_action_trigger"          # 用户触发动作

    # ==================== IPC 事件 ====================
    # 主进程 <-> 悬浮球进程
    IPC_SHOW_MAIN_WINDOW = "ipc_show_main_window"        # 显示主窗口
    IPC_TOGGLE_CHAT = "ipc_toggle_chat"                  # 切换聊天窗口
    IPC_START_RECORDING = "ipc_start_recording"          # 开始录音
    IPC_STOP_RECORDING = "ipc_stop_recording"            # 停止录音
    IPC_QUIT_APPLICATION = "ipc_quit_application"        # 退出应用
    IPC_CHAT_MESSAGE = "ipc_chat_message"                # 聊天消息

    # LLM 状态管理
    IPC_LLM_STATE_UPDATE = "ipc_llm_state_update"        # LLM状态更新
    IPC_LLM_STATE_WARNING = "ipc_llm_state_warning"      # LLM状态告警

    # ==================== 系统事件 ====================
    # 文件处理
    FILE_UPLOAD = "file_upload"                          # 文件上传
    FILE_PROCESS_COMPLETE = "file_process_complete"      # 文件处理完成

    # 录音相关
    RECORDING_START = "recording_start"                  # 开始录音
    RECORDING_STOP = "recording_stop"                    # 停止录音
    RECORDING_TEXT_UPDATE = "recording_text_update"      # 录音文本更新

    # 定时任务
    SCHEDULED_TASK_TRIGGER = "scheduled_task_trigger"    # 定时任务触发

    # ==================== 性能监控事件 ====================
    PERFORMANCE_METRIC = "performance_metric"            # 性能指标
    ERROR_OCCURRED = "error_occurred"                    # 错误发生
    RECOVERY_ATTEMPT = "recovery_attempt"                # 恢复尝试

    @classmethod
    def from_string(cls, value: str) -> 'EventType':
        """从字符串转换"""
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"Unknown event type: {value}")