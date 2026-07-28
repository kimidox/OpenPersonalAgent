"""
性能数据采集器

提供多种性能数据采集方式：
- 资源监控（CPU、内存、磁盘、网络）
- 时间跟踪（context manager）
- 自定义指标记录
"""
from __future__ import annotations

import time
import threading
import statistics
from typing import Any, Dict, List, Optional, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import deque

from logger import get_logger
from .metrics import (
    MetricValue,
    ResourceMetrics,
    ThroughputMetrics,
    SuccessRateMetrics,
    PerformanceSnapshot,
)
from .config import PerformanceConfig


@dataclass
class TimingRecord:
    """计时记录"""
    name: str
    start_time: float
    end_time: float
    duration_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResourceMonitor:
    """
    资源监控器

    使用 psutil 监控系统资源使用情况
    """

    def __init__(self, sample_interval: float = PerformanceConfig.SAMPLE_INTERVAL_SECONDS):
        """
        Args:
            sample_interval: 采样间隔（秒）
        """
        self._logger = get_logger()
        self._sample_interval = sample_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 历史数据缓冲区
        self._cpu_history: deque[float] = deque(maxlen=100)
        self._memory_history: deque[tuple[float, float]] = deque(maxlen=100)  # (MB, %)
        self._disk_history: deque[tuple[float, float]] = deque(maxlen=100)  # (read, write)
        self._net_history: deque[tuple[float, float]] = deque(maxlen=100)  # (recv, sent)

        # 上次采样值（用于计算速率）
        self._last_disk_io: Optional[tuple[float, float]] = None
        self._last_net_io: Optional[tuple[float, float]] = None
        self._last_sample_time: float = 0.0

        # psutil 进程对象
        self._process = None
        self._psutil = None

    def start(self) -> None:
        """启动资源监控"""
        if self._running:
            return

        # 导入 psutil
        try:
            import psutil
            self._psutil = psutil
            self._process = psutil.Process()
        except ImportError:
            self._logger.warning("psutil 未安装，资源监控将不可用")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="resource-monitor",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(f"资源监控器已启动 (采样间隔: {self._sample_interval}s)")

    def stop(self) -> None:
        """停止资源监控"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._logger.info("资源监控器已停止")

    def _monitor_loop(self) -> None:
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                self._sample()
            except Exception as e:
                self._logger.error(f"资源采样失败: {e}")

            self._stop_event.wait(self._sample_interval)

    def _sample(self) -> None:
        """采样资源使用情况"""
        now = time.time()
        elapsed = now - self._last_sample_time if self._last_sample_time > 0 else self._sample_interval

        # CPU 使用率
        cpu_percent = self._process.cpu_percent()
        self._cpu_history.append(cpu_percent)

        # 内存使用
        memory_info = self._process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)  # 转换为 MB
        memory_percent = self._process.memory_percent()
        self._memory_history.append((memory_mb, memory_percent))

        # 磁盘 I/O
        try:
            disk_io = self._psutil.disk_io_counters()
            if disk_io and self._last_disk_io:
                read_bytes = disk_io.read_bytes - self._last_disk_io[0]
                write_bytes = disk_io.write_bytes - self._last_disk_io[1]
                read_mb_s = (read_bytes / (1024 * 1024)) / elapsed
                write_mb_s = (write_bytes / (1024 * 1024)) / elapsed
                self._disk_history.append((read_mb_s, write_mb_s))
            self._last_disk_io = (disk_io.read_bytes, disk_io.write_bytes) if disk_io else None
        except Exception as e:
            self._logger.debug(f"磁盘 I/O 采样失败: {e}")

        # 网络 I/O
        try:
            net_io = self._psutil.net_io_counters()
            if net_io and self._last_net_io:
                recv_bytes = net_io.bytes_recv - self._last_net_io[0]
                sent_bytes = net_io.bytes_sent - self._last_net_io[1]
                recv_mb_s = (recv_bytes / (1024 * 1024)) / elapsed
                sent_mb_s = (sent_bytes / (1024 * 1024)) / elapsed
                self._net_history.append((recv_mb_s, sent_mb_s))
            self._last_net_io = (net_io.bytes_recv, net_io.bytes_sent) if net_io else None
        except Exception as e:
            self._logger.debug(f"网络 I/O 采样失败: {e}")

        self._last_sample_time = now

    def get_metrics(self) -> ResourceMetrics:
        """获取资源指标"""
        metrics = ResourceMetrics()

        # CPU
        if self._cpu_history:
            metrics.cpu_percent = statistics.mean(self._cpu_history)

        # 内存
        if self._memory_history:
            memory_values = [m[0] for m in self._memory_history]
            percent_values = [m[1] for m in self._memory_history]
            metrics.memory_mb = statistics.mean(memory_values)
            metrics.memory_percent = statistics.mean(percent_values)

        # 磁盘
        if self._disk_history:
            read_values = [d[0] for d in self._disk_history]
            write_values = [d[1] for d in self._disk_history]
            metrics.disk_read_mb_s = statistics.mean(read_values)
            metrics.disk_write_mb_s = statistics.mean(write_values)

        # 网络
        if self._net_history:
            recv_values = [n[0] for n in self._net_history]
            sent_values = [n[1] for n in self._net_history]
            metrics.net_recv_mb_s = statistics.mean(recv_values)
            metrics.net_sent_mb_s = statistics.mean(sent_values)

        return metrics


class TimingCollector:
    """
    时间采集器

    使用 context manager 记录代码块执行时间
    """

    def __init__(self, history_size: int = 1000):
        """
        Args:
            history_size: 历史记录大小
        """
        self._logger = get_logger()
        self._history: deque[TimingRecord] = deque(maxlen=history_size)
        self._lock = threading.Lock()

    @contextmanager
    def track(self, name: str, **metadata):
        """
        跟踪代码块执行时间

        用法:
            with timing.track("llm_call", model="gpt-4"):
                # ... LLM 调用代码 ...
        """
        start_time = time.time()
        try:
            yield
        finally:
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            record = TimingRecord(
                name=name,
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                metadata=metadata,
            )

            with self._lock:
                self._history.append(record)

            self._logger.debug(f"[{name}] 耗时: {duration_ms:.2f}ms")

    def get_records(self, name: Optional[str] = None) -> List[TimingRecord]:
        """
        获取计时记录

        Args:
            name: 过滤特定名称的记录（可选）

        Returns:
            计时记录列表
        """
        with self._lock:
            if name:
                return [r for r in self._history if r.name == name]
            return list(self._history)

    def get_statistics(self, name: str) -> Dict[str, float]:
        """
        获取特定操作的统计数据

        Args:
            name: 操作名称

        Returns:
            统计数据字典
        """
        records = self.get_records(name)
        if not records:
            return {}

        durations = [r.duration_ms for r in records]
        return {
            "count": len(durations),
            "min_ms": min(durations),
            "max_ms": max(durations),
            "avg_ms": statistics.mean(durations),
            "median_ms": statistics.median(durations),
            "p95_ms": statistics.quantiles(durations, n=100)[94] if len(durations) >= 100 else max(durations),
        }


class PerformanceCollector:
    """
    性能数据采集器

    统一管理所有性能数据采集
    """

    def __init__(self):
        self._logger = get_logger()
        self._resource_monitor = ResourceMonitor()
        self._timing_collector = TimingCollector()

        # 成功率统计
        self._success_counts: Dict[str, int] = {}
        self._failure_counts: Dict[str, int] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        """启动性能采集"""
        self._resource_monitor.start()
        self._logger.info("性能采集器已启动")

    def stop(self) -> None:
        """停止性能采集"""
        self._resource_monitor.stop()
        self._logger.info("性能采集器已停止")

    @contextmanager
    def track_time(self, name: str, **metadata):
        """跟踪执行时间"""
        with self._timing_collector.track(name, **metadata):
            yield

    def record_success(self, operation: str) -> None:
        """记录操作成功"""
        with self._lock:
            self._success_counts[operation] = self._success_counts.get(operation, 0) + 1

    def record_failure(self, operation: str) -> None:
        """记录操作失败"""
        with self._lock:
            self._failure_counts[operation] = self._failure_counts.get(operation, 0) + 1

    def get_success_rate_metrics(self) -> SuccessRateMetrics:
        """获取成功率指标"""
        metrics = SuccessRateMetrics()

        # 计算各操作成功率
        operations = {
            "llm": ("llm_success_rate",),
            "tool": ("tool_success_rate",),
            "ipc": ("ipc_success_rate",),
            "asr": ("asr_success_rate",),
            "tts": ("tts_success_rate",),
        }

        for op, (metric_name,) in operations.items():
            success = self._success_counts.get(op, 0)
            failure = self._failure_counts.get(op, 0)
            total = success + failure

            if total > 0:
                rate = (success / total) * 100
                setattr(metrics, metric_name, rate)

        return metrics

    def get_timing_statistics(self, name: str) -> Dict[str, float]:
        """获取计时统计"""
        return self._timing_collector.get_statistics(name)

    def collect_snapshot(self) -> PerformanceSnapshot:
        """采集性能快照"""
        snapshot = PerformanceSnapshot()

        # 资源指标
        snapshot.resource = self._resource_monitor.get_metrics()

        # 成功率指标
        snapshot.success_rate = self.get_success_rate_metrics()

        return snapshot


# 全局采集器实例
_collector: Optional[PerformanceCollector] = None


def get_collector() -> PerformanceCollector:
    """获取全局采集器实例"""
    global _collector
    if _collector is None:
        _collector = PerformanceCollector()
    return _collector


def track_time(name: str, **metadata):
    """全局时间跟踪函数"""
    return get_collector().track_time(name, **metadata)


def record_success(operation: str) -> None:
    """全局成功记录函数"""
    get_collector().record_success(operation)


def record_failure(operation: str) -> None:
    """全局失败记录函数"""
    get_collector().record_failure(operation)