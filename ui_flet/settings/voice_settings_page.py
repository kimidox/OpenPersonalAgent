"""
Shim: 向后兼容导出 VoiceSettingsPage

实际实现已拆分到 voice_settings/ 子包中。
"""
from ui_flet.settings.voice_settings import VoiceSettingsPage

__all__ = ["VoiceSettingsPage"]
