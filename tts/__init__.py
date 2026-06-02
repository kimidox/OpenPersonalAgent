"""
TTS模块 - 文本转语音功能

使用Sherpa-ONNX作为后端引擎，支持本地语音合成。
"""
from .tts_engine import TTSEngine
from .voice_manager import VoiceManager, VoiceInfo
from .audio_player import AudioPlayer
from .synthesizer import TTSSynthesizer
from .tts_config import TTSConfigManager, TTSConfigData, get_tts_config

__all__ = [
    "TTSEngine",
    "VoiceManager",
    "VoiceInfo",
    "AudioPlayer",
    "TTSSynthesizer",
    "TTSConfigManager",
    "TTSConfigData",
    "get_tts_config",
]