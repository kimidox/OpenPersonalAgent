"""
音频设备设置区域

提供音频输入/输出设备选择与测试的配置界面。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import flet as ft

from config import get_config, set_config
from logger import get_logger
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    pass


def _get_device_id(value: str) -> Optional[int]:
    """将下拉框值转换为设备 ID"""
    if value is None or value == "default" or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


class AudioSection:
    """
    音频设备设置区域

    负责音频输入/输出设备选择与测试的 UI 和逻辑。
    """

    def __init__(
        self,
        page: ft.Page,
        theme_manager: ThemeManager,
    ) -> None:
        """
        初始化音频设备设置区域

        Args:
            page: Flet Page 对象
            theme_manager: 主题管理器
        """
        self._page = page
        self._theme_manager = theme_manager
        self._logger = get_logger()

        # UI 组件引用
        self._input_device_dropdown: Optional[ft.Dropdown] = None
        self._output_device_dropdown: Optional[ft.Dropdown] = None
        self._audio_device_status: Optional[ft.Text] = None

    def build(self) -> ft.Container:
        """构建音频设备设置区域"""
        colors = self._theme_manager.get_color_scheme()

        section_title = ft.Text(
            "音频设备",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        info_text = ft.Text(
            "选择用于录音和播放的音频设备。",
            size=10,
            color=colors.text_muted,
        )

        self._input_device_dropdown = ft.Dropdown(
            label="输入设备",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="选择麦克风",
            options=[ft.dropdown.Option("default", "加载中...")],
            value="default",
            on_select=self._on_input_device_changed,
            expand=True,
        )

        self._output_device_dropdown = ft.Dropdown(
            label="输出设备",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="选择扬声器",
            options=[ft.dropdown.Option("default", "加载中...")],
            value="default",
            on_select=self._on_output_device_changed,
            expand=True,
        )

        self._audio_device_status = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        refresh_btn = ft.OutlinedButton(
            "刷新设备列表",
            on_click=self._on_refresh_audio_devices,
            icon=ft.Icons.REFRESH,
            style=ft.ButtonStyle(icon_size=16),
        )

        test_device_btn = ft.ElevatedButton(
            "测试设备",
            on_click=self._on_test_audio_device,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        return ft.Container(
            content=ft.Column(
                [
                    section_title,
                    ft.Container(height=10),
                    info_text,
                    ft.Container(height=16),
                    self._input_device_dropdown,
                    ft.Container(height=10),
                    self._output_device_dropdown,
                    ft.Container(height=10),
                    ft.Row([refresh_btn, test_device_btn]),
                    ft.Container(height=8),
                    self._audio_device_status,
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=10,
        )

    # ==================== 数据获取 ====================

    def get_audio_input_devices(self) -> list[ft.dropdown.Option]:
        """获取音频输入设备选项"""
        options = [ft.dropdown.Option("default", "默认设备")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                if device["max_input_channels"] > 0:
                    options.append(ft.dropdown.Option(str(i), device["name"]))
        except Exception as e:
            self._logger.warning(f"获取音频输入设备列表失败: {e}")
        return options

    def get_audio_output_devices(self) -> list[ft.dropdown.Option]:
        """获取音频输出设备选项"""
        options = [ft.dropdown.Option("default", "默认设备")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                if device["max_output_channels"] > 0:
                    options.append(ft.dropdown.Option(str(i), device["name"]))
        except Exception as e:
            self._logger.warning(f"获取音频输出设备列表失败: {e}")
        return options

    def get_current_input_device(self) -> str:
        """获取当前输入设备配置"""
        device_id = get_config("AUDIO_INPUT_DEVICE") or "default"
        return device_id

    def get_current_output_device(self) -> str:
        """获取当前输出设备配置"""
        device_id = get_config("AUDIO_OUTPUT_DEVICE") or "default"
        return device_id

    def get_input_device_value(self) -> str:
        """获取当前输入设备下拉框的值"""
        if self._input_device_dropdown:
            return self._input_device_dropdown.value or "default"
        return "default"

    # ==================== 事件处理 ====================

    def _on_input_device_changed(self, e: ft.ControlEvent) -> None:
        """输入设备选择变化"""
        if self._input_device_dropdown:
            value = self._input_device_dropdown.value
            set_config("AUDIO_INPUT_DEVICE", value)
            self._logger.info(f"输入设备选择: {value}")

    def _on_output_device_changed(self, e: ft.ControlEvent) -> None:
        """输出设备选择变化"""
        if self._output_device_dropdown:
            value = self._output_device_dropdown.value
            set_config("AUDIO_OUTPUT_DEVICE", value)
            self._logger.info(f"输出设备选择: {value}")

    def _on_refresh_audio_devices(self, e: ft.ControlEvent) -> None:
        """刷新音频设备列表"""
        try:
            if self._input_device_dropdown:
                self._input_device_dropdown.options = self.get_audio_input_devices()
                self._input_device_dropdown.update()
            if self._output_device_dropdown:
                self._output_device_dropdown.options = self.get_audio_output_devices()
                self._output_device_dropdown.update()
            self._show_audio_status("设备列表已刷新")
        except Exception:
            self._logger.exception("刷新音频设备列表失败")
            self._show_audio_status("刷新设备列表失败", error=True)

    def _on_test_audio_device(self, e: ft.ControlEvent) -> None:
        """测试音频设备：录制 3 秒并回放"""
        device_id = _get_device_id(self._input_device_dropdown.value)
        output_id = _get_device_id(self._output_device_dropdown.value)

        self._show_audio_status("正在录制 3 秒音频...")

        def test_thread() -> None:
            try:
                import numpy as np
                import sounddevice as sd
                import wave
                from datetime import datetime

                duration = 3
                sample_rate = 16000
                channels = 1
                dtype = "int16"

                recording = sd.rec(
                    int(duration * sample_rate),
                    samplerate=sample_rate,
                    channels=channels,
                    dtype=dtype,
                    device=device_id,
                )

                for i in range(duration):
                    self._run_on_ui(
                        lambda sec=i + 1: self._show_audio_status(f"正在录音... {sec}/{duration} 秒")
                    )
                    time.sleep(1)

                sd.wait()

                # 保存临时文件
                temp_path = Path("PersonalData") / "records" / f"device_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(temp_path), "wb") as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(recording.tobytes())

                self._run_on_ui(lambda: self._show_audio_status("正在播放录音..."))
                sd.play(recording.astype(np.float32) / 32768.0, samplerate=sample_rate, device=output_id)
                sd.wait()

                self._run_on_ui(lambda: self._show_audio_status(f"设备测试完成，录音已保存到: {temp_path}"))
            except Exception as ex:
                self._logger.exception("音频设备测试失败")
                self._run_on_ui(lambda: self._show_audio_status(f"设备测试失败: {ex}", error=True))

        threading.Thread(target=test_thread, daemon=True).start()

    # ==================== 辅助方法 ====================

    def _show_audio_status(self, message: str, error: bool = False) -> None:
        """显示音频设备状态"""
        if self._audio_device_status:
            colors = self._theme_manager.get_color_scheme()
            self._audio_device_status.value = message
            self._audio_device_status.color = colors.error if error else colors.text_muted
            self._audio_device_status.update()

    def _run_on_ui(self, callback) -> None:
        """在主线程执行 UI 更新回调"""
        try:
            if self._page.platform_thread_id == threading.current_thread().ident:
                callback()
            else:
                # 使用 run_task 在主线程调度异步任务
                async def _wrapper():
                    callback()
                self._page.run_task(_wrapper)
        except Exception:
            try:
                callback()
            except Exception:
                pass
