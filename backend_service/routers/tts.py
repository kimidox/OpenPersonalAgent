"""TTS 路由：模型加载状态查询 + 文本朗读。

调用 tts.py 同步 API（sherpa-onnx），路由用 `def`（threadpool）。
朗读为后台线程播放，接口立即返回。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/tts", tags=["tts"])


# =====================================================================
# 模型
# =====================================================================

class TtsStatusResponse(BaseModel):
    loaded: bool
    model_path: str | None = None
    num_speakers: int = 0


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    speaker_id: int = 0
    speed: float = 1.0


class SpeakResponse(BaseModel):
    started: bool


# =====================================================================
# 路由
# =====================================================================

@router.get("/status", response_model=TtsStatusResponse)
def tts_status() -> TtsStatusResponse:
    """查询 TTS 模型加载状态（未加载依赖时同样只返回 loaded=False）。"""
    from tts import is_tts_model_loaded, get_tts_model_path, get_num_speakers

    try:
        loaded = is_tts_model_loaded()
        return TtsStatusResponse(
            loaded=loaded,
            model_path=get_tts_model_path() if loaded else None,
            num_speakers=get_num_speakers() if loaded else 0,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"TTS 状态查询失败: {e}",
        )


@router.post("/speak", response_model=SpeakResponse)
def tts_speak(body: SpeakRequest) -> SpeakResponse:
    """朗读文本：先打断当前播放，再合成并后台播放。"""
    from tts import is_tts_model_loaded, speak_text

    if not is_tts_model_loaded():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TTS 模型未加载",
        )
    # 打断正在进行的播放，避免新旧语音叠加
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:  # noqa: BLE001
        pass
    ok = speak_text(body.text, speaker_id=body.speaker_id, speed=body.speed)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="朗读启动失败",
        )
    return SpeakResponse(started=True)
