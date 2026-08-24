"""
IPC 通信优化模块

优化策略：
1. 批量消息传递：在主进程侧累积消息，批量发送减少 IPC 调用次数
2. msgpack 序列化：替代 pickle，提供更快的序列化性能和更小的体积
3. 性能监控：记录延迟、吞吐量，提供性能告警

使用方式：
    # 主进程侧
    sender = BatchMessageSender(to_ball_queue)
    sender.send({"type": "test", "data": "hello"})
    sender.send({"type": "update", "value": 123})
    # 批量发送会在后台自动进行

    # 悬浮球进程侧
    optimized_queue = OptimizedIPCQueue(from_main_queue)
    msg = optimized_queue.get()  # 自动解包批量消息
"""
from __future__ import annotations

import time
import threading
import statistics
from collections import deque
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from logger import get_logger


@dataclass
class IPCPerformanceStats:
    """IPC 性能统计数据"""
    total_messages_sent: int = 0
    total_messages_received: int = 0
    total_batches_sent: int = 0
    total_bytes_sent: int = 0

    # 延迟统计（毫秒）
    latencies: list[float] = field(default_factory=list)
    max_latency: float = 0.0
    min_latency: float = float('inf')
    avg_latency: float = 0.0

    # 吞吐量统计
    messages_per_second: float = 0.0
    bytes_per_second: float = 0.0

    # 性能告警
    high_latency_count: int = 0  # 延迟超过阈值次数
    last_error: Optional[str] = None


class IPCPerformanceMonitor:
    """
    IPC 性能监控器

    记录消息传递延迟、吞吐量，提供性能告警
    """

    def __init__(
        self,
        latency_threshold_ms: float = 100.0,
        stats_window: int = 100,
    ):
        """
        Args:
            latency_threshold_ms: 延迟告警阈值（毫秒）
            stats_window: 统计窗口大小（保留最近 N 条记录）
        """
        self._logger = get_logger()
        self._latency_threshold = latency_threshold_ms
        self._stats_window = stats_window
        self._stats = IPCPerformanceStats()
        self._lock = threading.Lock()

        # 吞吐量计算
        self._throughput_window: deque[tuple[float, int]] = deque(maxlen=stats_window)
        self._last_throughput_check = time.time()

    def record_send(
        self,
        batch_size: int,
        bytes_sent: int,
        latency_ms: float,
    ) -> None:
        """记录发送性能"""
        with self._lock:
            self._stats.total_messages_sent += batch_size
            self._stats.total_batches_sent += 1
            self._stats.total_bytes_sent += bytes_sent

            # 延迟统计
            self._stats.latencies.append(latency_ms)
            if len(self._stats.latencies) > self._stats_window:
                self._stats.latencies = self._stats.latencies[-self._stats_window:]

            self._stats.max_latency = max(self._stats.max_latency, latency_ms)
            self._stats.min_latency = min(self._stats.min_latency, latency_ms) if self._stats.min_latency != float('inf') else latency_ms
            self._stats.avg_latency = statistics.mean(self._stats.latencies) if self._stats.latencies else 0.0

            # 延迟告警
            if latency_ms > self._latency_threshold:
                self._stats.high_latency_count += 1
                self._logger.warning(
                    f"IPC 延迟过高: {latency_ms:.2f}ms (阈值: {self._latency_threshold}ms)"
                )

            # 吞吐量统计
            self._throughput_window.append((time.time(), batch_size))
            self._update_throughput()

    def record_receive(self, message_count: int = 1) -> None:
        """记录接收性能"""
        with self._lock:
            self._stats.total_messages_received += message_count

    def _update_throughput(self) -> None:
        """更新吞吐量统计"""
        now = time.time()
        window_duration = now - self._last_throughput_check

        # 每 1 秒更新一次吞吐量
        if window_duration >= 1.0 and self._throughput_window:
            total_messages = sum(count for _, count in self._throughput_window)
            total_bytes = sum(count * 100 for _, count in self._throughput_window)  # 估算

            self._stats.messages_per_second = total_messages / window_duration
            self._stats.bytes_per_second = total_bytes / window_duration

            self._throughput_window.clear()
            self._last_throughput_check = now

    def get_stats(self) -> IPCPerformanceStats:
        """获取性能统计"""
        with self._lock:
            return IPCPerformanceStats(
                total_messages_sent=self._stats.total_messages_sent,
                total_messages_received=self._stats.total_messages_received,
                total_batches_sent=self._stats.total_batches_sent,
                total_bytes_sent=self._stats.total_bytes_sent,
                latencies=self._stats.latencies.copy(),
                max_latency=self._stats.max_latency,
                min_latency=self._stats.min_latency,
                avg_latency=self._stats.avg_latency,
                messages_per_second=self._stats.messages_per_second,
                bytes_per_second=self._stats.bytes_per_second,
                high_latency_count=self._stats.high_latency_count,
                last_error=self._stats.last_error,
            )

    def record_error(self, error: str) -> None:
        """记录错误"""
        with self._lock:
            self._stats.last_error = error
            self._logger.error(f"IPC 错误: {error}")


