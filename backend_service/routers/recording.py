"""录音路由：start/stop/status + ASR 模型加载。

调用 recorder / asr 同步 API，路由用 `def`（threadpool）。
录音实时识别回调经 WS 推送（recording.delta 事件）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend_service.deps import get_skill_agent
from backend_service.ws.events import WSEvent
from backend_service.ws.manager import ws_manager

router = APIRouter(prefix="/api/recording", tags=["recording"])


# =====================================================================
# 模型
# =====================================================================

class RecordingStatusResponse(BaseModel):
    is_recording: bool
    asr_model_loaded: bool
    current_audio_path: str | None = None


class StartRecordingResponse(BaseModel):
    started: bool
    conversation_id: str | None = None


class StopRecordingResponse(BaseModel):
    stopped: bool
    audio_path: str | None = None


class LoadModelRequest(BaseModel):
    model_path: str | None = None
    auto_download: bool | None = None


class LoadModelResponse(BaseModel):
    loaded: bool


class ReleaseModelResponse(BaseModel):
    released: bool


# =====================================================================
# 录音器单例
# =====================================================================

def _get_recorder():
    """延迟导入 recorder，避免 lifespan 启动期加载 ASR 依赖。"""
    from recorder import get_recorder
    return get_recorder()


# =====================================================================
# 路由
# =====================================================================

@router.get("/status", response_model=RecordingStatusResponse)
def recording_status() -> RecordingStatusResponse:
    """查询录音状态。"""
    try:
        rec = _get_recorder()
        from recorder import is_online_model_loaded
        return RecordingStatusResponse(
            is_recording=rec.is_recording,
            asr_model_loaded=is_online_model_loaded(),
            current_audio_path=str(rec.get_current_audio_path()) if rec.get_current_audio_path() else None,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询录音状态失败: {e}",
        )


@router.post("/start", response_model=StartRecordingResponse)
def start_recording(
    request: Request,
    conversation_id: str | None = None,
) -> StartRecordingResponse:
    """开始流式录音。realtime_callback 经 WS 推 recording.delta 事件。"""
    try:
        rec = _get_recorder()
        loop = getattr(request.app.state, "loop", None)

        def _realtime_callback(text: str, is_final: bool) -> None:
            if loop is None:
                return
            event = WSEvent(
                event="recording.delta",
                conversation_id=conversation_id or "",
                run_id="",
                data={"text": text, "is_final": is_final},
            )
            try:
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast(event), loop)
            except Exception:
                pass

        ok = rec.start_recording(realtime_callback=_realtime_callback)
        return StartRecordingResponse(started=ok, conversation_id=conversation_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"开始录音失败: {e}",
        )


@router.post("/stop", response_model=StopRecordingResponse)
def stop_recording() -> StopRecordingResponse:
    """停止录音。返回音频文件路径。"""
    try:
        rec = _get_recorder()
        path = rec.stop_recording()
        return StopRecordingResponse(
            stopped=True,
            audio_path=str(path) if path else None,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"停止录音失败: {e}",
        )


@router.post("/asr/load", response_model=LoadModelResponse)
def load_asr_model(body: LoadModelRequest) -> LoadModelResponse:
    """加载流式 ASR 模型。"""
    try:
        from recorder import load_online_model
        ok = load_online_model(
            model_path=body.model_path,
            auto_download=body.auto_download,
        )
        return LoadModelResponse(loaded=ok)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载 ASR 模型失败: {e}",
        )


@router.post("/asr/release", response_model=ReleaseModelResponse)
def release_asr_model() -> ReleaseModelResponse:
    """释放流式 ASR 模型。"""
    try:
        from recorder import release_online_model
        release_online_model()
        return ReleaseModelResponse(released=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"释放 ASR 模型失败: {e}",
        )


@router.post("/asr/transcribe", response_model=dict)
def transcribe_audio(audio_path: str) -> dict:
    """转录音频文件（同步阻塞）。"""
    try:
        from pathlib import Path
        from recorder import get_recorder
        rec = get_recorder()
        text = rec.transcribe_audio(Path(audio_path))
        return {"text": text or ""}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"转录失败: {e}",
        )
