"""
性能监控和告警机制

提供：
- 性能基线检查
- 异常告警
- 性能数据聚合
"""
from __future__ import annotations

import time
import threading
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

from logger import get_logger
from .metrics import MetricValue, PerformanceSnapshot
from .config import PerformanceConfig
from .collector import PerformanceCollector, get_collector


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """告警"""
    metric_name: str
    level: AlertLevel
    value: float
    baseline: float
    threshold: float
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "metric_name": self.metric_name,
            "level": self.level.value,
            "value": self.value,
            "baseline": self.baseline,
            "threshold": self.threshold,
            "message": self.message,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class AlertManager:
    """
    告警管理器

    管理告警触发、冷却、发送
    """

    def __init__(
        self,
        cooldown_seconds: int = PerformanceConfig.ALERT_COOLDOWN_SECONDS,
        max_alerts_per_hour: int = PerformanceConfig.MAX_ALERTS_PER_HOUR,
    ):
        """
        Args:
            cooldown_seconds: 告警冷却时间（秒）
            max_alerts_per_hour: 每小时最大告警数
        """
        self._logger = get_logger()
        self._cooldown_seconds = cooldown_seconds
        self._max_alerts_per_hour = max_alerts_per_hour

        # 告警历史（用于冷却）
        self._alert_history: Dict[str, float] = {}
        self._hourly_alert_count = 0
        self._hourly_reset_time = time.time()

        # 告警处理器列表
        self._handlers: List[Callable[[Alert], None]] = []
        self._lock = threading.Lock()

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """添加告警处理器"""
        with self._lock:
            self._handlers.append(handler)

    def check_metric(self, metric: MetricValue) -> Optional[Alert]:
        """
        检查指标是否触发告警

        Args:
            metric: 指标值

        Returns:
            告警对象（如果触发），否则 None
        """
        baseline = PerformanceConfig.get_all_baselines().get(metric.name)
        if baseline is None:
            return None

        # 跳过初始值（0）的告警，避免误报
        # 对于吞吐量指标，初始值 0 表示系统刚启动，不应告警
        if metric.value == 0 and not PerformanceConfig.is_lower_better(metric.name):
            return None

        # 获取告警阈值
        warning_threshold, critical_threshold = PerformanceConfig.get_threshold(metric.name)

        # 判断是否越小越好
        is_lower_better = PerformanceConfig.is_lower_better(metric.name)

        # 检查是否超过阈值
        alert_level = None
        threshold = None

        if is_lower_better:
            # 越小越好的指标（延迟、资源占用）
            if metric.value >= critical_threshold:
                alert_level = AlertLevel.CRITICAL
                threshold = critical_threshold
            elif metric.value >= warning_threshold:
                alert_level = AlertLevel.WARNING
                threshold = warning_threshold
        else:
            # 越大越好的指标（吞吐量、成功率）
            # 对于这些指标，warning_threshold 和 critical_threshold 是反向的
            # 例如：基线 100，warning 1.5倍 = 150，但实际阈值应该是低于基线时告警
            # 所以这里需要特殊处理
            if metric.value <= baseline * (1 - (PerformanceConfig.CRITICAL_THRESHOLD - 1)):
                alert_level = AlertLevel.CRITICAL
                threshold = baseline * (1 - (PerformanceConfig.CRITICAL_THRESHOLD - 1))
            elif metric.value <= baseline * (1 - (PerformanceConfig.WARNING_THRESHOLD - 1)):
                alert_level = AlertLevel.WARNING
                threshold = baseline * (1 - (PerformanceConfig.WARNING_THRESHOLD - 1))

        if alert_level is None:
            return None

        # 检查告警冷却
        if not self._check_cooldown(metric.name):
            self._logger.debug(f"告警冷却中，跳过: {metric.name}")
            return None

        # 检查每小时告警限制
        if not self._check_hourly_limit():
            self._logger.warning(f"每小时告警数量已达上限，跳过: {metric.name}")
            return None

        # 创建告警
        alert = Alert(
            metric_name=metric.name,
            level=alert_level,
            value=metric.value,
            baseline=baseline,
            threshold=threshold,
            message=f"指标 {metric.name} 超过阈值: {metric.value:.2f} (基线: {baseline:.2f}, 阈值: {threshold:.2f})",
            metadata=metric.metadata,
        )

        # 记录告警
        self._record_alert(metric.name)

        # 触发处理器
        self._trigger_handlers(alert)

        return alert

    def _check_cooldown(self, metric_name: str) -> bool:
        """检查告警冷却"""
        with self._lock:
            last_alert_time = self._alert_history.get(metric_name, 0)
            return time.time() - last_alert_time > self._cooldown_seconds

    def _check_hourly_limit(self) -> bool:
        """检查每小时告警限制"""
        with self._lock:
            # 重置计数器
            if time.time() - self._hourly_reset_time > 3600:
                self._hourly_alert_count = 0
                self._hourly_reset_time = time.time()

            return self._hourly_alert_count < self._max_alerts_per_hour

    def _record_alert(self, metric_name: str) -> None:
        """记录告警"""
        with self._lock:
            self._alert_history[metric_name] = time.time()
            self._hourly_alert_count += 1

    def _trigger_handlers(self, alert: Alert) -> None:
        """触发告警处理器"""
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as e:
                self._logger.error(f"告警处理器执行失败: {e}")


