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
    SendMessageQueuedResponse,
    SendMessageRequest,
    SendMessageStartedResponse,
    StopRunResponse,
)
from backend_service.ws.events import new_run_id

router = APIRouter(prefix="/api", tags=["messages", "agent"])


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
    run_id = new_run_id()
    ctx = RunContext(
        run_id=run_id,
        conversation_id=conversation_id,
        source=body.source,
        query=body.query,
        enable_thinking=body.enable_thinking,
        uploaded_files_content=body.uploaded_files_content,
    )
    # 注入 executor / on_complete / on_error（由 stream_bridge 构造）
    ctx.executor = bridge.build_executor(ctx)
    ctx.on_complete = bridge.make_on_complete(ctx)
    ctx.on_error = bridge.make_on_error(ctx)

    try:
        result = runner.submit(ctx, queued_ok=body.queued_ok)
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
