"""
性能指标定义和数据模型

定义了系统各个方面的性能指标，包括：
- 启动时间
- 响应延迟
- 资源占用
- 业务指标
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class MetricType(Enum):
    """指标类型"""
    STARTUP = "startup"              # 启动时间
    RESPONSE = "response"            # 响应延迟
    RESOURCE = "resource"            # 资源占用
    THROUGHPUT = "throughput"        # 吞吐量
    SUCCESS_RATE = "success_rate"    # 成功率
    USER_EXPERIENCE = "user_experience"  # 用户体验


class MetricCategory(Enum):
    """指标分类"""
    APPLICATION = "application"      # 应用级
    UI = "ui"                        # UI 交互
    LLM = "llm"                      # LLM 调用
    IPC = "ipc"                      # IPC 通信
    SYSTEM = "system"                # 系统资源


@dataclass
class MetricValue:
    """指标值"""
    name: str
    value: float
    unit: str  # ms, MB, %, count 等
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class StartupMetrics:
    """启动时间指标"""
    # 应用启动时间
    app_startup_ms: float = 0.0
    # 悬浮球启动时间
    ball_startup_ms: float = 0.0
    # 数据库初始化时间
    db_init_ms: float = 0.0
    # 模型加载时间
    model_load_ms: float = 0.0
    # UI 初始化时间
    ui_init_ms: float = 0.0

    def to_metric_values(self) -> List[MetricValue]:
        """转换为指标值列表"""
        return [
            MetricValue("app_startup_ms", self.app_startup_ms, "ms", tags={"category": "startup"}),
            MetricValue("ball_startup_ms", self.ball_startup_ms, "ms", tags={"category": "startup"}),
            MetricValue("db_init_ms", self.db_init_ms, "ms", tags={"category": "startup"}),
            MetricValue("model_load_ms", self.model_load_ms, "ms", tags={"category": "startup"}),
            MetricValue("ui_init_ms", self.ui_init_ms, "ms", tags={"category": "startup"}),
        ]


@dataclass
class ResponseMetrics:
    """响应延迟指标"""
    # UI 响应延迟
    ui_response_ms: float = 0.0
    # LLM 首字延迟
    llm_first_token_ms: float = 0.0
    # LLM 完成延迟
    llm_completion_ms: float = 0.0
    # IPC 消息延迟
    ipc_latency_ms: float = 0.0
    # 工具执行延迟
    tool_execution_ms: float = 0.0

    def to_metric_values(self) -> List[MetricValue]:
        """转换为指标值列表"""
        return [
            MetricValue("ui_response_ms", self.ui_response_ms, "ms", tags={"category": "response"}),
            MetricValue("llm_first_token_ms", self.llm_first_token_ms, "ms", tags={"category": "response"}),
            MetricValue("llm_completion_ms", self.llm_completion_ms, "ms", tags={"category": "response"}),
            MetricValue("ipc_latency_ms", self.ipc_latency_ms, "ms", tags={"category": "response"}),
            MetricValue("tool_execution_ms", self.tool_execution_ms, "ms", tags={"category": "response"}),
        ]


@dataclass
class ResourceMetrics:
    """资源占用指标"""
    # CPU 使用率 (%)
    cpu_percent: float = 0.0
    # 内存使用 (MB)
    memory_mb: float = 0.0
    # 内存使用率 (%)
    memory_percent: float = 0.0
    # 磁盘读取速度 (MB/s)
    disk_read_mb_s: float = 0.0
    # 磁盘写入速度 (MB/s)
    disk_write_mb_s: float = 0.0
    # 网络接收速度 (MB/s)
    net_recv_mb_s: float = 0.0
    # 网络发送速度 (MB/s)
    net_sent_mb_s: float = 0.0

    def to_metric_values(self) -> List[MetricValue]:
        """转换为指标值列表"""
        return [
            MetricValue("cpu_percent", self.cpu_percent, "%", tags={"category": "resource"}),
            MetricValue("memory_mb", self.memory_mb, "MB", tags={"category": "resource"}),
            MetricValue("memory_percent", self.memory_percent, "%", tags={"category": "resource"}),
            MetricValue("disk_read_mb_s", self.disk_read_mb_s, "MB/s", tags={"category": "resource"}),
            MetricValue("disk_write_mb_s", self.disk_write_mb_s, "MB/s", tags={"category": "resource"}),
            MetricValue("net_recv_mb_s", self.net_recv_mb_s, "MB/s", tags={"category": "resource"}),
            MetricValue("net_sent_mb_s", self.net_sent_mb_s, "MB/s", tags={"category": "resource"}),
        ]


@dataclass
class ThroughputMetrics:
    """吞吐量指标"""
    # IPC 吞吐量（消息/秒）
    ipc_msg_per_sec: float = 0.0
    # IPC 字节吞吐量（MB/s）
    ipc_bytes_per_sec: float = 0.0
    # LLM 调用吞吐量（请求/秒）
    llm_requests_per_sec: float = 0.0
    # Token 生成速度（token/s）
    token_per_sec: float = 0.0
    # 工具执行吞吐量（次/秒）
    tool_executions_per_sec: float = 0.0

    def to_metric_values(self) -> List[MetricValue]:
        """转换为指标值列表"""
        return [
            MetricValue("ipc_msg_per_sec", self.ipc_msg_per_sec, "msg/s", tags={"category": "throughput"}),
            MetricValue("ipc_bytes_per_sec", self.ipc_bytes_per_sec, "MB/s", tags={"category": "throughput"}),
            MetricValue("llm_requests_per_sec", self.llm_requests_per_sec, "req/s", tags={"category": "throughput"}),
            MetricValue("token_per_sec", self.token_per_sec, "token/s", tags={"category": "throughput"}),
            MetricValue("tool_executions_per_sec", self.tool_executions_per_sec, "exec/s", tags={"category": "throughput"}),
        ]


@dataclass
class SuccessRateMetrics:
    """成功率指标"""
    # LLM 调用成功率
    llm_success_rate: float = 100.0
    # 工具执行成功率
    tool_success_rate: float = 100.0
    # IPC 通信成功率
    ipc_success_rate: float = 100.0
    # ASR 识别成功率
    asr_success_rate: float = 100.0
    # TTS 转换成功率
    tts_success_rate: float = 100.0

    def to_metric_values(self) -> List[MetricValue]:
        """转换为指标值列表"""
        return [
            MetricValue("llm_success_rate", self.llm_success_rate, "%", tags={"category": "success_rate"}),
            MetricValue("tool_success_rate", self.tool_success_rate, "%", tags={"category": "success_rate"}),
            MetricValue("ipc_success_rate", self.ipc_success_rate, "%", tags={"category": "success_rate"}),
            MetricValue("asr_success_rate", self.asr_success_rate, "%", tags={"category": "success_rate"}),
            MetricValue("tts_success_rate", self.tts_success_rate, "%", tags={"category": "success_rate"}),
        ]


@dataclass
class UserExperienceMetrics:
    """用户体验指标"""
    # 用户操作响应时间（从操作到界面更新的时间）
    user_op_response_ms: float = 0.0
    # 消息发送到显示的时间
    msg_send_to_display_ms: float = 0.0
    # 语音识别到文本显示的时间
    asr_to_text_ms: float = 0.0
    # TTS 播放延迟
    tts_play_delay_ms: float = 0.0
    # 页面切换延迟
    page_switch_ms: float = 0.0

    def to_metric_values(self) -> List[MetricValue]:
        """转换为指标值列表"""
        return [
            MetricValue("user_op_response_ms", self.user_op_response_ms, "ms", tags={"category": "user_experience"}),
            MetricValue("msg_send_to_display_ms", self.msg_send_to_display_ms, "ms", tags={"category": "user_experience"}),
            MetricValue("asr_to_text_ms", self.asr_to_text_ms, "ms", tags={"category": "user_experience"}),
            MetricValue("tts_play_delay_ms", self.tts_play_delay_ms, "ms", tags={"category": "user_experience"}),
            MetricValue("page_switch_ms", self.page_switch_ms, "ms", tags={"category": "user_experience"}),
        ]


@dataclass
class PerformanceSnapshot:
    """性能快照"""
    timestamp: float = field(default_factory=time.time)
    startup: StartupMetrics = field(default_factory=StartupMetrics)
    response: ResponseMetrics = field(default_factory=ResponseMetrics)
    resource: ResourceMetrics = field(default_factory=ResourceMetrics)
    throughput: ThroughputMetrics = field(default_factory=ThroughputMetrics)
    success_rate: SuccessRateMetrics = field(default_factory=SuccessRateMetrics)
    user_experience: UserExperienceMetrics = field(default_factory=UserExperienceMetrics)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp,
            "startup": {m.name: m.value for m in self.startup.to_metric_values()},
            "response": {m.name: m.value for m in self.response.to_metric_values()},
            "resource": {m.name: m.value for m in self.resource.to_metric_values()},
            "throughput": {m.name: m.value for m in self.throughput.to_metric_values()},
            "success_rate": {m.name: m.value for m in self.success_rate.to_metric_values()},
            "user_experience": {m.name: m.value for m in self.user_experience.to_metric_values()},
        }

    def get_all_metrics(self) -> List[MetricValue]:
        """获取所有指标值"""
        return (
            self.startup.to_metric_values() +
            self.response.to_metric_values() +
            self.resource.to_metric_values() +
            self.throughput.to_metric_values() +
            self.success_rate.to_metric_values() +
            self.user_experience.to_metric_values()
        )