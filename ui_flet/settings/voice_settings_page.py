"""
Flet 语音设置页面

提供 ASR（语音识别）和 TTS（语音合成）的配置界面。
与旧版 PySide6 前端对齐，包含：
- ASR 模型选择、下载、加载、实时测试
- TTS 模型选择、音色、语速、测试朗读
- 音频输入/输出设备选择与测试
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import flet as ft

import config
from config import get_config, set_config
from logger import get_logger
from ui_flet.theme import ThemeManager, get_color

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

        # UI 组件引用
        self._asr_model_dropdown: Optional[ft.Dropdown] = None
        self._asr_model_detail_text: Optional[ft.Text] = None
        self._asr_local_path_field: Optional[ft.TextField] = None
        self._asr_auto_load_switch: Optional[ft.Switch] = None
        self._asr_realtime_switch: Optional[ft.Switch] = None
        self._asr_interval_slider: Optional[ft.Slider] = None
        self._asr_interval_text: Optional[ft.Text] = None
        self._asr_status_text: Optional[ft.Text] = None
        self._asr_progress_bar: Optional[ft.ProgressBar] = None
        self._asr_test_button: Optional[ft.ElevatedButton] = None
        self._asr_test_result: Optional[ft.TextField] = None

        self._tts_model_dropdown: Optional[ft.Dropdown] = None
        self._tts_speaker_dropdown: Optional[ft.Dropdown] = None
        self._tts_speed_slider: Optional[ft.Slider] = None
        self._tts_speed_text: Optional[ft.Text] = None
        self._tts_auto_load_switch: Optional[ft.Switch] = None
        self._tts_auto_download_switch: Optional[ft.Switch] = None
        self._tts_status_text: Optional[ft.Text] = None
        self._tts_progress_bar: Optional[ft.ProgressBar] = None
        self._tts_test_text: Optional[ft.TextField] = None
        self._tts_test_button: Optional[ft.ElevatedButton] = None
        self._tts_stop_button: Optional[ft.ElevatedButton] = None

        self._input_device_dropdown: Optional[ft.Dropdown] = None
        self._output_device_dropdown: Optional[ft.Dropdown] = None
        self._audio_device_status: Optional[ft.Text] = None

        # 后台任务控制
        self._asr_test_running = False
        self._tts_speaking = False
        self._asr_download_thread: Optional[threading.Thread] = None
        self._asr_load_thread: Optional[threading.Thread] = None
        self._tts_load_thread: Optional[threading.Thread] = None

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

        asr_section = self._build_asr_section()
        tts_section = self._build_tts_section()
        audio_section = self._build_audio_section()

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

        # 初始状态刷新
        self._refresh_asr_status()
        self._refresh_tts_status()
        self._refresh_tts_speakers()

        self._logger.info("VoiceSettingsPage: 页面构建完成")
        return self._container

    # ==================== ASR 区域 ====================

    def _build_asr_section(self) -> ft.Container:
        """构建 ASR 设置区域"""
        colors = self._theme_manager.get_color_scheme()

        section_title = ft.Text(
            "ASR 语音识别",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        info_text = ft.Text(
            "使用 sherpa-onnx 流式模型进行实时语音识别。支持边说边识别，适用于实时转写场景。",
            size=10,
            color=colors.text_muted,
        )

        self._asr_model_dropdown = ft.Dropdown(
            label="ASR 模型",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="选择语音识别模型",
            options=self._get_asr_model_options(),
            value=self._get_current_asr_model(),
            on_select=self._on_asr_model_changed,
            expand=True,
        )

        self._asr_model_detail_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        self._asr_local_path_field = ft.TextField(
            label="本地模型路径",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="选择或输入本地模型目录路径...",
            value=get_config("ASR_REALTIME_MODEL_PATH") or "",
            on_change=self._on_asr_local_path_changed,
            expand=True,
        )

        browse_btn = ft.ElevatedButton(
            "浏览",
            on_click=self._on_browse_asr_path,
        )

        self._asr_progress_bar = ft.ProgressBar(
            value=0,
            visible=False,
            height=9,
        )

        self._asr_status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        download_btn = ft.ElevatedButton(
            "下载模型",
            on_click=self._on_download_asr_model,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        load_btn = ft.ElevatedButton(
            "加载模型",
            on_click=self._on_load_asr_model,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        release_btn = ft.OutlinedButton(
            "释放模型",
            on_click=self._on_release_asr_model,
        )

        asr_auto_load_value = get_config("ASR_REALTIME_AUTO_LOAD")
        asr_auto_load = asr_auto_load_value.lower() == "true" if asr_auto_load_value else False
        self._asr_auto_load_switch = ft.Switch(
            label="程序启动时自动加载语音识别模型",
            value=asr_auto_load,
            on_change=self._on_asr_auto_load_changed,
        )

        asr_realtime_enabled = get_config("ASR_REALTIME_ENABLED")
        self._asr_realtime_switch = ft.Switch(
            label="启用实时语音识别（边说边识别）",
            value=asr_realtime_enabled.lower() == "true" if asr_realtime_enabled else True,
            on_change=self._on_asr_realtime_changed,
        )

        current_interval = config.ASR_REALTIME_UPDATE_INTERVAL
        self._asr_interval_text = ft.Text(
            f"实时结果更新间隔: {current_interval}ms",
            size=11, weight=ft.FontWeight.BOLD,
            color=colors.text,
        )
        self._asr_interval_slider = ft.Slider(
            min=50,
            max=1000,
            value=current_interval,
            divisions=19,
            label="{value}ms",
            on_change=self._on_asr_interval_changed,
            expand=True,
        )

        self._asr_test_button = ft.ElevatedButton(
            "开始实时测试",
            on_click=self._on_toggle_asr_test,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        self._asr_test_result = ft.TextField(
            hint_text="实时识别结果将显示在这里...",
            text_size=11,
            multiline=True,
            min_lines=3,
            max_lines=5,
            read_only=True,
            expand=True,
        )

        copy_result_btn = ft.OutlinedButton(
            "复制结果",
            on_click=self._on_copy_asr_result,
        )

        return ft.Container(
            content=ft.Column(
                [
                    section_title,
                    ft.Container(height=10),
                    info_text,
                    ft.Container(height=16),
                    self._asr_model_dropdown,
                    self._asr_model_detail_text,
                    ft.Container(height=10),
                    ft.Row([self._asr_local_path_field, browse_btn]),
                    ft.Container(height=10),
                    self._asr_progress_bar,
                    ft.Row([download_btn, load_btn, release_btn]),
                    ft.Container(height=8),
                    self._asr_status_text,
                    ft.Container(height=10),
                    self._asr_auto_load_switch,
                    self._asr_realtime_switch,
                    ft.Container(height=10),
                    self._asr_interval_text,
                    self._asr_interval_slider,
                    ft.Container(height=16),
                    ft.Text("实时测试", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=10),
                    ft.Row([self._asr_test_button, copy_result_btn]),
                    ft.Container(height=8),
                    self._asr_test_result,
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=10,
        )

    def _get_asr_model_options(self) -> list[ft.dropdown.Option]:
        """获取 ASR 模型选项"""
        options = [ft.dropdown.Option("default", "默认模型（自动下载）")]

        try:
            from recorder import get_streaming_models_list
            models = get_streaming_models_list()
            for key, model_info in models.items():
                display = model_info.get("display_name", key)
                options.append(ft.dropdown.Option(key, display))
        except Exception as e:
            self._logger.warning(f"获取 ASR 模型列表失败: {e}")

        # 扫描本地模型目录
        try:
            from recorder import get_asr_model_dir
            asr_dir = get_asr_model_dir()
            predefined_names = set()
            try:
                from recorder import get_streaming_models_list
                for info in get_streaming_models_list().values():
                    predefined_names.add(info.get("name"))
            except Exception:
                pass

            if asr_dir.exists():
                for subdir in asr_dir.iterdir():
                    if subdir.is_dir() and list(subdir.glob("encoder*.onnx")):
                        if subdir.name not in predefined_names:
                            custom_key = f"custom:{subdir.name}"
                            options.append(ft.dropdown.Option(custom_key, f"[本地] {subdir.name}"))
        except Exception as e:
            self._logger.warning(f"扫描本地 ASR 模型失败: {e}")

        return options

    def _get_current_asr_model(self) -> str:
        """获取当前 ASR 模型配置"""
        saved_path = get_config("ASR_REALTIME_MODEL_PATH") or ""
        if not saved_path:
            return "default"

        # 如果是已下载预设模型目录，尝试匹配 key
        try:
            from recorder import get_streaming_models_list, get_asr_model_dir
            models = get_streaming_models_list()
            asr_dir = get_asr_model_dir()
            saved_name = Path(saved_path).name
            for key, info in models.items():
                if info.get("name") == saved_name:
                    return key
            # 本地模型
            if Path(saved_path).exists() and list(Path(saved_path).glob("encoder*.onnx")):
                return f"custom:{saved_name}"
        except Exception:
            pass

        return "default"

    def _update_asr_model_detail(self) -> None:
        """更新 ASR 模型详情显示"""
        if not self._asr_model_dropdown or not self._asr_model_detail_text:
            return

        value = self._asr_model_dropdown.value or "default"
        if value == "default":
            self._asr_model_detail_text.value = "使用默认模型，首次加载时会自动下载。"
            return

        if value.startswith("custom:"):
            self._asr_model_detail_text.value = f"[本地导入] {value[7:]}"
            return

        try:
            from recorder import get_streaming_models_list
            models = get_streaming_models_list()
            info = models.get(value)
            if info:
                size = info.get("size_mb", "?")
                languages = ", ".join(info.get("languages", []))
                self._asr_model_detail_text.value = f"大小: {size}MB | 语言: {languages}"
                return
        except Exception:
            pass

        self._asr_model_detail_text.value = ""

    # ==================== TTS 区域 ====================

    def _build_tts_section(self) -> ft.Container:
        """构建 TTS 设置区域"""
        colors = self._theme_manager.get_color_scheme()

        section_title = ft.Text(
            "TTS 语音合成",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=colors.text,
        )

        info_text = ft.Text(
            "使用 sherpa-onnx VITS 模型进行本地文本转语音。支持自定义导入模型或使用默认中文模型。",
            size=10,
            color=colors.text_muted,
        )

        self._tts_model_dropdown = ft.Dropdown(
            label="TTS 模型类型",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="选择语音合成模型",
            options=self._get_tts_model_options(),
            value=self._get_current_tts_model(),
            on_select=self._on_tts_model_changed,
            expand=True,
        )

        current_speaker = config.TTS_SPEAKER_ID
        self._tts_speaker_dropdown = ft.Dropdown(
            label="音色",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="加载模型后选择音色",
            options=[ft.dropdown.Option("0", "默认")],
            value=str(current_speaker),
            on_select=self._on_tts_speaker_changed,
            expand=True,
        )

        current_speed = config.TTS_SPEED
        speed_value = int(current_speed * 100)
        self._tts_speed_text = ft.Text(
            f"语速: {current_speed:.1f}x",
            size=11, weight=ft.FontWeight.BOLD,
            color=colors.text,
        )
        self._tts_speed_slider = ft.Slider(
            min=50,
            max=200,
            value=speed_value,
            divisions=15,
            label="{value}%",
            on_change=self._on_tts_speed_changed,
            expand=True,
        )

        tts_auto_load = get_config("TTS_AUTO_LOAD")
        self._tts_auto_load_switch = ft.Switch(
            label="程序启动时自动加载语音合成模型",
            value=tts_auto_load.lower() == "true" if tts_auto_load else False,
            on_change=self._on_tts_auto_load_changed,
        )

        tts_auto_download = get_config("TTS_AUTO_DOWNLOAD")
        self._tts_auto_download_switch = ft.Switch(
            label="模型不存在时自动下载",
            value=tts_auto_download.lower() != "false" if tts_auto_download else True,
            on_change=self._on_tts_auto_download_changed,
        )

        self._tts_progress_bar = ft.ProgressBar(
            value=0,
            visible=False,
            height=9,
        )

        self._tts_status_text = ft.Text(
            "",
            size=10,
            color=colors.text_muted,
        )

        load_btn = ft.ElevatedButton(
            "加载模型",
            on_click=self._on_load_tts_model,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        release_btn = ft.OutlinedButton(
            "释放模型",
            on_click=self._on_release_tts_model,
        )

        save_params_btn = ft.ElevatedButton(
            "保存参数",
            on_click=self._on_save_tts_params,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        self._tts_test_text = ft.TextField(
            label="测试文本",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            value="你好，这是一个语音合成测试。",
            expand=True,
        )

        self._tts_test_button = ft.ElevatedButton(
            "开始朗读",
            on_click=self._on_test_tts,
            style=ft.ButtonStyle(
                color=colors.text,
                bgcolor=colors.surface,
            ),
        )

        self._tts_stop_button = ft.OutlinedButton(
            "停止朗读",
            on_click=self._on_stop_tts,
            disabled=True,
        )

        custom_info = ft.Text(
            "支持导入自定义 VITS ONNX 模型：模型目录需包含 model.onnx、tokens.txt、lexicon.txt；"
            "多音色模型需包含 dict/ 目录。可下载其他预训练模型：github.com/k2-fsa/sherpa-onnx/releases",
            size=10,
            color=colors.text_muted,
        )

        return ft.Container(
            content=ft.Column(
                [
                    section_title,
                    ft.Container(height=10),
                    info_text,
                    ft.Container(height=16),
                    self._tts_model_dropdown,
                    ft.Container(height=10),
                    self._tts_speaker_dropdown,
                    ft.Container(height=10),
                    self._tts_speed_text,
                    self._tts_speed_slider,
                    ft.Container(height=10),
                    ft.Row([load_btn, release_btn, save_params_btn]),
                    self._tts_progress_bar,
                    ft.Container(height=8),
                    self._tts_status_text,
                    ft.Container(height=10),
                    self._tts_auto_load_switch,
                    self._tts_auto_download_switch,
                    ft.Container(height=16),
                    ft.Text("测试朗读", size=12, weight=ft.FontWeight.BOLD, color=colors.text),
                    ft.Container(height=10),
                    self._tts_test_text,
                    ft.Container(height=10),
                    ft.Row([self._tts_test_button, self._tts_stop_button]),
                    ft.Container(height=16),
                    custom_info,
                ],
                spacing=0,
            ),
            bgcolor=colors.surface,
            padding=16,
            border_radius=10,
        )

    def _get_tts_model_options(self) -> list[ft.dropdown.Option]:
        """获取 TTS 模型选项"""
        options = [
            ft.dropdown.Option("zh", "中文模型（sherpa-onnx-vits-zh-ll）"),
            ft.dropdown.Option("zh_en", "中英文模型（vits-melo-tts-zh_en）"),
        ]

        try:
            from tts import get_local_tts_models_list
            local_models = get_local_tts_models_list()
            for model_name, model_path in local_models.items():
                options.append(ft.dropdown.Option(model_path, f"本地: {model_name}"))
        except Exception as e:
            self._logger.warning(f"获取本地 TTS 模型列表失败: {e}")

        return options

    def _get_current_tts_model(self) -> str:
        """获取当前 TTS 模型配置"""
        model_type = get_config("TTS_MODEL_TYPE") or "zh"
        model_path = get_config("TTS_MODEL_PATH")

        if model_path:
            return model_path
        return model_type

    def _refresh_tts_speakers(self) -> None:
        """刷新 TTS 音色列表"""
        if not self._tts_speaker_dropdown:
            return

        options = [ft.dropdown.Option("0", "默认")]
        current_speaker = config.TTS_SPEAKER_ID

        try:
            from tts import get_num_speakers
            num = get_num_speakers()
            if num > 1:
                # 中文模型预置音色名称
                speaker_names = [
                    "苏映雪（女声）", "顾念（女声）", "付思雨（女声）",
                    "冰娇（女声）", "巴总（男声）",
                ]
                for i in range(num):
                    name = speaker_names[i] if i < len(speaker_names) else f"音色 {i}"
                    options.append(ft.dropdown.Option(str(i), name))
                if current_speaker >= num:
                    current_speaker = 0
        except Exception as e:
            self._logger.warning(f"刷新 TTS 音色列表失败: {e}")

        self._tts_speaker_dropdown.options = options
        self._tts_speaker_dropdown.value = str(current_speaker)

    # ==================== 音频设备区域 ====================

    def _build_audio_section(self) -> ft.Container:
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
            options=self._get_audio_input_devices(),
            value=self._get_current_input_device(),
            on_select=self._on_input_device_changed,
            expand=True,
        )

        self._output_device_dropdown = ft.Dropdown(
            label="输出设备",
            label_style=ft.TextStyle(size=11),
            text_size=11,
            hint_text="选择扬声器",
            options=self._get_audio_output_devices(),
            value=self._get_current_output_device(),
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

    def _get_audio_input_devices(self) -> list[ft.dropdown.Option]:
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

    def _get_audio_output_devices(self) -> list[ft.dropdown.Option]:
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

    def _get_current_input_device(self) -> str:
        """获取当前输入设备配置"""
        device_id = get_config("AUDIO_INPUT_DEVICE") or "default"
        return device_id

    def _get_current_output_device(self) -> str:
        """获取当前输出设备配置"""
        device_id = get_config("AUDIO_OUTPUT_DEVICE") or "default"
        return device_id

    # ==================== 事件处理 ====================

    def _on_asr_model_changed(self, e: ft.ControlEvent) -> None:
        """ASR 模型选择变化"""
        if not self._asr_model_dropdown:
            return

        value = self._asr_model_dropdown.value or "default"
        self._logger.info(f"ASR 模型选择: {value}")
        self._update_asr_model_detail()

        # 持久化选择
        if value == "default":
            set_config("ASR_REALTIME_MODEL_PATH", "")
            config.ASR_REALTIME_MODEL_PATH = ""
        elif value.startswith("custom:"):
            try:
                from recorder import get_asr_model_dir
                model_name = value[7:]
                model_path = str(get_asr_model_dir() / model_name)
                set_config("ASR_REALTIME_MODEL_PATH", model_path)
                config.ASR_REALTIME_MODEL_PATH = model_path
            except Exception:
                pass
        else:
            try:
                from recorder import get_streaming_models_list, get_asr_model_dir
                models = get_streaming_models_list()
                model_name = models.get(value, {}).get("name", value)
                model_path = str(get_asr_model_dir() / model_name)
                set_config("ASR_REALTIME_MODEL_PATH", model_path)
                config.ASR_REALTIME_MODEL_PATH = model_path
            except Exception:
                pass

        self._refresh_asr_status()

    def _on_asr_local_path_changed(self, e: ft.ControlEvent) -> None:
        """ASR 本地路径变化"""
        if not self._asr_local_path_field:
            return

        path = self._asr_local_path_field.value or ""
        set_config("ASR_REALTIME_MODEL_PATH", path)
        config.ASR_REALTIME_MODEL_PATH = path

        # 如果路径有效，尝试匹配下拉选项
        if path and Path(path).exists() and list(Path(path).glob("encoder*.onnx")):
            model_name = Path(path).name
            custom_key = f"custom:{model_name}"
            found = False
            for opt in self._asr_model_dropdown.options:
                if opt.key == custom_key:
                    self._asr_model_dropdown.value = custom_key
                    found = True
                    break
            if not found:
                self._asr_model_dropdown.options = self._get_asr_model_options()
                self._asr_model_dropdown.value = custom_key
            self._update_asr_model_detail()

    async def _on_browse_asr_path(self, e: ft.ControlEvent) -> None:
        """浏览 ASR 本地模型路径"""
        picker = ft.FilePicker()
        self._page.services.append(picker)
        self._page.update()
        path = await picker.get_directory_path()
        if path and self._asr_local_path_field:
            self._asr_local_path_field.value = path
            self._on_asr_local_path_changed(None)
            self._asr_local_path_field.update()

    def _on_asr_auto_load_changed(self, e: ft.ControlEvent) -> None:
        """ASR 自动加载开关变化"""
        if self._asr_auto_load_switch:
            value = self._asr_auto_load_switch.value
            set_config("ASR_REALTIME_AUTO_LOAD", str(value).lower())
            config.ASR_REALTIME_AUTO_LOAD = value
            self._logger.info(f"ASR 自动加载: {value}")

    def _on_asr_realtime_changed(self, e: ft.ControlEvent) -> None:
        """ASR 实时识别开关变化"""
        if self._asr_realtime_switch:
            value = self._asr_realtime_switch.value
            set_config("ASR_REALTIME_ENABLED", str(value).lower())
            config.ASR_REALTIME_ENABLED = value
            self._logger.info(f"ASR 实时识别: {value}")

    def _on_asr_interval_changed(self, e: ft.ControlEvent) -> None:
        """ASR 更新间隔变化"""
        if self._asr_interval_slider:
            value = int(self._asr_interval_slider.value)
            set_config("ASR_REALTIME_UPDATE_INTERVAL", str(value))
            config.ASR_REALTIME_UPDATE_INTERVAL = value
            if self._asr_interval_text:
                self._asr_interval_text.value = f"实时结果更新间隔: {value}ms"
                self._asr_interval_text.update()

    def _on_download_asr_model(self, e: ft.ControlEvent) -> None:
        """下载 ASR 模型"""
        if not self._asr_model_dropdown:
            return

        value = self._asr_model_dropdown.value or "default"
        if value == "default":
            try:
                from recorder import get_default_model_key
                model_key = get_default_model_key()
            except Exception:
                self._show_asr_status("无法获取默认模型", error=True)
                return
        elif value.startswith("custom:"):
            self._show_asr_status("本地模型无需下载", error=True)
            return
        else:
            model_key = value

        self._set_asr_controls_enabled(False)
        self._asr_progress_bar.visible = True
        self._asr_progress_bar.value = 0
        self._show_asr_status("正在准备下载...")

        def download_thread() -> None:
            try:
                from recorder import download_specific_online_model

                def callback(progress: int, status: str) -> None:
                    self._run_on_ui(lambda: self._update_asr_progress(progress / 100.0, status))

                path = download_specific_online_model(model_key, callback=callback)
                if path:
                    self._run_on_ui(lambda: self._on_asr_download_finished(str(path)))
                else:
                    self._run_on_ui(lambda: self._on_asr_download_error("下载失败"))
            except Exception as ex:
                self._run_on_ui(lambda: self._on_asr_download_error(str(ex)))

        self._asr_download_thread = threading.Thread(target=download_thread, daemon=True)
        self._asr_download_thread.start()

    def _on_asr_download_finished(self, path: str) -> None:
        """ASR 下载完成"""
        self._asr_progress_bar.visible = False
        self._set_asr_controls_enabled(True)
        self._show_asr_status(f"模型下载完成: {path}", error=False)
        # 刷新下拉框以显示新下载的模型
        current_value = self._asr_model_dropdown.value
        self._asr_model_dropdown.options = self._get_asr_model_options()
        self._asr_model_dropdown.value = current_value
        self._asr_model_dropdown.update()

    def _on_asr_download_error(self, message: str) -> None:
        """ASR 下载失败"""
        self._asr_progress_bar.visible = False
        self._set_asr_controls_enabled(True)
        self._show_asr_status(f"下载失败: {message}", error=True)

    def _on_load_asr_model(self, e: ft.ControlEvent) -> None:
        """加载 ASR 模型"""
        self._set_asr_controls_enabled(False)
        self._asr_progress_bar.visible = True
        self._asr_progress_bar.value = 0
        self._show_asr_status("正在加载 ASR 模型...")

        def load_thread() -> None:
            try:
                from recorder import load_online_model

                def callback(progress: int, status: str) -> None:
                    self._run_on_ui(lambda: self._update_asr_progress(progress / 100.0, status))

                model_path = config.ASR_REALTIME_MODEL_PATH or None
                success = load_online_model(model_path=model_path, callback=callback)
                self._run_on_ui(lambda: self._on_asr_load_finished(success))
            except Exception as ex:
                self._run_on_ui(lambda: self._on_asr_load_finished(False, str(ex)))

        self._asr_load_thread = threading.Thread(target=load_thread, daemon=True)
        self._asr_load_thread.start()

    def _on_asr_load_finished(self, success: bool, message: str = "") -> None:
        """ASR 加载完成"""
        self._asr_progress_bar.visible = False
        self._set_asr_controls_enabled(True)
        if success:
            self._show_asr_status("ASR 模型加载成功", error=False)
        else:
            self._show_asr_status(f"ASR 模型加载失败: {message}", error=True)

    def _on_release_asr_model(self, e: ft.ControlEvent) -> None:
        """释放 ASR 模型"""
        try:
            from recorder import release_online_model
            release_online_model()
            self._show_asr_status("ASR 模型已释放", error=False)
        except Exception:
            self._logger.exception("释放 ASR 模型失败")
            self._show_asr_status("释放 ASR 模型失败", error=True)

    def _on_toggle_asr_test(self, e: ft.ControlEvent) -> None:
        """切换 ASR 实时测试"""
        if self._asr_test_running:
            self._asr_test_running = False
            self._asr_test_button.text = "开始实时测试"
            self._asr_test_button.update()
            return

        try:
            from recorder import is_online_model_loaded
            if not is_online_model_loaded():
                self._show_asr_status("请先加载 ASR 模型", error=True)
                return
        except Exception:
            self._show_asr_status("无法检查模型状态", error=True)
            return

        device_id = self._get_device_id(self._input_device_dropdown.value)
        self._asr_test_running = True
        self._asr_test_button.text = "停止实时测试"
        self._asr_test_result.value = ""
        self._asr_test_result.update()
        self._asr_test_button.update()
        self._show_asr_status("正在初始化实时测试...")

        def test_thread() -> None:
            try:
                import numpy as np
                from recorder import (
                    create_online_stream,
                    destroy_online_stream,
                    get_online_stream_result,
                    process_online_stream,
                )

                if not create_online_stream():
                    self._run_on_ui(lambda: self._show_asr_status("创建识别流失败", error=True))
                    return

                self._run_on_ui(lambda: self._show_asr_status("请说话..."))

                import sounddevice as sd

                def audio_callback(indata, frames, time_info, status):
                    if not self._asr_test_running:
                        raise sd.CallbackStop
                    try:
                        audio_data = indata[:, 0].astype(np.int16)
                        process_online_stream(audio_data, 16000)
                        result = get_online_stream_result()
                        if result:
                            self._run_on_ui(lambda r=result: self._append_asr_result(r))
                    except Exception as ex:
                        self._logger.warning(f"实时测试音频处理异常: {ex}")

                with sd.InputStream(
                    device=device_id,
                    samplerate=16000,
                    channels=1,
                    dtype="int16",
                    callback=audio_callback,
                    blocksize=512,
                ):
                    while self._asr_test_running:
                        time.sleep(0.1)

                time.sleep(0.2)
                final = get_online_stream_result()
                if final:
                    self._run_on_ui(lambda: self._append_asr_result(f"[最终结果] {final}"))
                destroy_online_stream()
                self._run_on_ui(lambda: self._show_asr_status("测试完成", error=False))
            except Exception as ex:
                self._logger.exception("实时测试异常")
                self._run_on_ui(lambda: self._show_asr_status(f"测试异常: {ex}", error=True))
            finally:
                self._run_on_ui(self._reset_asr_test_button)

        threading.Thread(target=test_thread, daemon=True).start()

    def _append_asr_result(self, text: str) -> None:
        """追加 ASR 测试结果"""
        if self._asr_test_result:
            current = self._asr_test_result.value or ""
            self._asr_test_result.value = f"{current}\n{text}".strip()
            self._asr_test_result.update()

    def _on_copy_asr_result(self, e: ft.ControlEvent) -> None:
        """复制 ASR 测试结果"""
        if self._asr_test_result and self._asr_test_result.value:
            self._page.set_clipboard(self._asr_test_result.value)
            self._show_asr_status("已复制到剪贴板", error=False)

    def _reset_asr_test_button(self) -> None:
        """重置 ASR 测试按钮状态"""
        self._asr_test_running = False
        if self._asr_test_button:
            self._asr_test_button.text = "开始实时测试"
            self._asr_test_button.update()

    def _on_tts_model_changed(self, e: ft.ControlEvent) -> None:
        """TTS 模型选择变化"""
        if not self._tts_model_dropdown:
            return

        value = self._tts_model_dropdown.value or "zh"
        if value in ("zh", "zh_en"):
            set_config("TTS_MODEL_TYPE", value)
            config.TTS_MODEL_TYPE = value
            set_config("TTS_MODEL_PATH", "")
            config.TTS_MODEL_PATH = ""
        else:
            set_config("TTS_MODEL_PATH", value)
            config.TTS_MODEL_PATH = value
        self._logger.info(f"TTS 模型选择: {value}")

    def _on_tts_speaker_changed(self, e: ft.ControlEvent) -> None:
        """TTS 音色选择变化"""
        if self._tts_speaker_dropdown:
            try:
                speaker_id = int(self._tts_speaker_dropdown.value or "0")
                set_config("TTS_SPEAKER_ID", str(speaker_id))
                config.TTS_SPEAKER_ID = speaker_id
            except ValueError:
                pass

    def _on_tts_speed_changed(self, e: ft.ControlEvent) -> None:
        """TTS 语速调节"""
        if self._tts_speed_slider:
            speed_percent = self._tts_speed_slider.value
            speed = speed_percent / 100.0
            if self._tts_speed_text:
                self._tts_speed_text.value = f"语速: {speed:.1f}x"
                self._tts_speed_text.update()

    def _on_tts_auto_load_changed(self, e: ft.ControlEvent) -> None:
        """TTS 自动加载开关变化"""
        if self._tts_auto_load_switch:
            value = self._tts_auto_load_switch.value
            set_config("TTS_AUTO_LOAD", str(value).lower())
            config.TTS_AUTO_LOAD = value
            self._logger.info(f"TTS 自动加载: {value}")

    def _on_tts_auto_download_changed(self, e: ft.ControlEvent) -> None:
        """TTS 自动下载开关变化"""
        if self._tts_auto_download_switch:
            value = self._tts_auto_download_switch.value
            set_config("TTS_AUTO_DOWNLOAD", str(value).lower())
            config.TTS_AUTO_DOWNLOAD = value
            self._logger.info(f"TTS 自动下载: {value}")

    def _on_save_tts_params(self, e: ft.ControlEvent) -> None:
        """保存 TTS 参数"""
        if self._tts_speed_slider:
            speed = self._tts_speed_slider.value / 100.0
            set_config("TTS_SPEED", str(speed))
            config.TTS_SPEED = speed
        if self._tts_speaker_dropdown:
            try:
                speaker_id = int(self._tts_speaker_dropdown.value or "0")
                set_config("TTS_SPEAKER_ID", str(speaker_id))
                config.TTS_SPEAKER_ID = speaker_id
            except ValueError:
                pass
        self._show_tts_status("参数已保存", error=False)

    def _on_load_tts_model(self, e: ft.ControlEvent) -> None:
        """加载 TTS 模型"""
        self._set_tts_controls_enabled(False)
        self._tts_progress_bar.visible = True
        self._tts_progress_bar.value = 0
        self._show_tts_status("正在加载 TTS 模型...")

        def load_thread() -> None:
            try:
                from tts import load_tts_model

                def callback(progress: int, status: str) -> None:
                    self._run_on_ui(lambda: self._update_tts_progress(progress / 100.0, status))

                model_type = config.TTS_MODEL_TYPE
                model_path = config.TTS_MODEL_PATH or None
                success = load_tts_model(
                    model_path=model_path,
                    model_type=model_type,
                    callback=callback,
                    auto_download=config.TTS_AUTO_DOWNLOAD,
                )
                self._run_on_ui(lambda: self._on_tts_load_finished(success))
            except Exception as ex:
                self._run_on_ui(lambda: self._on_tts_load_finished(False, str(ex)))

        self._tts_load_thread = threading.Thread(target=load_thread, daemon=True)
        self._tts_load_thread.start()

    def _on_tts_load_finished(self, success: bool, message: str = "") -> None:
        """TTS 加载完成"""
        self._tts_progress_bar.visible = False
        self._set_tts_controls_enabled(True)
        if success:
            self._show_tts_status("TTS 模型加载成功", error=False)
            self._refresh_tts_speakers()
            if self._tts_speaker_dropdown:
                self._tts_speaker_dropdown.update()
        else:
            self._show_tts_status(f"TTS 模型加载失败: {message}", error=True)

    def _on_release_tts_model(self, e: ft.ControlEvent) -> None:
        """释放 TTS 模型"""
        try:
            from tts import release_tts_model
            release_tts_model()
            self._show_tts_status("TTS 模型已释放", error=False)
            self._refresh_tts_speakers()
            if self._tts_speaker_dropdown:
                self._tts_speaker_dropdown.update()
        except Exception:
            self._logger.exception("释放 TTS 模型失败")
            self._show_tts_status("释放 TTS 模型失败", error=True)

    def _on_test_tts(self, e: ft.ControlEvent) -> None:
        """测试 TTS 朗读"""
        try:
            from tts import is_tts_model_loaded, speak_text
            if not is_tts_model_loaded():
                self._show_tts_status("请先加载 TTS 模型", error=True)
                return
        except Exception:
            self._show_tts_status("无法检查 TTS 模型状态", error=True)
            return

        text = self._tts_test_text.value or "你好，这是一个语音合成测试。"
        speaker_id = config.TTS_SPEAKER_ID
        speed = config.TTS_SPEED

        self._tts_speaking = True
        self._tts_test_button.disabled = True
        self._tts_stop_button.disabled = False
        self._tts_test_button.update()
        self._tts_stop_button.update()
        self._show_tts_status("正在朗读...")

        def on_finished() -> None:
            self._tts_speaking = False
            self._run_on_ui(lambda: self._show_tts_status("朗读完成", error=False))
            self._run_on_ui(self._reset_tts_test_buttons)

        try:
            speak_text(text, speaker_id=speaker_id, speed=speed, on_finished=on_finished)
        except Exception as ex:
            self._tts_speaking = False
            self._show_tts_status(f"朗读失败: {ex}", error=True)
            self._reset_tts_test_buttons()

    def _on_stop_tts(self, e: ft.ControlEvent) -> None:
        """停止 TTS 朗读"""
        try:
            from tts import stop_speaking
            stop_speaking()
        except Exception:
            self._logger.exception("停止 TTS 失败")
        self._tts_speaking = False
        self._show_tts_status("已停止朗读", error=False)
        self._reset_tts_test_buttons()

    def _reset_tts_test_buttons(self) -> None:
        """重置 TTS 测试按钮状态"""
        if self._tts_test_button:
            self._tts_test_button.disabled = False
            self._tts_test_button.update()
        if self._tts_stop_button:
            self._tts_stop_button.disabled = True
            self._tts_stop_button.update()

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
                self._input_device_dropdown.options = self._get_audio_input_devices()
                self._input_device_dropdown.update()
            if self._output_device_dropdown:
                self._output_device_dropdown.options = self._get_audio_output_devices()
                self._output_device_dropdown.update()
            self._show_audio_status("设备列表已刷新")
        except Exception:
            self._logger.exception("刷新音频设备列表失败")
            self._show_audio_status("刷新设备列表失败", error=True)

    def _on_test_audio_device(self, e: ft.ControlEvent) -> None:
        """测试音频设备：录制 3 秒并回放"""
        device_id = self._get_device_id(self._input_device_dropdown.value)
        output_id = self._get_device_id(self._output_device_dropdown.value)

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

    def _get_device_id(self, value: str) -> Optional[int]:
        """将下拉框值转换为设备 ID"""
        if value is None or value == "default" or value == "":
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _refresh_asr_status(self) -> None:
        """刷新 ASR 模型状态显示"""
        try:
            from recorder import is_online_model_loaded
            if is_online_model_loaded():
                self._show_asr_status("模型已加载", error=False)
            else:
                self._show_asr_status("模型未加载", error=False)
        except Exception:
            pass

    def _refresh_tts_status(self) -> None:
        """刷新 TTS 模型状态显示"""
        try:
            from tts import is_tts_model_loaded
            if is_tts_model_loaded():
                self._show_tts_status("模型已加载", error=False)
            else:
                self._show_tts_status("模型未加载", error=False)
        except Exception:
            pass

    def _update_asr_progress(self, value: float, status: str) -> None:
        """更新 ASR 进度条"""
        if self._asr_progress_bar:
            self._asr_progress_bar.value = max(0.0, min(1.0, value))
            self._asr_progress_bar.update()
        self._show_asr_status(status)

    def _update_tts_progress(self, value: float, status: str) -> None:
        """更新 TTS 进度条"""
        if self._tts_progress_bar:
            self._tts_progress_bar.value = max(0.0, min(1.0, value))
            self._tts_progress_bar.update()
        self._show_tts_status(status)

    def _set_asr_controls_enabled(self, enabled: bool) -> None:
        """设置 ASR 控件启用状态"""
        if self._asr_model_dropdown:
            self._asr_model_dropdown.disabled = not enabled
            self._asr_model_dropdown.update()

    def _set_tts_controls_enabled(self, enabled: bool) -> None:
        """设置 TTS 控件启用状态"""
        if self._tts_model_dropdown:
            self._tts_model_dropdown.disabled = not enabled
            self._tts_model_dropdown.update()

    def _show_asr_status(self, message: str, error: bool = False) -> None:
        """显示 ASR 状态"""
        if self._asr_status_text:
            colors = self._theme_manager.get_color_scheme()
            self._asr_status_text.value = message
            self._asr_status_text.color = colors.error if error else colors.text_muted
            self._asr_status_text.update()

    def _show_tts_status(self, message: str, error: bool = False) -> None:
        """显示 TTS 状态"""
        if self._tts_status_text:
            colors = self._theme_manager.get_color_scheme()
            self._tts_status_text.value = message
            self._tts_status_text.color = colors.error if error else colors.text_muted
            self._tts_status_text.update()

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
                self._page.run(callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass
