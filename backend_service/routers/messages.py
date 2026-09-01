"""消息路由：POST /messages / POST /stop / GET /agent/status。

注意（3.9 节）：调用 SkillAgent / memory 的路由用 `def`（threadpool），
但本路由仅做 RunCoordinator.submit（非阻塞），不直接调 SkillAgent.run，
因此可用 `def` 即可。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend_service.deps import require_skill_agent, get_run_coordinator, get_stream_bridge
from backend_service.runner import (
    RunContext,
    RunCoordinator,
    RunConflictError,
    RunQueueFullError,
    SameConversationConflictError,
)
from backend_service.ws.stream_bridge import StreamBridge
from backend_service.schemas import (
    AgentStatus,
    RegenerateRequest,
    SendMessageQueuedResponse,
    SendMessageRequest,
    SendMessageStartedResponse,
    StopRunResponse,
)
from backend_service.ws.events import new_run_id

router = APIRouter(prefix="/api", tags=["messages", "agent"])


def _submit_run(
    conversation_id: str,
    *,
    query: str,
    source: str,
    enable_thinking: bool,
    queued_ok: bool,
    runner: RunCoordinator,
    bridge: StreamBridge,
) -> SendMessageStartedResponse | SendMessageQueuedResponse:
    """构造 RunContext 并提交（send_message / regenerate 共用）。"""
    run_id = new_run_id()
    ctx = RunContext(
        run_id=run_id,
        conversation_id=conversation_id,
        source=source,
        query=query,
        enable_thinking=enable_thinking,
    )
    # 注入 executor / on_complete / on_error（由 stream_bridge 构造）
    ctx.executor = bridge.build_executor(ctx)
    ctx.on_complete = bridge.make_on_complete(ctx)
    ctx.on_error = bridge.make_on_error(ctx)

    try:
        result = runner.submit(ctx, queued_ok=queued_ok)
    except SameConversationConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "status": "conflict",
                "reason": "same_conversation",
                "existing_run_id": e.existing_run_id,
            },
        )
    except RunConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "status": "conflict",
                "reason": "busy",
                "active_run_id": e.active_run_id,
                "active_conversation_id": e.active_conversation_id,
            },
        )
    except RunQueueFullError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "queue_full", "position": e.position},
        )

    if result.status == "started":
        return SendMessageStartedResponse(status="started", run_id=result.run_id)
    return SendMessageQueuedResponse(
        status="queued", run_id=result.run_id, position=result.position
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageStartedResponse | SendMessageQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    agent=Depends(require_skill_agent),
    runner: RunCoordinator = Depends(get_run_coordinator),
    bridge: StreamBridge = Depends(get_stream_bridge),
) -> SendMessageStartedResponse | SendMessageQueuedResponse:
    """发送消息 → 启动 run（流式经 WS 推送）。"""
    return _submit_run(
        conversation_id,
        query=body.query,
        source=body.source,
        enable_thinking=body.enable_thinking,
        queued_ok=body.queued_ok,
        runner=runner,
        bridge=bridge,
    )


@router.post(
    "/conversations/{conversation_id}/regenerate",
    response_model=SendMessageStartedResponse | SendMessageQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_message(
    conversation_id: str,
    body: RegenerateRequest,
    request: Request,
    agent=Depends(require_skill_agent),
    runner: RunCoordinator = Depends(get_run_coordinator),
    bridge: StreamBridge = Depends(get_stream_bridge),
) -> SendMessageStartedResponse | SendMessageQueuedResponse:
    """重新生成最后一轮回复。

    从持久化记忆中删除最后一条 user 消息及其之后的所有消息
    （即上一轮推理结果），然后用原 query 重新提交 run；
    user 消息由 Agent 在新 run 中重新持久化，历史不重复。
    """
    memory = getattr(agent, "memory", None)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent memory 未就绪",
        )
    try:
        record = memory.pop_last_turn(conversation_id)
    except NotImplementedError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="当前记忆实现不支持重新生成",
        )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话中没有可重新生成的用户消息",
        )
    query = record.get("content") if isinstance(record, dict) else None
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="最后一条用户消息内容为空，无法重新生成",
        )
    return _submit_run(
        conversation_id,
        query=query,
        source="main",
        enable_thinking=body.enable_thinking,
        queued_ok=body.queued_ok,
        runner=runner,
        bridge=bridge,
    )


@router.post(
    "/conversations/{conversation_id}/stop",
    response_model=StopRunResponse,
)
def stop_conversation(
    conversation_id: str,
    runner: RunCoordinator = Depends(get_run_coordinator),
) -> StopRunResponse:
    """停止当前会话的活跃 run（如有）。"""
    active = runner.active_run()
    if active is None or active.conversation_id != conversation_id:
        return StopRunResponse(stopped=False, run_id=None)
    ok = runner.stop(active.run_id)
    return StopRunResponse(stopped=ok, run_id=active.run_id if ok else None)


@router.post(
    "/agent/stop",
    response_model=StopRunResponse,
)
def stop_agent(
    runner: RunCoordinator = Depends(get_run_coordinator),
) -> StopRunResponse:
    """停止当前活跃 run（不限会话）。"""
    active = runner.active_run()
    if active is None:
        return StopRunResponse(stopped=False, run_id=None)
    ok = runner.stop_active()
    return StopRunResponse(stopped=ok, run_id=active.run_id if ok else None)


@router.get("/agent/status", response_model=AgentStatus)
def agent_status(
    runner: RunCoordinator = Depends(get_run_coordinator),
) -> AgentStatus:
    """Agent 状态查询（纯内存读，async-safe）。"""
    active = runner.active_run()
    return AgentStatus(
        is_running=active is not None,
        active_run_id=active.run_id if active else None,
        active_conversation_id=active.conversation_id if active else None,
        queue_size=runner.queue_size(),
    )
