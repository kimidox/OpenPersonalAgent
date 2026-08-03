"""
AgentViewModel — Agent 状态管理的 ViewModel 层

封装 SkillAgent 的运行状态、模型信息、Token 使用统计等，
使 UI 层无需直接访问 SkillAgent 即可获取 Agent 的运行状态。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, TYPE_CHECKING

from logger import get_logger

if TYPE_CHECKING:
    from skill_agent import SkillAgent


class AgentViewModel:
    """
    Agent 状态 ViewModel

    职责：
    - 管理 Agent 的运行状态（是否正在运行、当前模型等）
    - 管理 Token 使用统计
    - 启动 / 停止任务
    - 提供状态查询接口

    UI 层通过此 ViewModel 查询 Agent 状态，不直接访问 SkillAgent。
    """

    def __init__(
        self,
        skill_agent: SkillAgent | None = None,
    ) -> None:
        self._skill_agent = skill_agent
        self._logger = get_logger()

        # 运行状态
        self._is_running: bool = False
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # 当前模型信息
        self._current_model: str = ""

        # Token 使用统计
        self._token_usage: dict[str, Any] = {}

        # ---------- 回调 ----------
        # 运行状态变化回调：签名 (is_running: bool) -> None
        self.on_running_changed: Callable[[bool], Any] | None = None
        # Token 使用变化回调：签名 (token_usage: dict) -> None
        self.on_token_usage_changed: Callable[[dict], Any] | None = None

    # ==================================================================
    # SkillAgent 引用管理
    # ==================================================================

    def set_skill_agent(self, agent: SkillAgent | None) -> None:
        """设置 / 替换 SkillAgent 实例"""
        self._skill_agent = agent

    @property
    def skill_agent(self) -> SkillAgent | None:
        """只读属性：获取 SkillAgent（仅限 ViewModel 内部与极少数桥接场景）"""
        return self._skill_agent

    @property
    def is_available(self) -> bool:
        """SkillAgent 是否可用"""
        return self._skill_agent is not None

    # ==================================================================
    # 运行状态
    # ==================================================================

    @property
    def is_running(self) -> bool:
        """Agent 是否正在运行"""
        return self._is_running or (self._worker_thread is not None and self._worker_thread.is_alive())

    @property
    def worker_thread(self) -> threading.Thread | None:
        """当前工作线程"""
        return self._worker_thread

    @worker_thread.setter
    def worker_thread(self, thread: threading.Thread | None) -> None:
        """设置工作线程"""
        self._worker_thread = thread

    @property
    def stop_event(self) -> threading.Event:
        """停止事件"""
        return self._stop_event

    def _set_running(self, running: bool) -> None:
        """设置运行状态并通知回调"""
        old = self._is_running
        self._is_running = running
        if old != running and self.on_running_changed:
            try:
                self.on_running_changed(running)
            except Exception as e:
                self._logger.warning(f"on_running_changed 回调异常: {e}")

    # ==================================================================
    # 任务控制
    # ==================================================================

    def start_task(self, worker_thread: threading.Thread) -> None:
        """
        启动任务

        Args:
            worker_thread: 已启动的工作线程
        """
        self._stop_event.clear()
        self._worker_thread = worker_thread
        self._set_running(True)
        self._logger.info("AgentViewModel: 任务已启动")

    def stop_task(self) -> None:
        """请求停止当前任务"""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            if self._skill_agent:
                self._skill_agent.request_stop()
            self._logger.info("AgentViewModel: 请求停止任务")

    def on_task_finished(self) -> None:
        """任务完成回调（由 UI 层在 _handle_worker_finished 中调用）"""
        self._set_running(False)

    # ==================================================================
    # 模型与 Token 信息
    # ==================================================================

    @property
    def current_model(self) -> str:
        """当前使用的模型名称"""
        return self._current_model

    @current_model.setter
    def current_model(self, model: str) -> None:
        """设置当前模型"""
        self._current_model = model

    @property
    def token_usage(self) -> dict[str, Any]:
        """Token 使用统计"""
        return self._token_usage

    def update_token_usage(self, usage: dict[str, Any]) -> None:
        """
        更新 Token 使用统计

        Args:
            usage: Token 使用信息
        """
        self._token_usage = usage
        if self.on_token_usage_changed:
            try:
                self.on_token_usage_changed(usage)
            except Exception as e:
                self._logger.warning(f"on_token_usage_changed 回调异常: {e}")

    # ==================================================================
    # 便捷查询
    # ==================================================================

    def is_worker_alive(self) -> bool:
        """工作线程是否存活"""
        return bool(self._worker_thread and self._worker_thread.is_alive())

    def is_stop_requested(self) -> bool:
        """是否已请求停止"""
        return self._stop_event.is_set()
