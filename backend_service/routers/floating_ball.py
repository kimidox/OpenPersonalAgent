"""悬浮球控制路由（阶段 5）。

供 Tauri 前端控制悬浮球显隐 / 主题 / 查询状态。
球→backend 的消息由 FloatingBallManager._poll_loop 直接处理，不走 REST。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend_service.deps import require_floating_ball_manager


router = APIRouter(prefix="/api/floating-ball", tags=["floating-ball"])


# =====================================================================
# 响应模型
# =====================================================================

class FloatingBallStatus(BaseModel):
    running: bool
    pid: int | None = None
    ipc_stats: dict[str, Any] | None = None


class SetThemeRequest(BaseModel):
    theme: str


# =====================================================================
# 路由
# =====================================================================

@router.get("/status", response_model=FloatingBallStatus)
def get_status(mgr: Any = Depends(require_floating_ball_manager)) -> FloatingBallStatus:
    """查询悬浮球子进程状态。"""
    stats = mgr.get_stats()
    # IPCPerformanceStats 是 dataclass，转 dict
    stats_dict: dict[str, Any] | None = None
    if stats is not None:
        try:
            from dataclasses import asdict
            stats_dict = asdict(stats)
        except Exception:
            stats_dict = {"raw": str(stats)}
    return FloatingBallStatus(
        running=mgr.is_running(),
        pid=getattr(mgr._process, "pid", None) if mgr.is_running() else None,
        ipc_stats=stats_dict,
    )


@router.post("/show")
def show_ball(mgr: Any = Depends(require_floating_ball_manager)) -> dict[str, bool]:
    """显示悬浮球窗口。"""
    mgr.show()
    return {"shown": True}


@router.post("/hide")
def hide_ball(mgr: Any = Depends(require_floating_ball_manager)) -> dict[str, bool]:
    """隐藏悬浮球窗口。"""
    mgr.hide()
    return {"hidden": True}


@router.put("/theme")
def set_theme(
    body: SetThemeRequest,
    mgr: Any = Depends(require_floating_ball_manager),
) -> dict[str, str]:
    """更新悬浮球主题色。"""
    mgr.set_theme(body.theme)
    return {"theme": body.theme}


@router.post("/restart")
def restart_ball(mgr: Any = Depends(require_floating_ball_manager)) -> dict[str, bool]:
    """重启悬浮球子进程（先 stop 再 start）。"""
    mgr.stop()
    started = mgr.start(prestart=False)  # 重启后立即显示
    return {"restarted": started}
