"""
性能监控模块

提供完整的性能监控体系，包括：
- 性能指标定义和采集
- 资源监控（CPU、内存、磁盘、网络）
- 时间跟踪（context manager）
- 性能基线和告警
- 性能报告生成

使用示例：
    # 启动性能监控
    from performance import start_monitoring, track_time, record_success

    start_monitoring()

    # 跟踪执行时间
    with track_time("llm_call", model="gpt-4"):
        result = llm.chat(...)

    # 记录成功/失败
    record_success("llm")

    # 获取性能指标
    from performance import get_monitor
    monitor = get_monitor()
    metrics = monitor.get_current_metrics()
"""

# 核心模块
from .metrics import (
    MetricType,
    MetricCategory,
    MetricValue,
    StartupMetrics,
    ResponseMetrics,
    ResourceMetrics,
    ThroughputMetrics,
    SuccessRateMetrics,
    UserExperienceMetrics,
    PerformanceSnapshot,
)

from .config import PerformanceConfig

from .collector import (
    ResourceMonitor,
    TimingCollector,
    PerformanceCollector,
    get_collector,
    track_time,
    record_success,
    record_failure,
)

from .monitor import (
    AlertLevel,
    Alert,
    AlertManager,
    PerformanceMonitor,
    get_monitor,
    start_monitoring,
    stop_monitoring,
)

from .reporter import (
    PerformanceReporter,
    generate_and_save_daily_report,
    generate_and_save_weekly_report,
)


__all__ = [
    # 指标定义
    "MetricType",
    "MetricCategory",
    "MetricValue",
    "StartupMetrics",
    "ResponseMetrics",
    "ResourceMetrics",
    "ThroughputMetrics",
    "SuccessRateMetrics",
    "UserExperienceMetrics",
    "PerformanceSnapshot",

    # 配置
    "PerformanceConfig",

    # 采集器
    "ResourceMonitor",
    "TimingCollector",
    "PerformanceCollector",
    "get_collector",
    "track_time",
    "record_success",
    "record_failure",

    # 监控
    "AlertLevel",
    "Alert",
    "AlertManager",
    "PerformanceMonitor",
    "get_monitor",
    "start_monitoring",
    "stop_monitoring",

    # 报告
    "PerformanceReporter",
    "generate_and_save_daily_report",
    "generate_and_save_weekly_report",
]