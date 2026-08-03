"""SkillAgent 结构化事件系统模块。

本模块定义了 SkillAgent 运行过程中产生的各类事件类型、事件数据结构
以及消息队列模式，用于支撑 Agent 生命周期的事件驱动架构。
"""

import time
from dataclasses import dataclass, field
from enum import Enum


class AgentEventType(Enum):
    """Agent 事件类型枚举。

    枚举值覆盖了 Agent 从启动到结束的完整生命周期，
    包括轮次控制、工具执行、消息更新、外部干预及错误等场景。

    Attributes:
        AGENT_START: Agent 启动事件，在 Agent 开始运行时触发。
        AGENT_END: Agent 结束事件，在 Agent 完成所有工作后触发。
        TURN_START: 轮次开始事件，在每一轮推理/执行开始时触发。
        TURN_END: 轮次结束事件，在每一轮推理/执行完成时触发。
        TOOL_EXECUTE_START: 工具执行开始事件，在调用工具前触发。
        TOOL_EXECUTE_END: 工具执行结束事件，在工具调用返回后触发。
        MESSAGE_UPDATE: 消息更新事件，在消息内容发生变更时触发。
        STEERING_RECEIVED: 接收到导向指令事件，当外部下发导向/修正指令时触发。
        FOLLOWUP_RECEIVED: 接收到后续指令事件，当外部下发后续补充指令时触发。
        ERROR: 错误事件，在运行过程中发生异常时触发。
    """

    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    TOOL_EXECUTE_START = "tool_execute_start"
    TOOL_EXECUTE_END = "tool_execute_end"
    MESSAGE_UPDATE = "message_update"
    STEERING_RECEIVED = "steering_received"
    FOLLOWUP_RECEIVED = "followup_received"
    ERROR = "error"


@dataclass
class AgentEvent:
    """Agent 事件数据类。

    封装事件类型、时间戳、事件附加数据及所属会话标识，
    作为 Agent 事件系统中传递的标准数据单元。

    Attributes:
        event_type: 事件类型，标识本事件的具体类别。
        timestamp: 事件产生的时间戳，默认为当前时间（time.time()）。
        data: 事件附加数据字典，包含与事件类型相关的具体信息，
              例如 tool_name（工具名称）、step_number（步骤编号）、
              message_content（消息内容）等。
        conversation_id: 所属会话的唯一标识符，默认为空字符串。
    """

    event_type: AgentEventType
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)
    conversation_id: str = ""


class QueueMode(Enum):
    """消息队列模式枚举。

    定义了事件/消息在队列中的消费策略。

    Attributes:
        ALL: 一次性发送队列中的所有消息，适用于批量处理场景。
        ONE_AT_A_TIME: 逐条处理队列中的消息，适用于需要严格顺序控制的场景。
    """

    ALL = "all"
    ONE_AT_A_TIME = "one_at_a_time"