class MessageSerializer:
    """
    消息序列化器

    支持使用 msgpack 进行高效序列化
    """

    def __init__(self, use_msgpack: bool = True):
        """
        Args:
            use_msgpack: 是否使用 msgpack 序列化
        """
        self._use_msgpack = use_msgpack
        self._msgpack = None

        if use_msgpack:
            try:
                import msgpack
                self._msgpack = msgpack
            except ImportError:
                self._use_msgpack = False
                get_logger().warning(
                    "msgpack 未安装，回退到 pickle 序列化。"
                    "建议安装: pip install msgpack"
                )

    def serialize(self, data: dict[str, Any]) -> bytes:
        """序列化消息"""
        if self._use_msgpack and self._msgpack:
            return self._msgpack.packb(data, use_bin_type=True)
        else:
            # 回退到 pickle（multiprocessing.Queue 内部使用）
            import pickle
            return pickle.dumps(data)

    def deserialize(self, data: bytes) -> dict[str, Any]:
        """反序列化消息"""
        if self._use_msgpack and self._msgpack:
            return self._msgpack.unpackb(data, raw=False)
        else:
            import pickle
            return pickle.loads(data)


class BatchMessageSender:
    """
    批量消息发送器

    在主进程侧累积消息，批量发送到悬浮球进程，减少 IPC 调用次数

    工作原理：
    1. 消息先进入缓冲区
    2. 后台线程定期检查（时间窗口）或缓冲区达到阈值时批量发送
    3. 减少序列化开销和进程间通信次数
    """

    def __init__(
        self,
        queue: Any,  # multiprocessing.Queue
        batch_size: int = 10,
        time_window_ms: float = 50.0,
        use_msgpack: bool = True,
        monitor: Optional[IPCPerformanceMonitor] = None,
    ):
        """
        Args:
            queue: 目标进程队列
            batch_size: 批量发送大小阈值
            time_window_ms: 时间窗口（毫秒）
            use_msgpack: 是否使用 msgpack 序列化
            monitor: 性能监控器（可选）
        """
        self._logger = get_logger()
        self._queue = queue
        self._batch_size = batch_size
        self._time_window = time_window_ms / 1000.0  # 转换为秒
        self._serializer = MessageSerializer(use_msgpack)
        self._monitor = monitor or IPCPerformanceMonitor()

        # 消息缓冲区
        self._buffer: deque[dict[str, Any]] = deque()
        self._buffer_lock = threading.Lock()

        # 后台发送线程
        self._stop_event = threading.Event()
        self._send_thread = threading.Thread(
            target=self._send_loop,
            name="ipc-batch-sender",
            daemon=True,
        )
        self._send_thread.start()

        self._logger.info(
            f"批量消息发送器已启动 (batch_size={batch_size}, "
            f"time_window={time_window_ms}ms, msgpack={use_msgpack})"
        )

    def send(self, message: dict[str, Any]) -> None:
        """
        发送消息（异步，进入缓冲区）

        Args:
            message: 要发送的消息字典
        """
        with self._buffer_lock:
            self._buffer.append(message)

            # 如果缓冲区达到阈值，立即通知发送线程
            if len(self._buffer) >= self._batch_size:
                self._flush_buffer()

    def _flush_buffer(self) -> None:
        """立即发送缓冲区中的所有消息（必须在持有锁时调用）"""
        if not self._buffer:
            return

        # 取出所有消息
        messages = list(self._buffer)
        self._buffer.clear()

        # 发送批量消息
        self._send_batch(messages)

    def _send_batch(self, messages: list[dict[str, Any]]) -> None:
        """发送批量消息"""
        start_time = time.time()

        try:
            # 序列化批量消息
            batch_data = {
                "type": "__batch__",
                "messages": messages,
                "count": len(messages),
                "timestamp": time.time(),
            }

            serialized = self._serializer.serialize(batch_data)

            # 发送到队列
            self._queue.put(serialized)

            # 记录性能
            latency_ms = (time.time() - start_time) * 1000
            self._monitor.record_send(
                batch_size=len(messages),
                bytes_sent=len(serialized),
                latency_ms=latency_ms,
            )

            self._logger.debug(
                f"批量发送 {len(messages)} 条消息, "
                f"大小: {len(serialized)} 字节, "
                f"延迟: {latency_ms:.2f}ms"
            )

        except Exception as e:
            self._logger.error(f"批量发送失败: {e}")
            self._monitor.record_error(str(e))

            # 失败时尝试逐条发送
            for msg in messages:
                try:
                    serialized = self._serializer.serialize(msg)
                    self._queue.put(serialized)
                except Exception as e2:
                    self._logger.error(f"单条发送失败: {e2}")

    def _send_loop(self) -> None:
        """后台发送循环"""
        while not self._stop_event.is_set():
            try:
                # 等待时间窗口
                self._stop_event.wait(self._time_window)

                # 检查缓冲区
                with self._buffer_lock:
                    if self._buffer:
                        self._flush_buffer()

            except Exception as e:
                self._logger.error(f"发送循环异常: {e}")

    def flush(self) -> None:
        """立即发送所有缓冲消息"""
        with self._buffer_lock:
            self._flush_buffer()

    def close(self) -> None:
        """关闭发送器"""
        # 发送剩余消息
        self.flush()

        # 停止后台线程
        self._stop_event.set()
        self._send_thread.join(timeout=1.0)

        self._logger.info("批量消息发送器已关闭")

    def get_monitor(self) -> IPCPerformanceMonitor:
        """获取性能监控器"""
        return self._monitor


