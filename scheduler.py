"""TaskScheduler：周期检查 scheduled_tasks 并触发。

迁移说明（见 frontend-tauri-refactor.md 3.8 节）：
- 新增 `runner` / `bridge` / `skill_agent` 参数，用于后端服务模式（无 UI）。
- 保留 `main_window` 参数，用于 Flet 旧路径（阶段 6 前）。
- 二者互斥：若 `runner` 与 `bridge` 与 `skill_agent` 均提供，走后端路径；
  否则回退到 main_window 路径。
- `is_agent_busy`：后端路径读 `runner.is_busy()`；旧路径读 `main_window.is_agent_busy()`。
- `create_conversation_for_scheduled_task`：
  - 后端路径：`skill_agent.start_new_conversation()` + `runner.submit(RunContext)`。
  - 旧路径：`main_window.create_conversation_for_scheduled_task(task)`。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from logger import get_module_logger
from notification import send_notification
from scheduled_tasks import ScheduledTask, get_pending_tasks, update_task, update_task_status

if TYPE_CHECKING:
    from backend_service.runner import RunCoordinator, RunContext
    from backend_service.ws.stream_bridge import StreamBridge
    from skill_agent import SkillAgent

logger = get_module_logger("scheduler")


class _TaskDeferred(Exception):
    """任务延迟触发（如主窗口工作线程忙碌），保持 pending 状态等待下个检查周期。"""


class TaskScheduler:
    CHECK_INTERVAL_MS: int = 5000

    def __init__(
        self,
        tray_icon=None,
        main_window=None,
        *,
        runner: RunCoordinator | None = None,
        bridge: StreamBridge | None = None,
        skill_agent: SkillAgent | None = None,
    ) -> None:
        self._tray_icon = tray_icon
        self._main_window = main_window
        self._runner = runner
        self._bridge = bridge
        self._skill_agent = skill_agent
        self._timer: threading.Timer | None = None
        self._running: bool = False
        self._lock = threading.Lock()
        self._timer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # 后端模式标记
        self._backend_mode = runner is not None and bridge is not None and skill_agent is not None
        logger.info(
            f"TaskScheduler 初始化完成 (mode={'backend' if self._backend_mode else 'legacy'})"
        )

    # ------------------------------------------------------------------
    # 启停
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._running:
                logger.warning("TaskScheduler 已在运行中，跳过启动")
                return

            logger.info("TaskScheduler 启动中...")
            self._running = True
            self._stop_event.clear()

            def _timer_loop():
                while self._running:
                    try:
                        self._check_tasks()
                    except Exception as e:
                        logger.exception(f"检查任务时发生错误: {e}")
                    if self._stop_event.wait(self.CHECK_INTERVAL_MS / 1000):
                        break

            self._timer_thread = threading.Thread(target=_timer_loop, daemon=True)
            self._timer_thread.start()

            logger.info(f"TaskScheduler 已启动，检查间隔: {self.CHECK_INTERVAL_MS}ms")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                logger.warning("TaskScheduler 未在运行，跳过停止")
                return

            logger.info("TaskScheduler 停止中...")
            self._running = False
            self._stop_event.set()

        if self._timer_thread is not None:
            self._timer_thread.join(timeout=2)
            self._timer_thread = None

        logger.info("TaskScheduler 已停止")

    @property
    def is_running(self) -> bool:
        """调度器是否在运行（供 /api/health 查询）。"""
        return self._running

    # ------------------------------------------------------------------
    # 检查循环
    # ------------------------------------------------------------------

    def _check_tasks(self) -> None:
        if not self._running:
            return

        try:
            pending_tasks = get_pending_tasks()

            if not pending_tasks:
                return

            logger.debug(f"发现 {len(pending_tasks)} 个待触发任务")

            for task in pending_tasks:
                try:
                    self._trigger_task(task)
                except _TaskDeferred as e:
                    logger.info(str(e))
                except Exception as e:
                    logger.exception(f"触发任务 {task.task_id} 时发生错误: {e}")

        except Exception as e:
            logger.exception(f"检查任务时发生错误: {e}")

    def _trigger_task(self, task: ScheduledTask) -> None:
        logger.info(f"触发任务: {task.task_id} - {task.title}")

        execution_type = getattr(task, 'execution_type', 'notification')

        if execution_type == 'agent_conversation':
            self._trigger_agent_conversation(task)
        else:
            self._trigger_notification(task)

        if task.repeat_type == "none":
            update_task_status(task.task_id, "triggered")
            logger.info(f"单次任务 {task.task_id} 已标记为 triggered")
        else:
            next_trigger_time = self._calculate_next_trigger_time(task)
            if next_trigger_time:
                update_task(task.task_id, trigger_time=next_trigger_time)
                logger.info(f"重复任务 {task.task_id} 下次触发时间已更新为: {next_trigger_time}")
            else:
                update_task_status(task.task_id, "triggered")
                logger.warning(f"重复任务 {task.task_id} 无法计算下次触发时间，已标记为 triggered")

    def _trigger_notification(self, task: ScheduledTask) -> None:
        try:
            send_notification(
                notification_type=task.notification_type,
                title=task.title,
                message=task.content,
                tray_icon=self._tray_icon,
            )
            logger.debug(f"任务 {task.task_id} 通知已发送")
        except Exception as e:
            logger.error(f"发送任务 {task.task_id} 通知失败: {e}")

    # ------------------------------------------------------------------
    # agent_conversation 触发（双路径）
    # ------------------------------------------------------------------

    def _trigger_agent_conversation(self, task: ScheduledTask) -> None:
        if self._backend_mode:
            self._trigger_agent_conversation_backend(task)
        else:
            self._trigger_agent_conversation_legacy(task)

    def _trigger_agent_conversation_legacy(self, task: ScheduledTask) -> None:
        """旧路径：经 main_window.create_conversation_for_scheduled_task。"""
        if self._main_window is None:
            logger.error(f"无法触发 agent_conversation 任务 {task.task_id}: 主窗口引用未设置")
            return

        callback = getattr(self._main_window, 'create_conversation_for_scheduled_task', None)
        if not callable(callback):
            logger.error(
                f"无法触发 agent_conversation 任务 {task.task_id}: "
                "主窗口缺少 create_conversation_for_scheduled_task 方法"
            )
            return

        is_busy = getattr(self._main_window, 'is_agent_busy', None)
        if callable(is_busy) and is_busy():
            raise _TaskDeferred(
                f"主窗口工作线程忙碌，任务 {task.task_id} 延迟到下个检查周期"
            )

        try:
            callback(task)
            logger.info(f"任务 {task.task_id} agent_conversation 已触发（legacy）")
        except Exception as e:
            logger.exception(f"触发任务 {task.task_id} agent_conversation 失败: {e}")

    def _trigger_agent_conversation_backend(self, task: ScheduledTask) -> None:
        """新路径：直接调 RunCoordinator.submit，事件经 WS 广播。

        流程：
        1. 检查 run_coordinator.is_busy() → 忙则 _TaskDeferred
        2. 创建新会话 skill_agent.start_new_conversation()
        3. 构造 RunContext(source="scheduler") 并 submit(queued_ok=False)
           （调度器自身已用 _TaskDeferred 串行化，不再入队）
        4. run 启动后事件经 stream_bridge 推 WS（含 scheduled_task_id 便于前端识别）
        """
        assert self._runner is not None
        assert self._bridge is not None
        assert self._skill_agent is not None

        # 1. 忙则延迟
        if self._runner.is_busy():
            raise _TaskDeferred(
                f"RunCoordinator 忙碌，任务 {task.task_id} 延迟到下个检查周期"
            )

        content = (getattr(task, "content", "") or "").strip()
        if not content:
            logger.warning(f"任务 {task.task_id} 内容为空，跳过")
            return

        # 2. 创建新会话
        try:
            conversation_id, _title = self._skill_agent.start_new_conversation(
                conversation_type="agent_conversation",
                default_skills=[{"id": sid, "name": sid} for sid in (task.skill_ids or [])],
            )
            if not conversation_id:
                logger.error(f"任务 {task.task_id} 创建会话失败")
                return
        except Exception as e:
            logger.exception(f"任务 {task.task_id} 创建会话失败: {e}")
            return

        # 3. 构造 RunContext 并提交
        from backend_service.runner import RunContext
        from backend_service.ws.events import new_run_id

        run_id = new_run_id()
        ctx = RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            source="scheduler",
            query=content,
        )
        ctx.executor = self._bridge.build_executor(ctx)
        ctx.on_complete = self._bridge.make_on_complete(ctx)
        ctx.on_error = self._bridge.make_on_error(ctx)

        try:
            result = self._runner.submit(ctx, queued_ok=False)
            logger.info(
                f"任务 {task.task_id} agent_conversation 已触发（backend）: "
                f"run_id={run_id[:8]}, conversation_id={conversation_id[:8]}, "
                f"status={result.status}"
            )
        except Exception as e:
            logger.exception(f"任务 {task.task_id} 提交 RunCoordinator 失败: {e}")

    # ------------------------------------------------------------------
    # 重复任务计算
    # ------------------------------------------------------------------

    def _calculate_next_trigger_time(self, task: ScheduledTask) -> datetime | None:
        current_trigger = task.trigger_time

        if task.repeat_type == "daily":
            return current_trigger + timedelta(days=1)
        elif task.repeat_type == "weekly":
            return current_trigger + timedelta(weeks=1)
        elif task.repeat_type == "monthly":
            return current_trigger + timedelta(days=30)
        else:
            logger.warning(f"未知的重复类型: {task.repeat_type}")
            return None
