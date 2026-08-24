"""Agent 路由：思考模式 / 偏好 / steer / followUp / constraints。

所有路由用 `def`（threadpool，3.9 节），因调用 SkillAgent 同步方法。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend_service.deps import require_skill_agent

router = APIRouter(prefix="/api/agent", tags=["agent"])


# =====================================================================
# 请求/响应模型
# =====================================================================

class ThinkingModeRequest(BaseModel):
    enabled: bool


class ThinkingModeResponse(BaseModel):
    enabled: bool


class SteerRequest(BaseModel):
    message: str


class FollowUpRequest(BaseModel):
    message: str


class ConstraintsRequest(BaseModel):
    constraints: str


class ConstraintsResponse(BaseModel):
    constraints: str


class BaseInfoResponse(BaseModel):
    base_info: str


# =====================================================================
# 路由
# =====================================================================

@router.get("/thinking", response_model=ThinkingModeResponse)
def get_thinking(agent=Depends(require_skill_agent)) -> ThinkingModeResponse:
    """获取当前思考模式状态。

    SkillAgent 无 getter，从内部属性读取。
    """
    enabled = bool(getattr(agent, "_enable_thinking", False))
    return ThinkingModeResponse(enabled=enabled)


@router.put("/thinking", response_model=ThinkingModeResponse)
def set_thinking(
    body: ThinkingModeRequest,
    agent=Depends(require_skill_agent),
) -> ThinkingModeResponse:
    """开启/关闭思考模式。"""
    agent.set_enable_thinking(body.enabled)
    return ThinkingModeResponse(enabled=body.enabled)


@router.post("/steer", status_code=status.HTTP_202_ACCEPTED)
def steer(
    body: SteerRequest,
    agent=Depends(require_skill_agent),
) -> dict:
    """向当前 run 注入 steering 指令（中途修正）。"""
    try:
        agent.steer(body.message)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"steer 失败: {e}",
        )
    return {"accepted": True}


@router.post("/followup", status_code=status.HTTP_202_ACCEPTED)
def followup(
    body: FollowUpRequest,
    agent=Depends(require_skill_agent),
) -> dict:
    """向当前 run 注入 followUp 后续指令。"""
    try:
        agent.followUp(body.message)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"followUp 失败: {e}",
        )
    return {"accepted": True}


@router.get("/constraints", response_model=ConstraintsResponse)
def get_constraints(agent=Depends(require_skill_agent)) -> ConstraintsResponse:
    """获取当前会话的约束。"""
    return ConstraintsResponse(constraints=agent.get_conversation_constraints())


@router.put("/constraints", response_model=ConstraintsResponse)
def set_constraints(
    body: ConstraintsRequest,
    agent=Depends(require_skill_agent),
) -> ConstraintsResponse:
    """设置当前会话的约束。"""
    agent.set_conversation_constraints(body.constraints)
    return ConstraintsResponse(constraints=body.constraints)


@router.delete("/constraints", response_model=ConstraintsResponse)
def clear_constraints(agent=Depends(require_skill_agent)) -> ConstraintsResponse:
    """清除当前会话的约束。"""
    agent.clear_conversation_constraints()
    return ConstraintsResponse(constraints="")


@router.get("/base-info", response_model=BaseInfoResponse)
def get_base_info(agent=Depends(require_skill_agent)) -> BaseInfoResponse:
    """获取 Agent 基础信息（系统提示词渲染结果等）。"""
    return BaseInfoResponse(base_info=agent.get_base_info())


@router.post("/reload-skills", status_code=status.HTTP_200_OK)
def reload_skills(agent=Depends(require_skill_agent)) -> dict:
    """重新加载技能目录。"""
    try:
        agent.reload_skills()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"reload_skills 失败: {e}",
        )
    return {"reloaded": True}


@router.post("/clear-cache", status_code=status.HTTP_200_OK)
def clear_runtime_cache(agent=Depends(require_skill_agent)) -> dict:
    """清理运行时缓存。"""
    agent.clear_runtime_cache()
    return {"cleared": True}
