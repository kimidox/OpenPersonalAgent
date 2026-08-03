"""
定时任务 Mixin

负责定时任务调度、会话创建等。
"""
from __future__ import annotations

import config
from logger import get_logger
from ui_flet.viewmodels.conversation_viewmodel import ConversationViewModel


class ScheduledTaskMixin:
    """
    定时任务 Mixin

    包含定时任务触发的会话创建、调度器停止等方法。
    通过 self 访问 MainWindow 的属性（如 self._page, self._logger, self._scheduler 等）。
    """

    # ==================================================================
    # 定时任务和调度
    # ==================================================================

    def create_conversation_for_scheduled_task(self, task) -> None:
        """
        定时任务触发：创建新会话并将任务内容作为用户消息发起 Agent 对话。

        供 TaskScheduler（后台线程）调用；UI 操作通过 page.run_task 调度到
        Flet 主线程执行，避免跨线程操作 UI。

        Args:
            task: ScheduledTask 对象（使用 task.content 作为用户消息）
        """
        vm: ConversationViewModel = self._conversation_vm
        if not vm.is_available:
            self._logger.error("SkillAgent 未初始化，无法处理定时任务对话")
            return

        content = (getattr(task, "content", "") or "").strip()
        if not content:
            self._logger.warning(f"定时任务 {getattr(task, 'task_id', '?')} 内容为空，跳过")
            return

        self._logger.info(
            f"定时任务触发 Agent 对话: {getattr(task, 'title', '')} - {content[:50]}"
        )
        self._page.run_task(self._run_scheduled_task_conversation, content)

    async def _run_scheduled_task_conversation(self, content: str) -> None:
        """在 Flet 主线程中执行定时任务对话流程"""
        try:
            # 按配置决定是否显示主窗口
            if config.SCHEDULED_TASK_SHOW_WINDOW:
                self.show_main_window()

            # 双重检查：若触发后用户抢先发起了对话，则跳过本次（任务已被标记 triggered）
            if self.is_agent_busy():
                self._logger.warning("定时任务对话执行时工作线程正忙，跳过本次对话")
                return

            # 创建新会话并切换
            conversation_id = self._create_new_conversation()
            if not conversation_id:
                self._logger.error("定时任务创建新会话失败")
                return

            # 添加用户消息到消息列表
            if self._message_list:
                self._message_list.add_message("user", content)

            # 设置 UI 运行状态
            self._app_state.ui.set_task_running(True)
            if self._input_area:
                self._input_area.set_inference_running(True)

            # 启动工作线程处理 SkillAgent 调用
            self._start_skill_agent_worker(content, conversation_id)
        except Exception as e:
            self._logger.exception(f"定时任务对话执行失败: {e}")

    def _stop_scheduler(self) -> None:
        """停止定时任务调度器（窗口关闭/退出应用时调用）"""
        scheduler = getattr(self, "_scheduler", None)
        if scheduler is not None:
            try:
                scheduler.stop()
            except Exception as e:
                self._logger.warning(f"停止 TaskScheduler 失败: {e}")
