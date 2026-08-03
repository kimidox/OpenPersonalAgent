"""
ASR 语音识别设置区域

提供 ASR 模型选择、下载、加载、实时测试的配置界面。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import flet as ft

import config
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


class AsrSection:
    """
    ASR 语音识别设置区域

    负责 ASR 模型选择、下载、加载、实时测试的 UI 和逻辑。
    """

    def __init__(
        self,
        page: ft.Page,
        theme_manager: ThemeManager,
        get_input_device_value: Callable[[], str],
    ) -> None:
        """
        初始化 ASR 设置区域

        Args:
            page: Flet Page 对象
            theme_manager: 主题管理器
            get_input_device_value: 获取当前输入设备值的回调
        """
        self._page = page
        self._theme_manager = theme_manager
        self._logger = get_logger()
        self._get_input_device_value = get_input_device_value

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

        # 后台任务控制
        self._asr_test_running = False
        self._asr_download_thread: Optional[threading.Thread] = None
        self._asr_load_thread: Optional[threading.Thread] = None

    def build(self) -> ft.Container:
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
            options=[ft.dropdown.Option("default", "默认模型")],
            value="default",
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

    # ==================== 数据获取 ====================

    def get_asr_model_options(self) -> list[ft.dropdown.Option]:
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

    def get_current_asr_model(self) -> str:
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
                self._asr_model_dropdown.options = self.get_asr_model_options()
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
        self._asr_model_dropdown.options = self.get_asr_model_options()
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

        device_id = _get_device_id(self._get_input_device_value())
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

    # ==================== 辅助方法 ====================

    def refresh_asr_status(self) -> None:
        """刷新 ASR 模型状态显示"""
        try:
            from recorder import is_online_model_loaded
            if is_online_model_loaded():
                self._show_asr_status("模型已加载", error=False)
            else:
                self._show_asr_status("模型未加载", error=False)
        except Exception:
            pass

    def _refresh_asr_status(self) -> None:
        """刷新 ASR 模型状态显示（内部别名）"""
        self.refresh_asr_status()

    def _update_asr_progress(self, value: float, status: str) -> None:
        """更新 ASR 进度条"""
        if self._asr_progress_bar:
            self._asr_progress_bar.value = max(0.0, min(1.0, value))
            self._asr_progress_bar.update()
        self._show_asr_status(status)

    def _set_asr_controls_enabled(self, enabled: bool) -> None:
        """设置 ASR 控件启用状态"""
        if self._asr_model_dropdown:
            self._asr_model_dropdown.disabled = not enabled
            self._asr_model_dropdown.update()

    def _show_asr_status(self, message: str, error: bool = False) -> None:
        """显示 ASR 状态"""
        if self._asr_status_text:
            colors = self._theme_manager.get_color_scheme()
            self._asr_status_text.value = message
            self._asr_status_text.color = colors.error if error else colors.text_muted
            self._asr_status_text.update()

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
