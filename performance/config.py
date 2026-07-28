"""
性能监控配置

定义性能基线阈值和告警规则
"""
from typing import Dict, Any


class PerformanceConfig:
    """性能配置"""

    # ===== 启动时间基线（毫秒）=====
    STARTUP_BASELINE = {
        "app_startup_ms": 3000.0,      # 应用启动不超过 3 秒
        "ball_startup_ms": 500.0,      # 悬浮球启动不超过 500ms
        "db_init_ms": 500.0,           # 数据库初始化不超过 500ms
        "model_load_ms": 2000.0,       # 模型加载不超过 2 秒
        "ui_init_ms": 1000.0,          # UI 初始化不超过 1 秒
    }

    # ===== 响应延迟基线（毫秒）=====
    RESPONSE_BASELINE = {
        "ui_response_ms": 100.0,           # UI 响应不超过 100ms
        "llm_first_token_ms": 500.0,       # LLM 首字延迟不超过 500ms
        "llm_completion_ms": 3000.0,       # LLM 完成延迟不超过 3 秒
        "ipc_latency_ms": 50.0,            # IPC 延迟不超过 50ms
        "tool_execution_ms": 2000.0,       # 工具执行不超过 2 秒
    }

    # ===== 资源占用基线 =====
    RESOURCE_BASELINE = {
        "cpu_percent": 30.0,           # CPU 使用率不超过 30%
        "memory_mb": 500.0,            # 内存使用不超过 500MB
        "memory_percent": 20.0,        # 内存使用率不超过 20%
        "disk_read_mb_s": 10.0,        # 磁盘读取不超过 10MB/s
        "disk_write_mb_s": 10.0,       # 磁盘写入不超过 10MB/s
        "net_recv_mb_s": 5.0,          # 网络接收不超过 5MB/s
        "net_sent_mb_s": 5.0,          # 网络发送不超过 5MB/s
    }

    # ===== 吞吐量基线 =====
    THROUGHPUT_BASELINE = {
        "ipc_msg_per_sec": 100.0,          # IPC 吞吐量至少 100 消息/秒
        "ipc_bytes_per_sec": 1.0,          # IPC 字节吞吐量至少 1MB/s
        "llm_requests_per_sec": 0.5,       # LLM 吞吐量至少 0.5 请求/秒
        "token_per_sec": 10.0,             # Token 生成速度至少 10 token/s
        "tool_executions_per_sec": 0.2,    # 工具执行吞吐量至少 0.2 次/秒
    }

    # ===== 成功率基线（%）=====
    SUCCESS_RATE_BASELINE = {
        "llm_success_rate": 95.0,          # LLM 成功率至少 95%
        "tool_success_rate": 90.0,         # 工具成功率至少 90%
        "ipc_success_rate": 99.0,          # IPC 成功率至少 99%
        "asr_success_rate": 90.0,          # ASR 成功率至少 90%
        "tts_success_rate": 95.0,          # TTS 成功率至少 95%
    }

    # ===== 用户体验基线（毫秒）=====
    USER_EXPERIENCE_BASELINE = {
        "user_op_response_ms": 200.0,      # 用户操作响应不超过 200ms
        "msg_send_to_display_ms": 100.0,   # 消息发送到显示不超过 100ms
        "asr_to_text_ms": 500.0,           # ASR 到文本不超过 500ms
        "tts_play_delay_ms": 200.0,        # TTS 播放延迟不超过 200ms
        "page_switch_ms": 150.0,           # 页面切换不超过 150ms
    }

    # ===== 告警阈值系数 =====
    # 当指标值超过基线值 * WARNING_THRESHOLD 时发出告警
    WARNING_THRESHOLD = 1.5    # 超过基线 50% 发出警告
    CRITICAL_THRESHOLD = 2.0   # 超过基线 100% 发出严重告警

    # ===== 采集配置 =====
    SAMPLE_INTERVAL_SECONDS = 5.0     # 资源采样间隔（秒）
    REPORT_INTERVAL_SECONDS = 60.0    # 报告生成间隔（秒）
    HISTORY_RETENTION_HOURS = 24      # 历史数据保留时间（小时）

    # ===== 告警配置 =====
    ALERT_COOLDOWN_SECONDS = 300      # 同一告警冷却时间（秒）
    MAX_ALERTS_PER_HOUR = 20          # 每小时最大告警数

    @classmethod
    def get_all_baselines(cls) -> Dict[str, float]:
        """获取所有基线值"""
        return {
            **cls.STARTUP_BASELINE,
            **cls.RESPONSE_BASELINE,
            **cls.RESOURCE_BASELINE,
            **cls.THROUGHPUT_BASELINE,
            **cls.SUCCESS_RATE_BASELINE,
            **cls.USER_EXPERIENCE_BASELINE,
        }

    @classmethod
    def get_threshold(cls, metric_name: str) -> tuple[float, float]:
        """
        获取指标的告警阈值

        Returns:
            (warning_threshold, critical_threshold)
        """
        baseline = cls.get_all_baselines().get(metric_name, 0.0)
        return (
            baseline * cls.WARNING_THRESHOLD,
            baseline * cls.CRITICAL_THRESHOLD,
        )

    @classmethod
    def is_lower_better(cls, metric_name: str) -> bool:
        """
        判断指标是否越小越好

        Returns:
            True 表示越小越好（如延迟、资源占用）
            False 表示越大越好（如吞吐量、成功率）
        """
        # 吞吐量和成功率越大越好
        higher_better = [
            "ipc_msg_per_sec", "ipc_bytes_per_sec",
            "llm_requests_per_sec", "token_per_sec", "tool_executions_per_sec",
            "llm_success_rate", "tool_success_rate", "ipc_success_rate",
            "asr_success_rate", "tts_success_rate",
        ]
        return metric_name not in higher_better