class PerformanceMonitor:
    """
    性能监控器

    定期采集性能数据，检查告警，生成报告
    """

    def __init__(
        self,
        collector: Optional[PerformanceCollector] = None,
        report_interval: float = PerformanceConfig.REPORT_INTERVAL_SECONDS,
    ):
        """
        Args:
            collector: 性能采集器
            report_interval: 报告生成间隔（秒）
        """
        self._logger = get_logger()
        self._collector = collector or get_collector()
        self._alert_manager = AlertManager()

        # 性能历史数据
        self._history: deque[PerformanceSnapshot] = deque(
            maxlen=int(PerformanceConfig.HISTORY_RETENTION_HOURS * 3600 / report_interval)
        )
        self._lock = threading.Lock()  # 添加锁

        # 监控线程
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 报告生成间隔
        self._report_interval = report_interval

        # 添加日志告警处理器
        self._alert_manager.add_handler(self._log_alert)

    def _log_alert(self, alert: Alert) -> None:
        """日志告警处理器"""
        log_msg = f"[性能告警] {alert.message}"
        if alert.level == AlertLevel.CRITICAL:
            self._logger.critical(log_msg)
        elif alert.level == AlertLevel.WARNING:
            self._logger.warning(log_msg)
        else:
            self._logger.info(log_msg)

    def start(self) -> None:
        """启动性能监控"""
        if self._running:
            return

        # 先启动采集器
        self._collector.start()

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="performance-monitor",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("性能监控器已启动")

    def stop(self) -> None:
        """停止性能监控"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

        # 停止采集器
        self._collector.stop()

        self._logger.info("性能监控器已停止")

    def _monitor_loop(self) -> None:
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                # 采集性能快照
                snapshot = self._collector.collect_snapshot()

                # 检查告警
                self._check_alerts(snapshot)

                # 保存历史数据
                with self._lock:
                    self._history.append(snapshot)

            except Exception as e:
                self._logger.error(f"性能监控异常: {e}")

            self._stop_event.wait(self._report_interval)

    def _check_alerts(self, snapshot: PerformanceSnapshot) -> None:
        """检查性能告警"""
        for metric in snapshot.get_all_metrics():
            try:
                alert = self._alert_manager.check_metric(metric)
                if alert:
                    self._logger.info(f"性能告警触发: {alert.message}")
            except Exception as e:
                self._logger.error(f"告警检查失败: {e}")

    def get_history(self, hours: int = 1) -> List[PerformanceSnapshot]:
        """
        获取历史性能数据

        Args:
            hours: 最近几小时的数据

        Returns:
            性能快照列表
        """
        cutoff_time = time.time() - hours * 3600
        return [s for s in self._history if s.timestamp >= cutoff_time]

    def get_current_metrics(self) -> PerformanceSnapshot:
        """获取当前性能指标"""
        return self._collector.collect_snapshot()

    def add_alert_handler(self, handler: Callable[[Alert], None]) -> None:
        """添加告警处理器"""
        self._alert_manager.add_handler(handler)


# 全局监控器实例
_monitor: Optional[PerformanceMonitor] = None


def get_monitor() -> PerformanceMonitor:
    """获取全局监控器实例"""
    global _monitor
    if _monitor is None:
        _monitor = PerformanceMonitor()
    return _monitor


def start_monitoring() -> None:
    """启动性能监控"""
    get_monitor().start()


def stop_monitoring() -> None:
    """停止性能监控"""
    get_monitor().stop()