class BatchMessageReceiver:
    """
    批量消息接收器

    在悬浮球进程侧接收批量消息，自动解包

    使用方式：
        receiver = BatchMessageReceiver(from_main_queue)
        while True:
            messages = receiver.receive_all()
            for msg in messages:
                process(msg)
    """

    def __init__(
        self,
        queue: Any,  # multiprocessing.Queue
        use_msgpack: bool = True,
        monitor: Optional[IPCPerformanceMonitor] = None,
    ):
        """
        Args:
            queue: 源进程队列
            use_msgpack: 是否使用 msgpack 序列化
            monitor: 性能监控器（可选）
        """
        self._logger = get_logger()
        self._queue = queue
        self._serializer = MessageSerializer(use_msgpack)
        self._monitor = monitor or IPCPerformanceMonitor()

    def receive_all(self, timeout: float = 0.1) -> list[dict[str, Any]]:
        """
        接收所有可用消息（非阻塞）

        Args:
            timeout: 首次接收超时时间（秒）

        Returns:
            消息列表
        """
        messages = []

        try:
            # 尝试接收第一条消息（带超时）
            data = self._queue.get(timeout=timeout)
            msg = self._deserialize(data)
            messages.extend(self._unwrap_batch(msg))

            # 接收剩余消息（非阻塞）
            while True:
                try:
                    data = self._queue.get_nowait()
                    msg = self._deserialize(data)
                    messages.extend(self._unwrap_batch(msg))
                except Exception:
                    break

        except Exception:
            pass

        # 记录接收性能
        if messages:
            self._monitor.record_receive(len(messages))

        return messages

    def _deserialize(self, data: bytes) -> dict[str, Any]:
        """反序列化消息"""
        try:
            return self._serializer.deserialize(data)
        except Exception:
            # 如果反序列化失败，可能是旧格式的消息（直接是字典）
            if isinstance(data, dict):
                return data
            raise

    def _unwrap_batch(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """解包批量消息"""
        if message.get("type") == "__batch__":
            return message.get("messages", [])
        else:
            return [message]


class OptimizedIPCManager:
    """
    优化的 IPC 管理器

    统一管理批量发送器和接收器，提供性能统计

    使用方式：
        # 主进程侧
        manager = OptimizedIPCManager.create_sender(to_ball_queue)

        # 发送消息
        manager.send({"type": "test", "data": "hello"})

        # 获取性能统计
        stats = manager.get_stats()

        # 悬浮球进程侧
        manager = OptimizedIPCManager.create_receiver(from_main_queue)
        messages = manager.receive_all()
    """

    def __init__(
        self,
        sender: Optional[BatchMessageSender] = None,
        receiver: Optional[BatchMessageReceiver] = None,
    ):
        self._sender = sender
        self._receiver = receiver
        self._logger = get_logger()

    @classmethod
    def create_sender(
        cls,
        queue: Any,
        batch_size: int = 10,
        time_window_ms: float = 50.0,
        use_msgpack: bool = True,
    ) -> OptimizedIPCManager:
        """创建发送端管理器"""
        monitor = IPCPerformanceMonitor()
        sender = BatchMessageSender(
            queue=queue,
            batch_size=batch_size,
            time_window_ms=time_window_ms,
            use_msgpack=use_msgpack,
            monitor=monitor,
        )
        return cls(sender=sender)

    @classmethod
    def create_receiver(
        cls,
        queue: Any,
        use_msgpack: bool = True,
    ) -> OptimizedIPCManager:
        """创建接收端管理器"""
        monitor = IPCPerformanceMonitor()
        receiver = BatchMessageReceiver(
            queue=queue,
            use_msgpack=use_msgpack,
            monitor=monitor,
        )
        return cls(receiver=receiver)

    def send(self, message: dict[str, Any]) -> None:
        """发送消息"""
        if self._sender is None:
            raise RuntimeError("此管理器不是发送端")
        self._sender.send(message)

    def receive_all(self, timeout: float = 0.1) -> list[dict[str, Any]]:
        """接收所有消息"""
        if self._receiver is None:
            raise RuntimeError("此管理器不是接收端")
        return self._receiver.receive_all(timeout)

    def get_stats(self) -> IPCPerformanceStats:
        """获取性能统计"""
        if self._sender:
            return self._sender.get_monitor().get_stats()
        elif self._receiver:
            return self._receiver._monitor.get_stats()
        else:
            return IPCPerformanceStats()

    def flush(self) -> None:
        """立即发送所有缓冲消息"""
        if self._sender:
            self._sender.flush()

    def close(self) -> None:
        """关闭管理器"""
        if self._sender:
            self._sender.close()


# 性能测试工具
def benchmark_ipc_performance(
    queue: Any,
    message_count: int = 1000,
    message_size: int = 100,
) -> dict[str, float]:
    """
    测试 IPC 性能

    Args:
        queue: 测试队列
        message_count: 消息数量
        message_size: 每条消息大小（字节）

    Returns:
        性能测试结果
    """
    logger = get_logger()
    logger.info(f"开始 IPC 性能测试: {message_count} 条消息, 每条 {message_size} 字节")

    # 生成测试消息
    test_message = {
        "type": "test",
        "data": "x" * message_size,
    }

    # 测试原始方式（逐条发送）
    logger.info("测试原始方式（逐条发送）...")
    start_time = time.time()
    for _ in range(message_count):
        queue.put(test_message)
    original_time = time.time() - start_time
    original_latency = (original_time / message_count) * 1000  # 毫秒

    # 清空队列
    while not queue.empty():
        try:
            queue.get_nowait()
        except Exception:
            break

    # 测试优化方式（批量发送）
    logger.info("测试优化方式（批量发送）...")
    sender = BatchMessageSender(queue, batch_size=50, time_window_ms=20.0)
    start_time = time.time()
    for _ in range(message_count):
        sender.send(test_message)
    sender.flush()
    optimized_time = time.time() - start_time
    optimized_latency = (optimized_time / message_count) * 1000  # 毫秒

    # 清空队列
    while not queue.empty():
        try:
            queue.get_nowait()
        except Exception:
            break

    sender.close()

    # 计算改进
    improvement = (original_time - optimized_time) / original_time * 100

    results = {
        "message_count": message_count,
        "message_size": message_size,
        "original_time_s": original_time,
        "original_latency_ms": original_latency,
        "optimized_time_s": optimized_time,
        "optimized_latency_ms": optimized_latency,
        "improvement_percent": improvement,
        "throughput_original_msg_per_s": message_count / original_time,
        "throughput_optimized_msg_per_s": message_count / optimized_time,
    }

    logger.info("IPC 性能测试结果:")
    logger.info(f"  原始方式: {original_time:.3f}s, 延迟 {original_latency:.3f}ms")
    logger.info(f"  优化方式: {optimized_time:.3f}s, 延迟 {optimized_latency:.3f}ms")
    logger.info(f"  性能提升: {improvement:.1f}%")

    return results