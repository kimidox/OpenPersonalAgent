"""
TTS 语音合成设置区域

提供 TTS 模型选择、音色、语速、测试朗读的配置界面。
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

import flet as ft

import config
from config import get_config, set_config
from logger import get_logger
from ui_flet.theme import ThemeManager

if TYPE_CHECKING:
    pass


class TtsSection:
    """
    TTS 语音合成设置区域

    负责 TTS 模型选择、音色、语速、测试朗读的 UI 和逻辑。
    """

    def __init__(
        self,
        page: ft.Page,
        theme_manager: ThemeManager,
    ) -> None:
        """
        初始化 TTS 设置区域

        Args:
            page: Flet Page 对象
            theme_manager: 主题管理器
        """
        self._page = page
        self._theme_manager = theme_manager
        self._logger = get_logger()

        # UI 组件引用
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

        # 后台任务控制
        self._tts_speaking = False
        self._tts_load_thread: Optional[threading.Thread] = None

    def build(self) -> ft.Container:
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
            options=[ft.dropdown.Option("default", "默认模型")],
            value="default",
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

    # ==================== 数据获取 ====================

    def get_tts_model_options(self) -> list[ft.dropdown.Option]:
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

    def get_current_tts_model(self) -> str:
        """获取当前 TTS 模型配置"""
        model_type = get_config("TTS_MODEL_TYPE") or "zh"
        model_path = get_config("TTS_MODEL_PATH")

        if model_path:
            return model_path
        return model_type

    def refresh_tts_speakers(self) -> None:
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

    # ==================== 事件处理 ====================

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
            self.refresh_tts_speakers()
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
            self.refresh_tts_speakers()
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

    # ==================== 辅助方法 ====================

    def refresh_tts_status(self) -> None:
        """刷新 TTS 模型状态显示"""
        try:
            from tts import is_tts_model_loaded
            if is_tts_model_loaded():
                self._show_tts_status("模型已加载", error=False)
            else:
                self._show_tts_status("模型未加载", error=False)
        except Exception:
            pass

    def _update_tts_progress(self, value: float, status: str) -> None:
        """更新 TTS 进度条"""
        if self._tts_progress_bar:
            self._tts_progress_bar.value = max(0.0, min(1.0, value))
            self._tts_progress_bar.update()
        self._show_tts_status(status)

    def _set_tts_controls_enabled(self, enabled: bool) -> None:
        """设置 TTS 控件启用状态"""
        if self._tts_model_dropdown:
            self._tts_model_dropdown.disabled = not enabled
            self._tts_model_dropdown.update()

    def _show_tts_status(self, message: str, error: bool = False) -> None:
        """显示 TTS 状态"""
        if self._tts_status_text:
            colors = self._theme_manager.get_color_scheme()
            self._tts_status_text.value = message
            self._tts_status_text.color = colors.error if error else colors.text_muted
            self._tts_status_text.update()

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
