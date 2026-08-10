"""依赖注入：单例访问器（供路由通过 `Depends` 注入）。

模块级单例在 app.py lifespan 启动时初始化。路由层应使用 `Depends(get_xxx)`，
便于测试替换。
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from backend_service.runner import run_coordinator, RunCoordinator
from backend_service.ws.manager import ws_manager, WSManager
from backend_service.ws.stream_bridge import stream_bridge, StreamBridge


# =====================================================================
# 单例访问器
# =====================================================================

def get_ws_manager() -> WSManager:
    return ws_manager


def get_run_coordinator() -> RunCoordinator:
    return run_coordinator


def get_stream_bridge() -> StreamBridge:
    return stream_bridge


def get_skill_agent(request: Request) -> Any:
    """从 app.state 取 SkillAgent 实例。

    lifespan 完成前为 None，路由层应判断并返回 503。
    """
    return getattr(request.app.state, "skill_agent", None)


def get_memory(request: Request) -> Any:
    return getattr(request.app.state, "memory", None)


def get_floating_ball_manager(request: Request) -> Any:
    """从 app.state.components 取 FloatingBallManager 实例（阶段 5）。"""
    components = getattr(request.app.state, "components", None)
    if components is None:
        return None
    return getattr(components, "floating_ball", None)


def require_floating_ball_manager(request: Request) -> Any:
    """要求悬浮球管理器已就绪，否则 503。"""
    mgr = get_floating_ball_manager(request)
    if mgr is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FloatingBallManager 未就绪（后端启动中）",
        )
    return mgr


def require_skill_agent(request: Request) -> Any:
    """要求 SkillAgent 已就绪，否则 503。"""
    agent = get_skill_agent(request)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SkillAgent 未就绪（后端启动中）",
        )
    return agent
