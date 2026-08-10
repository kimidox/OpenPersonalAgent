"""RunCoordinator：全局 run 锁 + 请求队列（见 3.10 节）。

新架构下三路（Tauri 主窗口 / 悬浮球 / 调度器）可能并发 POST /messages。
SkillAgent 单例非线程安全，原 Flet 仅靠单 worker 串行隐式保证，需显式策略。

并发模型：
- 同一时刻最多一个活跃 run（_current_run）。
- 同一 conversation 不得排队第二个 run（视为冲突，409）。
- 不同 conversation 可排队（队列上限 4，超限 503）。
- run 完成后自动弹队首继续。
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from logger import get_logger

from backend_service.ws.events import new_run_id


# 来源标记（影响排队策略默认值）
RunSource = Literal["main", "floating_ball", "scheduler"]

# 队列上限
_MAX_QUEUE = 4


class RunConflictError(Exception):
    """已有活跃 run，且调用方选择不排队（queued_ok=False）。"""
    def __init__(self, active_run_id: str, active_conversation_id: str) -> None:
        self.active_run_id = active_run_id
        self.active_conversation_id = active_conversation_id
        super().__init__(f"已有活跃 run: {active_run_id}")


class RunQueueFullError(Exception):
    """排队队列已满。"""
    def __init__(self, position: int) -> None:
        self.position = position
        super().__init__(f"队列已满（{position}）")


class SameConversationConflictError(Exception):
    """同一会话已有活跃 run 或排队中的 run。"""
    def __init__(self, existing_run_id: str) -> None:
        self.existing_run_id = existing_run_id
        super().__init__(f"会话已有进行中的 run: {existing_run_id}")


@dataclass
class RunContext:
    """一次 run 请求的上下文。"""
    run_id: str
    conversation_id: str
    source: RunSource
    query: str
    enable_thinking: bool = False
    uploaded_files_content: str | dict | None = None
    # 由 RunCoordinator 在启动 worker 前注入
    stop_event: threading.Event = field(default_factory=threading.Event)
    started_at: float = 0.0
    finished_at: float = 0.0
    # run 执行函数（由 stream_bridge 注入），签名 () -> str
    executor: Callable[[], str] | None = None
    # 完成回调（由 stream_bridge 注入，用于推 message.complete）
    on_complete: Callable[[str], None] | None = None
    # 异常回调
    on_error: Callable[[BaseException], None] | None = None
    # 排队位置（0=已启动）
    queue_position: int = 0


@dataclass
class SubmitResult:
    """submit() 的返回值。"""
    status: Literal["started", "queued"]
    run_id: str
    position: int = 0  # started=0, queued=N


class RunCoordinator:
    """全局 run 协调器（单例，由 deps 持有）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_run: RunContext | None = None
        self._queue: deque[RunContext] = deque()
        self._logger = get_logger()
        # 已知活跃/排队中的 conversation_id 集合（用于同会话冲突检测）
        self._busy_conversations: set[str] = set()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def is_busy(self) -> bool:
        """是否有活跃 run（供调度器 is_agent_busy 等价语义使用）。"""
        with self._lock:
            return self._current_run is not None

    def active_run(self) -> RunContext | None:
        with self._lock:
            return self._current_run

    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    def submit(
        self,
        ctx: RunContext,
        *,
        queued_ok: bool,
    ) -> SubmitResult:
        """提交一个 run 请求。

        Args:
            ctx: run 上下文（run_id/conversation_id/query/enable_thinking 已填）。
            queued_ok: True=忙时入队；False=忙时抛 RunConflictError（409）。

        Returns:
            SubmitResult(status="started"|"queued", ...)

        Raises:
            SameConversationConflictError: 该 conversation 已有活跃/排队 run。
            RunConflictError: 已有活跃 run 且 queued_ok=False。
            RunQueueFullError: 队列已满。
        """
        with self._lock:
            # 1. 同会话冲突检测
            if ctx.conversation_id in self._busy_conversations:
                # 找到该会话已有的 run_id（活跃 or 队列）
                existing = self._find_run_for_conversation_locked(ctx.conversation_id)
                raise SameConversationConflictError(existing or "")

            # 2. 空闲 → 立即启动
            if self._current_run is None:
                self._current_run = ctx
                self._busy_conversations.add(ctx.conversation_id)
                ctx.queue_position = 0
                # 启动 worker（在锁外执行，避免阻塞 submit）
                self._start_worker_locked(ctx)
                return SubmitResult(status="started", run_id=ctx.run_id, position=0)

            # 3. 忙
            if not queued_ok:
                raise RunConflictError(
                    active_run_id=self._current_run.run_id,
                    active_conversation_id=self._current_run.conversation_id,
                )

            # 4. 入队
            if len(self._queue) >= _MAX_QUEUE:
                raise RunQueueFullError(position=len(self._queue))
            ctx.queue_position = len(self._queue) + 1
            self._queue.append(ctx)
            self._busy_conversations.add(ctx.conversation_id)
            self._logger.info(
                f"run 已入队: run_id={ctx.run_id[:8]}, "
                f"conversation_id={ctx.conversation_id[:8]}, position={ctx.queue_position}"
            )
            return SubmitResult(status="queued", run_id=ctx.run_id, position=ctx.queue_position)

    def _find_run_for_conversation_locked(self, conversation_id: str) -> str | None:
        if self._current_run and self._current_run.conversation_id == conversation_id:
            return self._current_run.run_id
        for ctx in self._queue:
            if ctx.conversation_id == conversation_id:
                return ctx.run_id
        return None

    def _start_worker_locked(self, ctx: RunContext) -> None:
        """启动 worker 线程（调用方持有锁）。"""
        ctx.started_at = time.time()
        thread = threading.Thread(
            target=self._worker_main,
            args=(ctx,),
            name=f"run-{ctx.run_id[:8]}",
            daemon=True,
        )
        thread.start()
        self._logger.info(
            f"run 已启动: run_id={ctx.run_id[:8]}, "
            f"conversation_id={ctx.conversation_id[:8]}, source={ctx.source}"
        )

    # ------------------------------------------------------------------
    # worker 主循环
    # ------------------------------------------------------------------

    def _worker_main(self, ctx: RunContext) -> None:
        """工作线程入口：执行 ctx.executor，完成后弹出队列下一个。"""
        result = ""
        try:
            if ctx.executor is None:
                raise RuntimeError("RunContext.executor 未注入")
            result = ctx.executor()
        except BaseException as e:  # noqa: BLE001
            self._logger.exception(f"run 执行异常: run_id={ctx.run_id[:8]}, {e}")
            if ctx.on_error is not None:
                try:
                    ctx.on_error(e)
                except Exception:  # noqa: BLE001
                    self._logger.exception("on_error 回调异常")
        finally:
            ctx.finished_at = time.time()
            if ctx.on_complete is not None:
                try:
                    ctx.on_complete(result)
                except Exception as e:  # noqa: BLE001
                    self._logger.exception(f"on_complete 回调异常: {e}")
            self._advance(ctx)

    def _advance(self, finished_ctx: RunContext) -> None:
        """当前 run 完成，弹出队首继续。"""
        with self._lock:
            if (
                self._current_run is not None
                and self._current_run.run_id == finished_ctx.run_id
            ):
                self._busy_conversations.discard(finished_ctx.conversation_id)
                self._current_run = None
            # 弹队首
            if self._queue:
                next_ctx = self._queue.popleft()
                # 重新计算排队位置（剩余队列）
                for i, c in enumerate(self._queue):
                    c.queue_position = i + 1
                next_ctx.queue_position = 0
                self._current_run = next_ctx
                self._logger.info(
                    f"弹出队首 run: run_id={next_ctx.run_id[:8]}, "
                    f"conversation_id={next_ctx.conversation_id[:8]}"
                )
                self._start_worker_locked(next_ctx)
            else:
                self._logger.info(f"run 完成且队列空: run_id={finished_ctx.run_id[:8]}")

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------

    def stop_active(self) -> bool:
        """请求停止当前活跃 run。返回是否成功请求。"""
        with self._lock:
            if self._current_run is None:
                return False
            ctx = self._current_run
        ctx.stop_event.set()
        # 业务层（stream_bridge）会在 stop_check_callback 检测到后退出
        self._logger.info(f"请求停止 run: run_id={ctx.run_id[:8]}")
        return True

    def stop(self, run_id: str) -> bool:
        """请求停止指定 run（活跃 or 队列）。"""
        with self._lock:
            if self._current_run and self._current_run.run_id == run_id:
                self._current_run.stop_event.set()
                return True
            for i, ctx in enumerate(self._queue):
                if ctx.run_id == run_id:
                    # 队列中的 run：直接移除（还未启动）
                    ctx.stop_event.set()
                    self._queue.remove(ctx)
                    self._busy_conversations.discard(ctx.conversation_id)
                    self._logger.info(f"已从队列移除 run: run_id={run_id[:8]}")
                    return True
        return False

    # ------------------------------------------------------------------
    # 中断（崩溃恢复用：sidecar 重启后清理所有未完成 run）
    # ------------------------------------------------------------------

    def abort_all(self, reason: str = "sidecar_restart") -> list[RunContext]:
        """标记所有活跃/排队 run 为中断状态。返回被中断的 run 列表。

        由 app.py lifespan shutdown 或崩溃恢复路径调用。
        不调用 on_complete/on_error（避免在异常退出时再触发业务逻辑）。
        """
        with self._lock:
            aborted = []
            if self._current_run is not None:
                self._current_run.stop_event.set()
                aborted.append(self._current_run)
                self._current_run = None
            while self._queue:
                ctx = self._queue.popleft()
                ctx.stop_event.set()
                aborted.append(ctx)
            self._busy_conversations.clear()
        self._logger.warning(f"已中断 {len(aborted)} 个 run: reason={reason}")
        return aborted


# 模块级单例
run_coordinator = RunCoordinator()
