from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer

from logger import get_module_logger
from notification import send_notification
from scheduled_tasks import ScheduledTask, get_pending_tasks, update_task, update_task_status

logger = get_module_logger("scheduler")


class TaskScheduler(QObject):
    CHECK_INTERVAL_MS: int = 5000

    def __init__(self, tray_icon=None, main_window=None):
        super().__init__()
        self._tray_icon = tray_icon
        self._main_window = main_window
        self._timer: QTimer | None = None
        self._running: bool = False
        logger.info("TaskScheduler 初始化完成")

    def start(self) -> None:
        if self._running:
            logger.warning("TaskScheduler 已在运行中，跳过启动")
            return

        logger.info("TaskScheduler 启动中...")
        self._running = True

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_tasks)
        self._timer.start(self.CHECK_INTERVAL_MS)

        self._check_tasks()
        logger.info(f"TaskScheduler 已启动，检查间隔: {self.CHECK_INTERVAL_MS}ms")

    def stop(self) -> None:
        if not self._running:
            logger.warning("TaskScheduler 未在运行，跳过停止")
            return

        logger.info("TaskScheduler 停止中...")
        self._running = False

        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

        logger.info("TaskScheduler 已停止")

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

    def _trigger_agent_conversation(self, task: ScheduledTask) -> None:
        if self._main_window is None:
            logger.error(f"无法触发 agent_conversation 任务 {task.task_id}: 主窗口引用未设置")
            return

        try:
            self._main_window.create_conversation_for_scheduled_task(task)
            logger.info(f"任务 {task.task_id} agent_conversation 已触发")
        except Exception as e:
            logger.exception(f"触发任务 {task.task_id} agent_conversation 失败: {e}")

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