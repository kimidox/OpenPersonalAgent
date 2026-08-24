"""流式桥：把 SkillAgent 的两路事件源（log_callback + AgentEvent）转为 WS 事件并广播。

关键点（见 3.1 / 3.9 / 3.11 节）：
- SkillAgent.run 在工作线程内执行（RunCoordinator 启动 daemon thread）。
- log_callback 在该工作线程内被调用 → 不能直接 await ws_manager.broadcast，
  必须经 `asyncio.run_coroutine_threadsafe(broadcast(...), loop)` 投递回事件循环。
- AgentEvent 经 SkillAgent.set_event_callback 设置的回调转发，同样在工作线程内。
- run 结束后推 `message.complete`（含 awaiting_user 标记，对应 SKILL_AGENT_AWAITING_USER_REPLY）。
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable

from logger import get_logger

from agent_events import AgentEvent
from skill_agent import SKILL_AGENT_AWAITING_USER_REPLY

from backend_service.runner import RunContext, run_coordinator
from backend_service.ws.events import (
    EVENT_LLM_STATE,
    EVENT_LLM_WARNING,
    EVENT_MESSAGE_COMPLETE,
    EVENT_STREAM_DELTA,
    WSEvent,
    from_log_callback,
    from_agent_event,
    message_complete,
    run_aborted,
)
from backend_service.ws.manager import ws_manager


class StreamBridge:
    """流式桥单例（由 deps 持有）。"""

    def __init__(self) -> None:
        self._logger = get_logger()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._skill_agent: Any = None  # SkillAgent 实例，由 lifecycle 注入
        self._floating_ball: Any = None  # FloatingBallManager，由 lifecycle 注入（阶段 5）

    # ------------------------------------------------------------------
    # 依赖注入
    # ------------------------------------------------------------------

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """lifespan 启动时调用，记录事件循环引用。"""
        self._loop = loop

    def set_skill_agent(self, agent: Any) -> None:
        """lifespan 完成 SkillAgent 初始化后调用。

        同时注册 AgentEvent 回调（set_event_callback）。
        """
        self._skill_agent = agent
        if agent is not None and hasattr(agent, "set_event_callback"):
            agent.set_event_callback(self._on_agent_event_callback)
            self._logger.info("StreamBridge: 已注册 SkillAgent event_callback")

    def set_floating_ball_manager(self, mgr: Any) -> None:
        """lifespan 完成悬浮球初始化后调用（阶段 5）。

        注入后，_emit 会把球关心的事件（llm.state / llm.warning / message.complete）
        同步转发到悬浮球 IPC 队列。
        """
        self._floating_ball = mgr
        self._logger.info("StreamBridge: 已注入 FloatingBallManager")

    # ------------------------------------------------------------------
    # 事件投递（工作线程 → 事件循环 + 悬浮球 IPC）
    # ------------------------------------------------------------------

    def _emit(self, event: WSEvent | None) -> None:
        """把 WSEvent 投递到事件循环广播。None 静默跳过。

        阶段 5：对悬浮球关心的事件（llm.state / llm.warning / message.complete），
        同步转发到悬浮球 IPC 队列（经 FloatingBallManager）。
        """
        if event is None or self._loop is None:
            if event is not None and self._loop is None:
                self._logger.warning(f"StreamBridge._emit 事件循环未设置，跳过 {event.event}")
            return
        # WS 广播
        try:
            self._logger.info(
                f"[WS] 投递事件: event={event.event}, run_id={event.run_id[:8]}, "
                f"conversation_id={event.conversation_id[:8]}, data_keys={list(event.data.keys())}"
            )
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast(event),
                self._loop,
            )
        except Exception as e:  # noqa: BLE001
            self._logger.warning(f"StreamBridge._emit 投递失败: {e}")

        # 分流到悬浮球（阶段 5）
        self._forward_to_floating_ball(event)

    def _forward_to_floating_ball(self, event: WSEvent) -> None:
        """把球关心的事件转发到悬浮球 IPC 队列。

        - llm.state → FloatingBallManager.send_llm_state_update
        - llm.warning → FloatingBallManager.send_llm_state_warning
        - message.complete → FloatingBallManager.send_chat_reply（result 作为回复）
        """
        if self._floating_ball is None:
            return
        try:
            if event.event == EVENT_LLM_STATE:
                self._floating_ball.send_llm_state_update(event.data)
            elif event.event == EVENT_LLM_WARNING:
                self._floating_ball.send_llm_state_warning(event.data)
            elif event.event == EVENT_MESSAGE_COMPLETE:
                result = event.data.get("result", "")
                if result:
                    self._floating_ball.send_chat_reply(result)
        except Exception as e:  # noqa: BLE001
            self._logger.warning(f"转发事件到悬浮球失败: {e}")

    # ------------------------------------------------------------------
    # log_callback（高频流式）
    # ------------------------------------------------------------------

    def make_log_callback(self, conversation_id: str, run_id: str) -> Callable[[str, str], None]:
        """构造 SkillAgent.run 的 log_callback 参数。"""
        def _log_callback(message: str, msg_type: str) -> None:
            event = from_log_callback(
                message,
                msg_type,
                conversation_id=conversation_id,
                run_id=run_id,
            )
            self._emit(event)
        return _log_callback

    # ------------------------------------------------------------------
    # AgentEvent 回调（结构化生命周期）
    # ------------------------------------------------------------------

    def _on_agent_event_callback(self, agent_event: AgentEvent) -> None:
        """由 SkillAgent 通过 set_event_callback 调用。

        注意：agent_event.conversation_id 是 SkillAgent 内部状态，
        与当前活跃 run 的 conversation_id 应一致；若为空，用 active_run 兜底。
        """
        conversation_id = agent_event.conversation_id
        run_id = ""
        active = run_coordinator.active_run()
        if active is not None:
            if not conversation_id:
                conversation_id = active.conversation_id
            if active.conversation_id == conversation_id:
                run_id = active.run_id
        if not run_id:
            # 找不到关联 run（可能是 lifecycle 启动期事件），丢弃
            self._logger.warning(
                f"StreamBridge: 丢弃无关联 run 的 AgentEvent: {agent_event.event_type}, "
                f"agent_event.conversation_id={agent_event.conversation_id[:8] if agent_event.conversation_id else '(空)'}, "
                f"active.conversation_id={active.conversation_id[:8] if active else '(空)'}, "
                f"active.run_id={active.run_id[:8] if active else '(空)'}"
            )
            return
        event = from_agent_event(agent_event, run_id=run_id)
        self._emit(event)

    # ------------------------------------------------------------------
    # 启动 run
    # ------------------------------------------------------------------

    def build_executor(
        self,
        ctx: RunContext,
    ) -> Callable[[], str]:
        """构造 RunContext.executor：调用 SkillAgent.run。

        executor 内部完成：
        1. 设置 conversation_id
        2. 设置 thinking / uploaded_files
        3. 调用 skill_agent.run(query, log_callback, stop_check_callback)
        4. 返回 result（可能是 SKILL_AGENT_AWAITING_USER_REPLY）
        """
        agent = self._skill_agent
        if agent is None:
            raise RuntimeError("SkillAgent 未初始化")

        log_callback = self.make_log_callback(ctx.conversation_id, ctx.run_id)
        stop_check_callback = ctx.stop_event.is_set

        def _execute() -> str:
            # 设置会话上下文
            agent.set_conversation_id(ctx.conversation_id)
            agent.set_enable_thinking(ctx.enable_thinking)
            # 文件内容已通过 <Files> 标签嵌入 query 中，无需单独设置
            # 调用主入口
            return agent.run(
                ctx.query,
                log_callback=log_callback,
                stop_check_callback=stop_check_callback,
            )

        return _execute

    def make_on_complete(self, ctx: RunContext) -> Callable[[str], None]:
        """构造 RunContext.on_complete：推 message.complete。"""
        def _on_complete(result: str) -> None:
            awaiting_user = (result == SKILL_AGENT_AWAITING_USER_REPLY)
            event = message_complete(
                conversation_id=ctx.conversation_id,
                run_id=ctx.run_id,
                result=result or "",
                awaiting_user=awaiting_user,
            )
            self._emit(event)
            self._logger.info(
                f"run 完成: run_id={ctx.run_id[:8]}, "
                f"awaiting_user={awaiting_user}, result_len={len(result or '')}"
            )
        return _on_complete

    def make_on_error(self, ctx: RunContext) -> Callable[[BaseException], None]:
        """构造 RunContext.on_error：异常时也推 message.complete（result=错误信息）。"""
        def _on_error(e: BaseException) -> None:
            err_msg = f"执行出错: {type(e).__name__}: {e}"
            event = message_complete(
                conversation_id=ctx.conversation_id,
                run_id=ctx.run_id,
                result=err_msg,
                awaiting_user=False,
            )
            self._emit(event)
        return _on_error

    # ------------------------------------------------------------------
    # 崩溃恢复
    # ------------------------------------------------------------------

    def abort_runs(self, runs: list[RunContext], reason: str = "sidecar_restart") -> None:
        """对 abort_all 返回的 run 列表推 run.aborted 事件。"""
        for ctx in runs:
            event = run_aborted(
                conversation_id=ctx.conversation_id,
                run_id=ctx.run_id,
                reason=reason,
            )
            self._emit(event)


# 模块级单例
stream_bridge = StreamBridge()
