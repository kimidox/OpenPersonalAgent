"""
VoiceSettingsPage 语音设置页面编排层

将 ASR、TTS、Audio 三个设置区域组装为完整页面。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import TYPE_CHECKING, Optional

import flet as ft

from logger import get_logger
from ui_flet.theme import ThemeManager
from ui_flet.settings.voice_settings._asr_section import AsrSection
from ui_flet.settings.voice_settings._tts_section import TtsSection
from ui_flet.settings.voice_settings._audio_section import AudioSection

if TYPE_CHECKING:
    pass


class VoiceSettingsPage:
    """
    语音设置页面

    提供 ASR 和 TTS 的完整配置功能。
    """

    def __init__(self, page: ft.Page) -> None:
        """
        初始化语音设置页面

        Args:
            page: Flet Page 对象
        """
        self._page = page
        self._logger = get_logger()
        self._theme_manager = ThemeManager()

        # 子区域
        self._audio_section = AudioSection(
            page=page,
            theme_manager=self._theme_manager,
        )
        self._asr_section = AsrSection(
            page=page,
            theme_manager=self._theme_manager,
            get_input_device_value=self._audio_section.get_input_device_value,
        )
        self._tts_section = TtsSection(
            page=page,
            theme_manager=self._theme_manager,
        )

        # 主容器
        self._container: Optional[ft.Container] = None

    def build(self) -> ft.Container:
        """
        构建页面 UI

        Returns:
            页面容器
        """
        self._logger.info("VoiceSettingsPage: 开始构建页面")
        colors = self._theme_manager.get_color_scheme()

        title = ft.Text(
            "语音设置",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        asr_section = self._asr_section.build()
        tts_section = self._tts_section.build()
        audio_section = self._audio_section.build()

        content = ft.Column(
            [
                title,
                ft.Container(height=14),
                asr_section,
                ft.Container(height=14),
                tts_section,
                ft.Container(height=14),
                audio_section,
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self._container = ft.Container(
            content=content,
            padding=20,
        )

        self._logger.info("VoiceSettingsPage: 页面构建完成")
        return self._container

    async def async_load_data(self) -> None:
        """异步加载数据，在页面可见后调用"""
        await asyncio.sleep(0)  # yield to UI

        # 在线程中运行磁盘 I/O：音频设备枚举 + 模型选项获取
        with concurrent.futures.ThreadPoolExecutor() as executor:
            input_future = executor.submit(self._audio_section.get_audio_input_devices)
            output_future = executor.submit(self._audio_section.get_audio_output_devices)
            asr_options_future = executor.submit(self._asr_section.get_asr_model_options)
            tts_options_future = executor.submit(self._tts_section.get_tts_model_options)

            input_devices = await asyncio.wrap_future(input_future)
            output_devices = await asyncio.wrap_future(output_future)
            asr_options = await asyncio.wrap_future(asr_options_future)
            tts_options = await asyncio.wrap_future(tts_options_future)

        # 更新音频设备下拉框
        if self._audio_section._input_device_dropdown:
            self._audio_section._input_device_dropdown.options = input_devices
            self._audio_section._input_device_dropdown.value = self._audio_section.get_current_input_device()

        if self._audio_section._output_device_dropdown:
            self._audio_section._output_device_dropdown.options = output_devices
            self._audio_section._output_device_dropdown.value = self._audio_section.get_current_output_device()

        # 更新 ASR 模型下拉框
        if self._asr_section._asr_model_dropdown:
            self._asr_section._asr_model_dropdown.options = asr_options
            self._asr_section._asr_model_dropdown.value = self._asr_section.get_current_asr_model()

        # 更新 TTS 模型下拉框
        if self._tts_section._tts_model_dropdown:
            self._tts_section._tts_model_dropdown.options = tts_options
            self._tts_section._tts_model_dropdown.value = self._tts_section.get_current_tts_model()

        # 刷新状态
        self._asr_section.refresh_asr_status()
        self._tts_section.refresh_tts_status()
        self._tts_section.refresh_tts_speakers()

        # 更新页面
        try:
            if self._page:
                self._page.update()
        except Exception:
            pass
