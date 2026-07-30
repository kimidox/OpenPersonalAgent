"""
LLM 异步执行器模块

提供基于 ThreadPoolExecutor 的异步 LLM 调用能力，避免阻塞主线程。
支持并发处理、任务取消、超时控制等特性。
"""

from __future__ import annotations

import threading
import time as _time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from logger import get_module_logger

logger = get_module_logger("AsyncExecutor")


class TaskState(str, Enum):
    """异步任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AsyncTaskResult:
    """异步任务结果"""
    task_id: str
    state: TaskState
    result: Optional[Any] = None
    error: Optional[Exception] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None

    @property
    def is_success(self) -> bool:
        """判断任务是否成功完成。

        Returns:
            bool: 当状态为 COMPLETED 且无错误时返回 True。
        """
        return self.state == TaskState.COMPLETED and self.error is None

    @property
    def is_finished(self) -> bool:
        """判断任务是否已结束（无论成功或失败）。

        Returns:
            bool: 状态为 COMPLETED、FAILED、CANCELLED 或 TIMEOUT 时返回 True。
        """
        return self.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.TIMEOUT)


class LLMExecutorManager:
    """
    LLM 线程池执行管理器（单例模式）

    核心功能：
    1. 管理全局线程池，避免重复创建
    2. 控制并发数量，防止资源耗尽
    3. 提供任务提交、取消、超时机制
    4. 线程安全的任务状态管理

    使用示例：
    ```python
    executor = LLMExecutorManager.get_instance()

    # 提交异步任务
    future = executor.submit(task_id, func, *args, **kwargs)

    # 等待结果（带超时）
    result = executor.get_result(task_id, timeout=30.0)

    # 取消任务
    executor.cancel(task_id)
    ```
    """

    _instance: Optional['LLMExecutorManager'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式：确保全局只有一个实例"""
        if cls._instance is None:
            with cls._lock:
                # 双重检查锁定
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        max_workers: int = 10,
        thread_name_prefix: str = "LLM-Executor",
    ):
        """
        初始化线程池管理器

        Args:
            max_workers: 最大线程数，默认 10（建议：CPU 核心数 * 2 + 1）
            thread_name_prefix: 线程名称前缀，便于调试
        """
        # 避免重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix

        # 创建线程池（懒加载）
        self._executor: Optional[ThreadPoolExecutor] = None
        self._executor_lock = threading.Lock()

        # 任务管理
        self._tasks: dict[str, Future] = {}
        self._task_results: dict[str, AsyncTaskResult] = {}
        self._tasks_lock = threading.Lock()

        # 统计信息
        self._total_tasks = 0
        self._active_tasks = 0
        self._stats_lock = threading.Lock()

        self._initialized = True
        logger.info(f"[LLMExecutorManager] 初始化完成，max_workers={max_workers}")

    def _get_executor(self) -> ThreadPoolExecutor:
        """获取线程池实例（懒加载）"""
        if self._executor is None:
            with self._executor_lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix=self._thread_name_prefix,
                    )
                    logger.debug(f"[LLMExecutorManager] 线程池已创建，max_workers={self._max_workers}")
        return self._executor

    @classmethod
    def get_instance(cls, max_workers: int = 10) -> 'LLMExecutorManager':
        """
        获取单例实例

        Args:
            max_workers: 最大线程数（仅首次创建时生效）

        Returns:
            LLMExecutorManager 实例
        """
        return cls(max_workers=max_workers)

    def submit(
        self,
        task_id: str,
        func: Callable,
        *args,
        timeout: Optional[float] = None,
        on_complete: Optional[Callable[[AsyncTaskResult], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        **kwargs
    ) -> Future:
        """
        提交异步任务到线程池

        Args:
            task_id: 任务唯一标识符
            func: 要执行的函数
            *args: 函数位置参数
            timeout: 任务超时时间（秒），None 表示不限制
            on_complete: 任务完成回调（成功）
            on_error: 任务错误回调（失败）
            **kwargs: 函数关键字参数

        Returns:
            Future 对象，用于跟踪任务状态

        Raises:
            RuntimeError: 如果任务 ID 已存在
        """
        with self._tasks_lock:
            if task_id in self._tasks:
                raise RuntimeError(f"任务 ID 已存在: {task_id}")

        executor = self._get_executor()

        # 包装任务函数，添加状态管理
        def wrapped_func():
            """包装实际任务函数，管理执行状态、结果保存和回调触发。

            执行传入的 func，根据结果更新 AsyncTaskResult 状态，
            并在成功时调用 on_complete 回调、失败时调用 on_error 回调。
            """
            task_result = AsyncTaskResult(
                task_id=task_id,
                state=TaskState.RUNNING,
                start_time=_time.time()
            )

            try:
                logger.debug(f"[LLMExecutorManager] 任务开始执行: {task_id}")

                # 执行实际任务
                result = func(*args, **kwargs)

                # 任务成功完成
                task_result.state = TaskState.COMPLETED
                task_result.result = result
                task_result.end_time = _time.time()
                task_result.duration_ms = (task_result.end_time - task_result.start_time) * 1000

                logger.debug(
                    f"[LLMExecutorManager] 任务完成: {task_id}, "
                    f"耗时: {task_result.duration_ms:.2f}ms"
                )

                # 调用成功回调
                if on_complete:
                    try:
                        on_complete(task_result)
                    except Exception as e:
                        logger.warning(f"[LLMExecutorManager] 成功回调执行失败: {e}")

            except Exception as e:
                # 任务失败
                task_result.state = TaskState.FAILED
                task_result.error = e
                task_result.end_time = _time.time()
                task_result.duration_ms = (task_result.end_time - task_result.start_time) * 1000

                logger.error(
                    f"[LLMExecutorManager] 任务失败: {task_id}, "
                    f"错误: {type(e).__name__}: {e}"
                )

                # 调用错误回调
                if on_error:
                    try:
                        on_error(e)
                    except Exception as err:
                        logger.warning(f"[LLMExecutorManager] 错误回调执行失败: {err}")

            finally:
                # 保存任务结果
                with self._tasks_lock:
                    self._task_results[task_id] = task_result

                # 更新统计信息
                with self._stats_lock:
                    self._active_tasks -= 1

            return task_result

        # 提交任务
        future = executor.submit(wrapped_func)

        # 注册任务
        with self._tasks_lock:
            self._tasks[task_id] = future

        # 更新统计信息
        with self._stats_lock:
            self._total_tasks += 1
            self._active_tasks += 1

        logger.debug(f"[LLMExecutorManager] 任务已提交: {task_id}")

        return future

    def get_result(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> AsyncTaskResult:
        """
        获取任务结果（阻塞等待）

        Args:
            task_id: 任务 ID
            timeout: 等待超时时间（秒），None 表示不限制

        Returns:
            AsyncTaskResult 任务结果对象

        Raises:
            TimeoutError: 任务超时
            KeyError: 任务不存在
            Exception: 任务执行失败的错误
        """
        with self._tasks_lock:
            future = self._tasks.get(task_id)
            if future is None:
                raise KeyError(f"任务不存在: {task_id}")

        try:
            # 等待任务完成
            future.result(timeout=timeout)

            # 获取任务结果
            with self._tasks_lock:
                task_result = self._task_results.get(task_id)

                if task_result is None:
                    raise RuntimeError(f"任务结果丢失: {task_id}")

                return task_result

        except TimeoutError:
            # 超时处理
            logger.warning(f"[LLMExecutorManager] 任务超时: {task_id}, timeout={timeout}s")

            # 更新任务状态
            with self._tasks_lock:
                task_result = self._task_results.get(task_id)
                if task_result:
                    task_result.state = TaskState.TIMEOUT

            raise

        except Exception as e:
            logger.error(f"[LLMExecutorManager] 获取任务结果失败: {task_id}, 错误: {e}")
            raise

    def cancel(self, task_id: str) -> bool:
        """
        取消任务

        Args:
            task_id: 任务 ID

        Returns:
            bool: 是否成功取消（True 表示任务还未开始或正在运行时被取消）
        """
        with self._tasks_lock:
            future = self._tasks.get(task_id)
            if future is None:
                logger.warning(f"[LLMExecutorManager] 尝试取消不存在的任务: {task_id}")
                return False

        # 尝试取消任务
        cancelled = future.cancel()

        if cancelled:
            # 更新任务状态
            task_result = AsyncTaskResult(
                task_id=task_id,
                state=TaskState.CANCELLED,
                end_time=_time.time()
            )

            with self._tasks_lock:
                self._task_results[task_id] = task_result

            logger.info(f"[LLMExecutorManager] 任务已取消: {task_id}")

            # 更新统计信息
            with self._stats_lock:
                self._active_tasks -= 1

        return cancelled

    def is_task_running(self, task_id: str) -> bool:
        """
        检查任务是否正在运行

        Args:
            task_id: 任务 ID

        Returns:
            bool: 任务是否正在运行
        """
        with self._tasks_lock:
            future = self._tasks.get(task_id)
            if future is None:
                return False

            return future.running()

    def get_task_state(self, task_id: str) -> Optional[TaskState]:
        """
        获取任务状态

        Args:
            task_id: 任务 ID

        Returns:
            TaskState: 任务状态，如果任务不存在则返回 None
        """
        with self._tasks_lock:
            task_result = self._task_results.get(task_id)
            if task_result:
                return task_result.state

            # 任务结果还未保存，检查 Future 状态
            future = self._tasks.get(task_id)
            if future is None:
                return None

            if future.running():
                return TaskState.RUNNING
            elif future.cancelled():
                return TaskState.CANCELLED
            elif future.done():
                return TaskState.COMPLETED
            else:
                return TaskState.PENDING

    def get_stats(self) -> dict:
        """
        获取线程池统计信息

        Returns:
            dict: 统计信息字典
        """
        with self._stats_lock:
            return {
                "total_tasks": self._total_tasks,
                "active_tasks": self._active_tasks,
                "max_workers": self._max_workers,
            }

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """
        关闭线程池

        Args:
            wait: 是否等待所有任务完成
            cancel_futures: 是否取消未开始的任务
        """
        if self._executor is not None:
            logger.info("[LLMExecutorManager] 关闭线程池...")
            self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            self._executor = None

    def cleanup_finished_tasks(self, max_age_seconds: float = 3600) -> int:
        """
        清理已完成的旧任务（释放内存）

        Args:
            max_age_seconds: 最大保留时间（秒），默认 1 小时

        Returns:
            int: 清理的任务数量
        """
        current_time = _time.time()
        cleaned_count = 0

        with self._tasks_lock:
            tasks_to_remove = []

            for task_id, task_result in self._task_results.items():
                if task_result.is_finished and task_result.end_time:
                    age = current_time - task_result.end_time
                    if age > max_age_seconds:
                        tasks_to_remove.append(task_id)

            # 批量删除
            for task_id in tasks_to_remove:
                del self._tasks[task_id]
                del self._task_results[task_id]
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"[LLMExecutorManager] 已清理 {cleaned_count} 个旧任务")

        return cleaned_count


# 全局实例（方便导入）
_executor_manager: Optional[LLMExecutorManager] = None
_executor_lock = threading.Lock()


def get_executor_manager() -> LLMExecutorManager:
    """
    获取全局线程池管理器实例

    Returns:
        LLMExecutorManager 实例
    """
    global _executor_manager

    if _executor_manager is None:
        with _executor_lock:
            if _executor_manager is None:
                _executor_manager = LLMExecutorManager.get_instance()

    return _executor_manager