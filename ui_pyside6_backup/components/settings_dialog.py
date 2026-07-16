from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from logger import get_module_logger

logger = get_module_logger("settings_dialog")

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from llm.llm_config_manager import (
    LLMConfig,
    LLMConfigItem,
    add_config,
    delete_config,
    generate_config_id,
    get_active_config_item,
    get_current_config,
    get_current_multi_config,
    get_switch_events,
    is_auto_switch_enabled,
    list_configs,
    move_config_down,
    move_config_up,
    reset_to_default,
    set_active_config,
    set_multi_config,
    update_config,
)
import autostart
import config
import scheduled_tasks
from scheduled_tasks import NotificationType, RepeatType, ScheduledTask, TaskStatus
from skill_agent_preferences import load_disabled_skill_ids, save_disabled_skill_ids
from ui.styles.style_manager import StyleManager
from recorder import (
    check_gpu_available,
    get_recorder,
    # 流式模型相关函数
    load_online_model,
    release_online_model,
    is_online_model_loaded,
    get_online_model_path,
    get_online_device,
    # 实时识别流相关函数
    create_online_stream,
    process_online_stream,
    get_online_stream_result,
    destroy_online_stream,
    # 模型下载函数
    download_onnx_model as download_online_model,
    download_specific_online_model,
    get_default_model_dir,
    get_asr_model_dir,  # 新增：ASR 模型目录
    ensure_model_dirs,  # 新增：确保模型目录存在
    migrate_models_to_separate_dirs,  # 新增：模型迁移
    identify_model_type,  # 新增：模型类型识别
    # 流式模型配置
    get_streaming_models_list,
    get_default_model_key,
    DEFAULT_ONLINE_MODEL_NAME,
)
from prompt_template_config import (
    get_template_for_conversation_type,
    update_template_for_conversation_type,
    reset_template_for_conversation_type,
    get_all_placeholder_descriptions,
    get_all_conversation_types_with_display_names,
    validate_template,
)
from prompt.dynamic_prompt import DynamicSystemPrompt

if TYPE_CHECKING:
    from skill_agent import SkillAgent


class RealtimeModelDownloadWorker(QThread):
    """流式模型下载工作线程"""

    progress_updated = Signal(int, str)  # (progress, status)
    finished = Signal(str)  # downloaded path
    error = Signal(str)  # error message

    def __init__(self, model_key: str = None, parent=None) -> None:
        super().__init__(parent)
        self._model_key = model_key or get_default_model_key()

    def run(self) -> None:
        """执行流式模型下载"""
        try:
            # 获取模型配置
            models = get_streaming_models_list()
            model_config = models.get(self._model_key)
            if model_config:
                display_name = model_config["display_name"]
            else:
                display_name = "流式模型"
            
            self.progress_updated.emit(5, f"正在准备下载 {display_name}...")
            
            def download_callback(progress: int, status: str):
                self.progress_updated.emit(progress, status)
            
            downloaded_path = download_specific_online_model(self._model_key, callback=download_callback)
            
            if downloaded_path:
                self.progress_updated.emit(100, f"{display_name} 下载完成")
                self.finished.emit(str(downloaded_path))
            else:
                self.error.emit(f"{display_name} 下载失败")
                
        except Exception as e:
            logger.exception(f"下载流式模型时发生错误: {e}")
            self.error.emit(str(e))


class RealtimeModelImportWorker(QThread):
    """流式模型导入工作线程"""

    progress_updated = Signal(int, str)  # (progress, status)
    finished = Signal(str)  # imported path
    error = Signal(str)  # error message

    def __init__(self, source_path: str, model_name: str, parent=None) -> None:
        super().__init__(parent)
        self._source_path = source_path
        self._model_name = model_name

    def run(self) -> None:
        """执行模型导入"""
        import tarfile
        import shutil
        
        try:
            model_dir = get_default_model_dir()
            target_dir = model_dir / self._model_name
            
            # 如果是 tar.bz2 文件，解压
            if self._source_path.endswith('.tar.bz2'):
                self.progress_updated.emit(0, "正在解压模型文件...")
                
                # 解压
                with tarfile.open(self._source_path, 'r:bz2') as tar:
                    # 获取压缩包内的目录名
                    members = tar.getmembers()
                    if members:
                        # 获取根目录名
                        root_dir = members[0].name.split('/')[0]
                        # 解压到临时目录
                        temp_dir = model_dir / "temp_import"
                        tar.extractall(temp_dir)
                        
                        self.progress_updated.emit(50, "正在移动模型文件...")
                        
                        # 移动到目标目录
                        extracted_dir = temp_dir / root_dir
                        if extracted_dir.exists():
                            # 如果目标目录已存在，先删除
                            if target_dir.exists():
                                shutil.rmtree(target_dir)
                            shutil.move(str(extracted_dir), str(target_dir))
                        
                        # 清理临时目录
                        if temp_dir.exists():
                            shutil.rmtree(temp_dir)
                
                self.progress_updated.emit(100, "模型导入完成")
                self.finished.emit(str(target_dir))
            
            # 如果是目录，检查并复制
            elif Path(self._source_path).is_dir():
                source_dir = Path(self._source_path)
                
                # 检查是否包含必要的模型文件
                encoder_files = list(source_dir.glob("encoder*.onnx"))
                
                if not encoder_files:
                    self.error.emit("所选目录不包含有效的模型文件（缺少 encoder*.onnx）")
                    return
                
                self.progress_updated.emit(0, "正在复制模型文件...")
                
                # 如果目标目录已存在，先删除
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                
                # 复制目录
                shutil.copytree(source_dir, target_dir)
                
                self.progress_updated.emit(100, "模型导入完成")
                self.finished.emit(str(target_dir))
            
            else:
                self.error.emit("请选择 .tar.bz2 文件或包含模型文件的目录")
                
        except Exception as e:
            logger.exception(f"导入模型时发生错误: {e}")
            self.error.emit(str(e))


class RealtimeASRTestWorker(QThread):
    """实时流式转写测试工作线程"""

    result_updated = Signal(str)  # 实时识别结果
    status_updated = Signal(str)  # 状态更新
    error = Signal(str)  # 错误消息
    finished = Signal()  # 测试结束

    def __init__(self, device_id: int | None = None, parent=None) -> None:
        """
        初始化实时流式转写测试工作线程

        Args:
            device_id: 音频设备ID，如果为None则使用默认设备
            parent: 父对象
        """
        super().__init__(parent)
        self._device_id = device_id
        self._sample_rate = 16000
        self._channels = 1
        self._dtype = 'int16'
        self._is_running = False
        self._stop_requested = False

    def stop(self) -> None:
        """请求停止测试"""
        self._stop_requested = True

    def run(self) -> None:
        """执行实时流式转写测试"""
        import numpy as np

        try:
            # 导入sounddevice
            try:
                import sounddevice as sd
            except ImportError:
                self.error.emit("sounddevice 库未安装，无法进行音频设备测试")
                return

            # 检查流式模型是否已加载
            if not is_online_model_loaded():
                self.error.emit("流式语音识别模型未加载，请先加载模型")
                return

            self.status_updated.emit("正在初始化音频设备...")
            self._is_running = True
            self._stop_requested = False

            # 创建识别流（使用 recorder.py 中的函数）
            if not create_online_stream():
                self.error.emit("创建识别流失败")
                return

            self.status_updated.emit("准备开始录音，请说话...")

            # 音频回调函数
            def audio_callback(indata, frames, time_info, status):
                if self._stop_requested:
                    raise sd.CallbackStop

                try:
                    # 将音频数据转换为 int16 格式
                    audio_data = indata[:, 0].astype(np.int16)

                    # 使用 recorder.py 中的函数处理音频数据
                    process_online_stream(audio_data, self._sample_rate)

                    # 获取当前识别结果
                    result = get_online_stream_result()
                    if result:
                        self.result_updated.emit(result)
                except Exception as e:
                    # 捕获音频处理中的异常，避免崩溃
                    logger.warning(f"音频处理异常: {e}")

            try:
                # 开始录音
                with sd.InputStream(
                    device=self._device_id,
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype=self._dtype,
                    callback=audio_callback,
                    blocksize=512
                ):
                    self.status_updated.emit("正在录音... 请说话测试实时识别")

                    # 等待停止信号
                    while not self._stop_requested:
                        self.msleep(100)

                # 等待一小段时间让音频处理完成
                self.msleep(200)

                # 获取最终结果
                try:
                    final_result = get_online_stream_result()
                    if final_result:
                        self.result_updated.emit(f"[最终结果] {final_result}")
                except Exception as e:
                    logger.warning(f"获取最终结果时异常: {e}")

                self.status_updated.emit("测试完成")

            except sd.CallbackStop:
                # 正常停止，获取最终结果
                try:
                    final_result = get_online_stream_result()
                    if final_result:
                        self.result_updated.emit(f"[最终结果] {final_result}")
                except Exception as e:
                    logger.warning(f"获取最终结果时异常: {e}")
                self.status_updated.emit("测试完成")
            except sd.PortAudioError as e:
                logger.exception(f"录音失败: {e}")
                self.error.emit(f"录音失败: {e}")
                return
            except Exception as e:
                logger.exception(f"录音时发生未知错误: {e}")
                self.error.emit(f"录音失败: {e}")
                return
            finally:
                # 销毁识别流
                destroy_online_stream()

        except Exception as e:
            logger.exception(f"实时流式转写测试时发生错误: {e}")
            self.error.emit(str(e))

        finally:
            self._is_running = False
            self.finished.emit()


class AudioDeviceTestWorker(QThread):
    """音频设备测试工作线程"""

    progress_updated = Signal(int, str)  # (progress, status)
    finished = Signal(str)  # result message
    error = Signal(str)  # error message

    def __init__(self, device_id: int | None = None, duration: int = 3, parent=None) -> None:
        """
        初始化音频设备测试工作线程

        Args:
            device_id: 音频设备ID，如果为None则使用默认设备
            duration: 录制时长（秒），默认3秒
            parent: 父对象
        """
        super().__init__(parent)
        self._device_id = device_id
        self._duration = duration
        self._sample_rate = 16000
        self._channels = 1
        self._dtype = 'int16'

    def run(self) -> None:
        """执行音频设备测试"""
        import numpy as np

        try:
            # 导入sounddevice
            try:
                import sounddevice as sd
            except ImportError:
                self.error.emit("sounddevice 库未安装，无法进行音频设备测试")
                return

            # 发送开始进度
            self.progress_updated.emit(5, "正在初始化音频设备...")

            # 检查设备是否可用
            if self._device_id is not None:
                try:
                    devices = sd.query_devices()
                    if self._device_id >= len(devices):
                        self.error.emit(f"设备ID {self._device_id} 不存在")
                        return
                    device_info = devices[self._device_id]
                    if device_info['max_input_channels'] < 1:
                        self.error.emit(f"设备 '{device_info['name']}' 不支持录音")
                        return
                except Exception as e:
                    logger.exception(f"查询设备信息时发生错误: {e}")
                    self.error.emit(f"查询设备信息失败: {e}")
                    return

            # 开始录制
            self.progress_updated.emit(10, f"开始录制 {self._duration} 秒音频...")

            try:
                # 录制音频
                recorded_audio = sd.rec(
                    int(self._duration * self._sample_rate),
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype=self._dtype,
                    device=self._device_id
                )

                # 等待录制完成，同时更新进度
                total_samples = int(self._duration * self._sample_rate)
                samples_per_update = total_samples // 10
                for i in range(10):
                    sd.wait(samples_per_update)
                    progress = 10 + (i + 1) * 5
                    elapsed = (i + 1) * self._duration / 10
                    self.progress_updated.emit(progress, f"正在录制... {elapsed:.1f}/{self._duration}秒")

                # 确保录制完成
                sd.wait()

                self.progress_updated.emit(60, "录制完成，准备播放...")

            except sd.PortAudioError as e:
                logger.exception(f"录音失败: {e}")
                self.error.emit(f"录音失败: {e}")
                return
            except Exception as e:
                logger.exception(f"录音时发生未知错误: {e}")
                self.error.emit(f"录音失败: {e}")
                return

            # 检查录制的音频是否有效
            if recorded_audio is None or len(recorded_audio) == 0:
                self.error.emit("录制的音频为空")
                return

            # 计算音频的音量级别
            audio_max = np.max(np.abs(recorded_audio))
            audio_rms = np.sqrt(np.mean(recorded_audio.astype(np.float64) ** 2))

            self.progress_updated.emit(70, f"音频信息: 最大值={audio_max}, RMS={audio_rms:.2f}")

            # 播放录制的音频
            self.progress_updated.emit(75, "正在播放录制的音频...")

            try:
                # 使用默认输出设备播放
                sd.play(recorded_audio, samplerate=self._sample_rate)

                # 等待播放完成，同时更新进度
                play_samples = len(recorded_audio)
                samples_per_update = play_samples // 5
                for i in range(5):
                    sd.wait(samples_per_update)
                    progress = 75 + (i + 1) * 4
                    elapsed = (i + 1) * self._duration / 5
                    self.progress_updated.emit(progress, f"正在播放... {elapsed:.1f}/{self._duration}秒")

                # 确保播放完成
                sd.wait()

                self.progress_updated.emit(95, "播放完成")

            except sd.PortAudioError as e:
                logger.exception(f"播放失败: {e}")
                self.error.emit(f"播放失败: {e}")
                return
            except Exception as e:
                logger.exception(f"播放时发生未知错误: {e}")
                self.error.emit(f"播放失败: {e}")
                return

            # 测试成功
            device_name = "默认设备"
            if self._device_id is not None:
                try:
                    device_info = sd.query_devices(self._device_id)
                    device_name = device_info['name']
                except Exception:
                    pass

            result_msg = f"音频设备测试成功！\n设备: {device_name}\n录制时长: {self._duration}秒\n音量级别: RMS={audio_rms:.2f}"
            self.progress_updated.emit(100, "测试完成")
            self.finished.emit(result_msg)

        except Exception as e:
            logger.exception(f"音频设备测试时发生错误: {e}")
            self.error.emit(str(e))


def _llm_request_params_text() -> str:
    from llm import get_chat_model
    import config

    m = get_chat_model()
    try:
        body = m.extra_body if isinstance(m.extra_body, dict) else dict(m.extra_body or {})
    except (TypeError, ValueError):
        body = m.extra_body
    body_s = json.dumps(body, ensure_ascii=False, indent=2) if isinstance(body, dict) else repr(body)
    key = m.api_key or ""
    key_disp = "（未设置）" if not key else f"{key[:4]}…{key[-2:]}" if len(key) > 8 else "（已设置）"
    parts = [
        f"model_name: {m.model_name}",
        f"temperature: {m.temperature}",
        f"top_p: {getattr(m, 'top_p', 0.95)}",
        f"frequency_penalty: {getattr(m, 'frequency_penalty', 0.6)}",
        f"enable_thinking: {body.get('enable_thinking', True)}",
        f"base_url: {m.base_url}",
        f"api_key: {key_disp}",
        f"extra_body:\n{body_s}",
        f"SKILL_AGENT_MAX_STEPS（Agent 循环上限）: {config.SKILL_AGENT_MAX_STEPS}",
    ]
    return "\n".join(parts)


class ConfigItemWidget(QWidget):
    """配置组列表项组件 - 完全自己管理状态"""

    selected = Signal(str)  # 信号：被选中查看/编辑，传递配置ID
    activated = Signal(str)  # 信号：被激活，传递配置ID
    
    def __init__(self, config_item: LLMConfigItem, is_active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_id = config_item.id
        self._is_active = is_active
        self._setup_ui(config_item)
        self._update_appearance()

    def _setup_ui(self, config_item: LLMConfigItem) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 使用一个简单的指示器代替 QRadioButton
        self._indicator = QLabel("●")
        self._indicator.setFixedWidth(20)
        self._indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._indicator)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self._name_label = QLabel(config_item.name)
        self._name_label.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        info_layout.addWidget(self._name_label)

        self._model_label = QLabel(config_item.model_name)
        self._model_label.setFont(QFont("Microsoft YaHei", 8))
        self._model_label.setStyleSheet("color: #6b7280;")
        info_layout.addWidget(self._model_label)

        layout.addLayout(info_layout, stretch=1)

        # 让点击整个区域也触发选中
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 安装事件过滤器来处理点击
        self._indicator.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器，处理指示器的点击"""
        if obj == self._indicator and event.type() == event.Type.MouseButtonPress:
            self.activated.emit(self.config_id)
            return True
        return False

    def mousePressEvent(self, event) -> None:
        """点击整个控件时，选中为编辑对象（不激活）"""
        super().mousePressEvent(event)
        self.selected.emit(self.config_id)

    def set_active(self, is_active: bool) -> None:
        """设置激活状态"""
        logger.debug(f"[ConfigItemWidget] set_active called for {self.config_id}, is_active={is_active}")
        self._is_active = is_active
        self._update_appearance()

    def _update_appearance(self) -> None:
        """更新外观显示 - 简单直接"""
        logger.debug(f"[ConfigItemWidget] _update_appearance called for {self.config_id}, is_active={self._is_active}")
        
        # 更新指示器颜色
        if self._is_active:
            self._indicator.setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self._indicator.setStyleSheet("color: #d1d5db;")
        
        # 使用 QPalette 来设置背景色
        palette = self.palette()
        if self._is_active:
            palette.setColor(self.backgroundRole(), QColor("#ecfdf5"))
        else:
            palette.setColor(self.backgroundRole(), QColor(0, 0, 0, 0))  # 透明
        
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.update()


class ConfigEditPanel(QWidget):
    """配置参数编辑面板"""

    config_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_config_id: str | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("配置参数编辑")
        title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        layout.addWidget(title)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(6)

        self._config_name_edit = QLineEdit()
        self._config_name_edit.setPlaceholderText("配置名称（如：主配置、备用配置）")
        self._config_name_edit.setObjectName("configNameEdit")
        form_layout.addWidget(QLabel("配置名称："))
        form_layout.addWidget(self._config_name_edit)

        self._model_name_edit = QLineEdit()
        self._model_name_edit.setPlaceholderText("模型名称（如：qwen3.5-plus、glm-4）")
        form_layout.addWidget(QLabel("模型名称："))
        form_layout.addWidget(self._model_name_edit)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("API Key")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addWidget(QLabel("API Key："))
        form_layout.addWidget(self._api_key_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("API 基础 URL")
        form_layout.addWidget(QLabel("Base URL："))
        form_layout.addWidget(self._base_url_edit)

        temp_layout = QHBoxLayout()
        temp_layout.addWidget(QLabel("温度系数："))
        self._temperature_edit = QLineEdit()
        self._temperature_edit.setPlaceholderText("0.7")
        self._temperature_edit.setFixedWidth(80)
        temp_layout.addWidget(self._temperature_edit)
        temp_hint = QLabel("（0-2，值越高越随机）")
        temp_hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        temp_layout.addWidget(temp_hint)
        temp_layout.addStretch()
        form_layout.addLayout(temp_layout)

        top_p_layout = QHBoxLayout()
        top_p_layout.addWidget(QLabel("Top P："))
        self._top_p_edit = QLineEdit()
        self._top_p_edit.setPlaceholderText("0.95")
        self._top_p_edit.setFixedWidth(80)
        top_p_layout.addWidget(self._top_p_edit)
        top_p_hint = QLabel("（0-1，值越小越聚焦）")
        top_p_hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        top_p_layout.addWidget(top_p_hint)
        top_p_layout.addStretch()
        form_layout.addLayout(top_p_layout)

        freq_layout = QHBoxLayout()
        freq_layout.addWidget(QLabel("频率惩罚："))
        self._frequency_penalty_edit = QLineEdit()
        self._frequency_penalty_edit.setPlaceholderText("0.6")
        self._frequency_penalty_edit.setFixedWidth(80)
        freq_layout.addWidget(self._frequency_penalty_edit)
        freq_hint = QLabel("（值越高越避免重复）")
        freq_hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        freq_layout.addWidget(freq_hint)
        freq_layout.addStretch()
        form_layout.addLayout(freq_layout)

        layout.addLayout(form_layout)

        save_btn = QPushButton("保存参数")
        save_btn.setObjectName("skillAgentSettingsSaveConfigButton")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        layout.addStretch()

    def load_config(self, config_item: LLMConfigItem | None) -> None:
        if config_item is None:
            self._current_config_id = None
            self._config_name_edit.clear()
            self._model_name_edit.clear()
            self._api_key_edit.clear()
            self._base_url_edit.clear()
            self._temperature_edit.clear()
            self._top_p_edit.clear()
            self._frequency_penalty_edit.clear()
            self.setEnabled(False)
            return

        self._current_config_id = config_item.id
        self._config_name_edit.setText(config_item.name)
        self._model_name_edit.setText(config_item.model_name)
        self._api_key_edit.setText(config_item.api_key)
        self._base_url_edit.setText(config_item.base_url)
        self._temperature_edit.setText(str(config_item.temperature))
        self._top_p_edit.setText(str(config_item.top_p))
        self._frequency_penalty_edit.setText(str(config_item.frequency_penalty))
        self.setEnabled(True)

    def _on_save(self) -> None:
        if not self._current_config_id:
            QMessageBox.warning(self, "警告", "请先选择一个配置组")
            return

        config_name = self._config_name_edit.text().strip()
        model_name = self._model_name_edit.text().strip()
        api_key = self._api_key_edit.text().strip()
        base_url = self._base_url_edit.text().strip()

        if not config_name:
            QMessageBox.warning(self, "警告", "请输入配置名称")
            return
        if not model_name:
            QMessageBox.warning(self, "警告", "请输入模型名称")
            return
        if not api_key:
            QMessageBox.warning(self, "警告", "请输入 API Key")
            return
        if not base_url:
            QMessageBox.warning(self, "警告", "请输入 API 基础 URL")
            return

        temperature = 0.7
        try:
            temp_val = float(self._temperature_edit.text().strip())
            if 0 <= temp_val <= 2:
                temperature = temp_val
            else:
                QMessageBox.warning(self, "警告", "温度系数必须在 0 到 2 之间")
                return
        except ValueError:
            QMessageBox.warning(self, "警告", "温度系数必须是数字")
            return

        top_p = 0.95
        try:
            top_p_val = float(self._top_p_edit.text().strip())
            if 0 <= top_p_val <= 1:
                top_p = top_p_val
            else:
                QMessageBox.warning(self, "警告", "Top P 必须在 0 到 1 之间")
                return
        except ValueError:
            QMessageBox.warning(self, "警告", "Top P 必须是数字")
            return

        frequency_penalty = 0.6
        try:
            freq_val = float(self._frequency_penalty_edit.text().strip())
            frequency_penalty = freq_val
        except ValueError:
            QMessageBox.warning(self, "警告", "频率惩罚必须是数字")
            return

        updated_config = LLMConfigItem(
            id=self._current_config_id,
            name=config_name,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            enable_thinking=True,
        )

        if update_config(self._current_config_id, updated_config):
            QMessageBox.information(self, "提示", "配置已保存")
            self.config_saved.emit()
        else:
            QMessageBox.warning(self, "警告", "保存配置失败")


class TaskEditDialog(QDialog):
    """添加/编辑定时任务对话框"""

    def __init__(
        self,
        parent: QWidget | None = None,
        task: ScheduledTask | None = None,
        user_id: str = "default",
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._user_id = user_id
        self._result_task: ScheduledTask | None = None
        self._setup_ui()
        self._apply_style()
        if task:
            self._load_task(task)
        else:
            self._update_datetime_display()
            self._on_execution_type_changed()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        self.setWindowTitle("添加任务" if self._task is None else "编辑任务")
        self.setModal(True)
        self.resize(480, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_label = QLabel("任务标题：")
        layout.addWidget(title_label)
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("请输入任务标题")
        layout.addWidget(self._title_edit)

        content_label = QLabel("任务内容：")
        layout.addWidget(content_label)
        self._content_edit = QTextEdit()
        self._content_edit.setPlaceholderText("请输入任务内容")
        self._content_edit.setMaximumHeight(80)
        layout.addWidget(self._content_edit)

        time_layout = QHBoxLayout()
        time_label = QLabel("触发时间：")
        time_layout.addWidget(time_label)
        self._datetime_edit = QDateTimeEdit()
        self._datetime_edit.setCalendarPopup(True)
        self._datetime_edit.setDateTime(datetime.now())
        self._datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        time_layout.addWidget(self._datetime_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)

        repeat_layout = QHBoxLayout()
        repeat_label = QLabel("重复类型：")
        repeat_layout.addWidget(repeat_label)
        self._repeat_combo = QComboBox()
        self._repeat_combo.addItem("单次", "none")
        self._repeat_combo.addItem("每日", "daily")
        self._repeat_combo.addItem("每周", "weekly")
        self._repeat_combo.addItem("每月", "monthly")
        self._repeat_combo.currentIndexChanged.connect(self._on_repeat_type_changed)
        repeat_layout.addWidget(self._repeat_combo)
        repeat_layout.addStretch()
        layout.addLayout(repeat_layout)

        exec_layout = QHBoxLayout()
        exec_label = QLabel("执行方式：")
        exec_layout.addWidget(exec_label)
        self._execution_combo = QComboBox()
        self._execution_combo.addItem("通知弹窗", "notification")
        self._execution_combo.addItem("智能体会话", "agent_conversation")
        self._execution_combo.currentIndexChanged.connect(self._on_execution_type_changed)
        exec_layout.addWidget(self._execution_combo)
        exec_layout.addStretch()
        layout.addLayout(exec_layout)

        notify_layout = QHBoxLayout()
        notify_label = QLabel("通知方式：")
        notify_layout.addWidget(notify_label)
        self._notify_combo = QComboBox()
        self._notify_combo.addItem("系统通知", "system")
        self._notify_combo.addItem("浮动窗口", "toast")
        notify_layout.addWidget(self._notify_combo)
        notify_layout.addStretch()
        self._notify_group = QWidget()
        self._notify_group.setLayout(notify_layout)
        layout.addWidget(self._notify_group)

        chain_label = QLabel("执行链路（JSON格式，可选）：")
        self._chain_group = QWidget()
        chain_layout = QVBoxLayout(self._chain_group)
        chain_layout.setContentsMargins(0, 0, 0, 0)
        chain_layout.addWidget(chain_label)
        self._chain_edit = QTextEdit()
        self._chain_edit.setPlaceholderText('{\n  "goal": "任务目标",\n  "skills": [],\n  "steps": []\n}')
        self._chain_edit.setMaximumHeight(120)
        chain_layout.addWidget(self._chain_edit)
        layout.addWidget(self._chain_group)

        layout.addStretch()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setText("保存")
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setText("取消")
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_execution_type_changed(self) -> None:
        exec_type = self._execution_combo.currentData()
        if exec_type == "notification":
            self._notify_group.setVisible(True)
            self._chain_group.setVisible(False)
        else:
            self._notify_group.setVisible(False)
            self._chain_group.setVisible(True)

    def _load_task(self, task: ScheduledTask) -> None:
        self._title_edit.setText(task.title)
        self._content_edit.setPlainText(task.content)
        self._datetime_edit.setDateTime(task.trigger_time)
        repeat_idx = self._repeat_combo.findData(task.repeat_type)
        if repeat_idx >= 0:
            self._repeat_combo.setCurrentIndex(repeat_idx)
        
        exec_idx = self._execution_combo.findData(task.execution_type)
        if exec_idx >= 0:
            self._execution_combo.setCurrentIndex(exec_idx)
        
        notify_idx = self._notify_combo.findData(task.notification_type)
        if notify_idx >= 0:
            self._notify_combo.setCurrentIndex(notify_idx)
        
        if task.execution_chain:
            self._chain_edit.setPlainText(task.execution_chain)
        
        self._update_datetime_display()
        self._on_execution_type_changed()

    def _on_repeat_type_changed(self) -> None:
        self._update_datetime_display()

    def _update_datetime_display(self) -> None:
        repeat_type = self._repeat_combo.currentData()
        if repeat_type == "none":
            self._datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
            self._datetime_edit.setCalendarPopup(True)
        else:
            self._datetime_edit.setDisplayFormat("HH:mm")
            self._datetime_edit.setCalendarPopup(False)

    def _on_save(self) -> None:
        title = self._title_edit.text().strip()
        content = self._content_edit.toPlainText().strip()
        trigger_time = self._datetime_edit.dateTime().toPython()
        repeat_type: RepeatType = self._repeat_combo.currentData()
        notification_type: NotificationType = self._notify_combo.currentData()
        execution_type: ExecutionType = self._execution_combo.currentData()
        
        execution_chain = None
        if execution_type == "agent_conversation":
            chain_text = self._chain_edit.toPlainText().strip()
            if chain_text:
                try:
                    import json
                    json.loads(chain_text)
                    execution_chain = chain_text
                except Exception as e:
                    QMessageBox.warning(self, "警告", f"执行链路JSON格式错误: {e}")
                    return

        if not title:
            QMessageBox.warning(self, "警告", "请输入任务标题")
            return

        try:
            if self._task:
                self._result_task = scheduled_tasks.update_task(
                    self._task.task_id,
                    title=title,
                    content=content,
                    trigger_time=trigger_time,
                    repeat_type=repeat_type,
                    notification_type=notification_type,
                    execution_type=execution_type,
                    execution_chain=execution_chain,
                )
            else:
                self._result_task = scheduled_tasks.add_task(
                    user_id=self._user_id,
                    title=title,
                    content=content,
                    trigger_time=trigger_time,
                    repeat_type=repeat_type,
                    notification_type=notification_type,
                    execution_type=execution_type,
                    execution_chain=execution_chain,
                )
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "警告", f"保存任务失败: {e}")

    def get_result(self) -> ScheduledTask | None:
        return self._result_task


class SkillBindingDialog(QDialog):
    """Skill 会话绑定设置对话框"""

    def __init__(
        self,
        parent: QWidget | None,
        skill_id: str,
        skill_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._skill_id = skill_id
        self._skill_name = skill_name or skill_id
        self._result_saved = False
        self._setup_ui()
        self._apply_style()
        self._load_bindings()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"配置 Skill 会话绑定 - {self._skill_name}")
        self.setModal(True)
        self.resize(450, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Skill 信息显示
        info_label = QLabel(f"Skill ID：{self._skill_id}\nSkill 名称：{self._skill_name}")
        info_label.setStyleSheet("font-size: 11pt; font-weight: bold;")
        layout.addWidget(info_label)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # 会话类型选择
        type_label = QLabel("选择该 Skill 在哪些会话类型中默认启用：")
        layout.addWidget(type_label)

        self._agent_conv_cb = QCheckBox("智能体会话 (agent_conversation)")
        self._human_chat_cb = QCheckBox("浮动聊天会话 (human_chat_conversation)")
        self._record_conv_cb = QCheckBox("录音会话 (record_conversation)")

        layout.addWidget(self._agent_conv_cb)
        layout.addWidget(self._human_chat_cb)
        layout.addWidget(self._record_conv_cb)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)

    def _load_bindings(self) -> None:
        from skill_agent_preferences import load_skill_bindings
        
        bindings = load_skill_bindings()
        conv_types = bindings.get(self._skill_id, [])
        
        self._agent_conv_cb.setChecked("agent_conversation" in conv_types)
        self._human_chat_cb.setChecked("human_chat_conversation" in conv_types)
        self._record_conv_cb.setChecked("record_conversation" in conv_types)

    def _on_save(self) -> None:
        from skill_agent_preferences import load_skill_bindings, save_skill_bindings
        
        bindings = load_skill_bindings()
        
        conv_types = []
        if self._agent_conv_cb.isChecked():
            conv_types.append("agent_conversation")
        if self._human_chat_cb.isChecked():
            conv_types.append("human_chat_conversation")
        if self._record_conv_cb.isChecked():
            conv_types.append("record_conversation")
        
        if conv_types:
            bindings[self._skill_id] = conv_types
        elif self._skill_id in bindings:
            del bindings[self._skill_id]
        
        save_skill_bindings(bindings)
        self._result_saved = True
        QMessageBox.information(self, "提示", "配置已保存")
        self.accept()


class SettingsDialog(QDialog):
    """会话设置：多配置组管理、模型信息、Skill 启用/禁用。"""

    def __init__(
        self,
        parent: QWidget | None,
        skill_agent: "SkillAgent",
        *,
        on_config_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("skillAgentSettingsDialog")
        self.setWindowTitle("大模型配置管理")
        self.setModal(True)
        self.resize(900, 800)
        self._skill_agent = skill_agent
        self._on_config_changed = on_config_changed
        self._disabled: set[str] = set(load_disabled_skill_ids())
        self._skill_checks: list[tuple[str, QCheckBox]] = []
        self._config_widgets: dict[str, ConfigItemWidget] = {}
        self._tasks_data: list[ScheduledTask] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._setup_main_content(root)
        self._setup_bottom_buttons(root)

        self._apply_style()
        self._refresh_config_list()
        self._repopulate_skill_rows()
        self._update_status_bar()

    def closeEvent(self, event) -> None:
        """处理关闭事件，检查是否有正在运行的测试"""
        # 检查是否有实时语音识别测试正在运行
        if hasattr(self, '_realtime_asr_test_worker') and self._realtime_asr_test_worker is not None:
            reply = QMessageBox.question(
                self,
                "确认关闭",
                "语音识别测试正在运行，是否停止测试并关闭？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 停止测试
                self._realtime_asr_test_worker.stop()
                self._realtime_asr_test_worker.deleteLater()
                self._realtime_asr_test_worker = None
                event.accept()
            else:
                event.ignore()
                return
        
        # 检查是否有模型导入正在运行
        if hasattr(self, '_realtime_import_worker') and self._realtime_import_worker is not None:
            reply = QMessageBox.question(
                self,
                "确认关闭",
                "模型导入正在进行，关闭可能导致导入中断。是否继续关闭？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self._realtime_import_worker.terminate()
                self._realtime_import_worker.deleteLater()
                self._realtime_import_worker = None
                event.accept()
            else:
                event.ignore()
                return
        
        event.accept()

    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)

    def _setup_main_content(self, layout: QVBoxLayout) -> None:
        # 创建 QTabWidget
        tab_widget = QTabWidget()
        
        # 第一个页签：大模型配置组管理
        config_tab = QWidget()
        config_tab_layout = QVBoxLayout(config_tab)
        config_tab_layout.setContentsMargins(0, 0, 0, 0)
        
        config_splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._create_left_panel()
        config_splitter.addWidget(left_panel)

        right_panel = self._create_right_panel()
        config_splitter.addWidget(right_panel)

        config_splitter.setSizes([280, 620])
        config_tab_layout.addWidget(config_splitter)
        
        # 添加自动故障切换选项
        auto_switch_layout = QHBoxLayout()
        self._auto_switch_check = QCheckBox("启用自动故障切换（当当前配置失败时自动切换到下一组）")
        self._auto_switch_check.setChecked(is_auto_switch_enabled())
        self._auto_switch_check.stateChanged.connect(self._on_auto_switch_changed)
        auto_switch_layout.addWidget(self._auto_switch_check)
        auto_switch_layout.addStretch()
        config_tab_layout.addLayout(auto_switch_layout)
        
        # 添加状态栏
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        config_tab_layout.addWidget(self._status_bar)
        
        tab_widget.addTab(config_tab, "大模型配置组管理")
        
        # 第二个页签：Skill管理
        skills_tab = QWidget()
        skills_tab_layout = QVBoxLayout(skills_tab)
        skills_tab_layout.setContentsMargins(8, 8, 8, 8)
        skills_tab_layout.setSpacing(12)
        
        skills_title = QLabel("Skill 管理")
        skills_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        skills_tab_layout.addWidget(skills_title)
        
        skills_list_group = QGroupBox("已加载 Skill 列表")
        skills_list_layout = QVBoxLayout(skills_list_group)
        
        self._skills_scroll = QScrollArea()
        self._skills_scroll.setWidgetResizable(True)
        self._skills_inner = QWidget()
        self._skills_inner.setObjectName("skillAgentSettingsSkillsInner")
        self._skills_layout = QVBoxLayout(self._skills_inner)
        self._skills_layout.setContentsMargins(8, 8, 8, 8)
        self._skills_layout.setSpacing(6)
        self._skills_scroll.setWidget(self._skills_inner)
        skills_list_layout.addWidget(self._skills_scroll)
        
        skills_tab_layout.addWidget(skills_list_group)
        
        tab_widget.addTab(skills_tab, "Skill管理")

        self._tasks_tab = QWidget()
        tasks_tab_layout = QVBoxLayout(self._tasks_tab)
        tasks_tab_layout.setContentsMargins(8, 8, 8, 8)
        tasks_tab_layout.setSpacing(12)

        tasks_title = QLabel("定时任务管理")
        tasks_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        tasks_tab_layout.addWidget(tasks_title)

        task_list_group = QGroupBox("任务列表")
        task_list_layout = QVBoxLayout(task_list_group)

        filter_layout = QHBoxLayout()
        filter_label = QLabel("状态筛选：")
        filter_label.setFont(QFont("Microsoft YaHei", 9))
        filter_layout.addWidget(filter_label)
        self._task_status_filter = QComboBox()
        self._task_status_filter.setObjectName("skillAgentSettingsTaskFilter")
        self._task_status_filter.addItem("全部", "all")
        self._task_status_filter.addItem("待触发", "pending")
        self._task_status_filter.addItem("已触发", "triggered")
        self._task_status_filter.addItem("已取消", "cancelled")
        self._task_status_filter.currentIndexChanged.connect(self._on_task_filter_changed)
        filter_layout.addWidget(self._task_status_filter)
        filter_layout.addStretch()
        task_list_layout.addLayout(filter_layout)

        self._task_table = QTableWidget()
        self._task_table.setObjectName("skillAgentSettingsTaskTable")
        self._task_table.setColumnCount(8)
        self._task_table.setHorizontalHeaderLabels([
            "标题", "内容", "触发时间", "重复类型", "执行方式", "通知方式", "状态", "操作"
        ])
        self._task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        self._task_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        self._task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._task_table.setAlternatingRowColors(True)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.verticalHeader().setDefaultSectionSize(50)
        self._task_table.itemSelectionChanged.connect(self._update_task_button_states)
        task_list_layout.addWidget(self._task_table)

        task_btn_layout = QHBoxLayout()
        self._add_task_btn = QPushButton("添加任务")
        self._add_task_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._add_task_btn.clicked.connect(self._on_add_task)
        task_btn_layout.addWidget(self._add_task_btn)

        self._edit_task_btn = QPushButton("编辑任务")
        self._edit_task_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._edit_task_btn.clicked.connect(self._on_edit_task)
        self._edit_task_btn.setEnabled(False)
        task_btn_layout.addWidget(self._edit_task_btn)

        self._delete_task_btn = QPushButton("删除任务")
        self._delete_task_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._delete_task_btn.clicked.connect(self._on_delete_task)
        self._delete_task_btn.setEnabled(False)
        task_btn_layout.addWidget(self._delete_task_btn)

        task_btn_layout.addStretch()
        task_list_layout.addLayout(task_btn_layout)

        tasks_tab_layout.addWidget(task_list_group)

        autostart_group = QGroupBox("开机自启动设置")
        autostart_layout = QVBoxLayout(autostart_group)
        autostart_check_layout = QHBoxLayout()
        self._autostart_check = QCheckBox("启用开机自启动")
        self._autostart_check.stateChanged.connect(self._on_autostart_changed)
        autostart_check_layout.addWidget(self._autostart_check)
        autostart_check_layout.addStretch()
        autostart_layout.addLayout(autostart_check_layout)

        self._autostart_status_label = QLabel()
        self._autostart_status_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        autostart_layout.addWidget(self._autostart_status_label)
        tasks_tab_layout.addWidget(autostart_group)

        # 添加定时任务行为设置
        task_behavior_group = QGroupBox("定时任务行为设置")
        task_behavior_layout = QVBoxLayout(task_behavior_group)
        task_behavior_check_layout = QHBoxLayout()
        self._scheduled_task_show_window_check = QCheckBox("定时任务触发智能体会话时自动弹出窗口")
        self._scheduled_task_show_window_check.stateChanged.connect(self._on_scheduled_task_show_window_changed)
        task_behavior_check_layout.addWidget(self._scheduled_task_show_window_check)
        task_behavior_check_layout.addStretch()
        task_behavior_layout.addLayout(task_behavior_check_layout)
        tasks_tab_layout.addWidget(task_behavior_group)

        tab_widget.addTab(self._tasks_tab, "定时任务管理")
        
        asr_tab = QWidget()
        asr_tab_layout = QVBoxLayout(asr_tab)
        asr_tab_layout.setContentsMargins(8, 8, 8, 8)
        asr_tab_layout.setSpacing(12)
        
        asr_title = QLabel("ASR 语音识别配置")
        asr_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        asr_tab_layout.addWidget(asr_title)
        
        # 说明文字
        info_label = QLabel("使用 sherpa-onnx 流式模型进行实时语音识别。\n支持边说边识别，适用于实时转写场景。\n首次加载时会自动下载模型到 PersonalData/model 目录。")
        info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        info_label.setWordWrap(True)
        asr_tab_layout.addWidget(info_label)

        # ===== 音频设备设置 =====
        audio_device_group = QGroupBox("音频设备")
        audio_device_layout = QVBoxLayout(audio_device_group)

        # 说明文字
        audio_device_info = QLabel("选择用于录音的音频输入设备。选择'默认设备'将使用系统默认麦克风。")
        audio_device_info.setStyleSheet("color: #6b7280; font-size: 9pt;")
        audio_device_info.setWordWrap(True)
        audio_device_layout.addWidget(audio_device_info)

        # 设备选择行
        device_select_row = QHBoxLayout()
        device_select_label = QLabel("输入设备：")
        device_select_row.addWidget(device_select_label)

        self._audio_device_combo = QComboBox()
        self._audio_device_combo.setMinimumWidth(300)
        self._audio_device_combo.currentIndexChanged.connect(self._on_audio_device_changed)
        device_select_row.addWidget(self._audio_device_combo, stretch=1)

        # 刷新设备按钮
        self._refresh_devices_btn = QPushButton("刷新设备列表")
        self._refresh_devices_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._refresh_devices_btn.clicked.connect(self._on_refresh_audio_devices)
        device_select_row.addWidget(self._refresh_devices_btn)

        audio_device_layout.addLayout(device_select_row)

        # 设备状态标签
        self._audio_device_status = QLabel()
        self._audio_device_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        audio_device_layout.addWidget(self._audio_device_status)

        # 测试设备按钮行
        test_device_row = QHBoxLayout()
        self._test_device_btn = QPushButton("测试设备")
        self._test_device_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._test_device_btn.clicked.connect(self._on_test_audio_device)
        test_device_row.addWidget(self._test_device_btn)

        # 测试进度条
        self._device_test_progress = QProgressBar()
        self._device_test_progress.setVisible(False)
        self._device_test_progress.setMaximumHeight(16)
        test_device_row.addWidget(self._device_test_progress)

        test_device_row.addStretch()
        audio_device_layout.addLayout(test_device_row)

        # 测试状态标签
        self._device_test_status = QLabel()
        self._device_test_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        self._device_test_status.setWordWrap(True)
        audio_device_layout.addWidget(self._device_test_status)

        asr_tab_layout.addWidget(audio_device_group)

        # 语音识别模型配置
        realtime_group = QGroupBox("语音识别模型")
        realtime_layout = QVBoxLayout(realtime_group)

        realtime_info = QLabel("流式语音识别模型用于实时转写，支持边说边识别。\n选择不同模型可获得不同的识别精度和速度。")
        realtime_info.setStyleSheet("color: #6b7280; font-size: 9pt;")
        realtime_info.setWordWrap(True)
        realtime_layout.addWidget(realtime_info)

        # 本地模型路径选择
        local_path_row = QHBoxLayout()
        local_path_label = QLabel("本地模型路径：")
        local_path_row.addWidget(local_path_label)

        self._local_model_path_edit = QLineEdit()
        self._local_model_path_edit.setPlaceholderText("选择或输入本地模型目录路径...")
        # 从配置中读取保存的路径
        saved_path = getattr(config, 'ASR_LOCAL_MODEL_PATH', '')
        self._local_model_path_edit.setText(saved_path)
        self._local_model_path_edit.textChanged.connect(self._on_local_model_path_changed)
        local_path_row.addWidget(self._local_model_path_edit)

        self._select_local_path_btn = QPushButton("选择路径")
        self._select_local_path_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._select_local_path_btn.clicked.connect(self._on_select_local_model_path)
        local_path_row.addWidget(self._select_local_path_btn)

        realtime_layout.addLayout(local_path_row)

        # 模型选择下拉框
        model_select_row = QHBoxLayout()
        model_select_label = QLabel("选择模型：")
        model_select_row.addWidget(model_select_label)

        self._streaming_model_combo = QComboBox()
        self._streaming_model_combo.currentIndexChanged.connect(self._on_streaming_model_selected)
        model_select_row.addWidget(self._streaming_model_combo)

        # 模型详情标签
        self._model_detail_label = QLabel()
        self._model_detail_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        self._model_detail_label.setWordWrap(True)
        model_select_row.addWidget(self._model_detail_label)
        model_select_row.addStretch()
        realtime_layout.addLayout(model_select_row)

        # 填充模型下拉框（在 _model_detail_label 创建之后）
        self._populate_streaming_models_combo()

        self._realtime_model_status = QLabel()
        self._realtime_model_status.setStyleSheet("color: #374151; font-size: 10pt;")
        realtime_layout.addWidget(self._realtime_model_status)

        self._realtime_load_progress = QProgressBar()
        self._realtime_load_progress.setVisible(False)
        realtime_layout.addWidget(self._realtime_load_progress)

        self._realtime_load_status = QLabel()
        self._realtime_load_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        realtime_layout.addWidget(self._realtime_load_status)

        realtime_btn_row = QHBoxLayout()
        self._download_realtime_btn = QPushButton("下载模型")
        self._download_realtime_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._download_realtime_btn.clicked.connect(self._on_download_realtime_model)
        realtime_btn_row.addWidget(self._download_realtime_btn)

        self._import_realtime_btn = QPushButton("导入本地模型")
        self._import_realtime_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._import_realtime_btn.clicked.connect(self._on_import_realtime_model)
        realtime_btn_row.addWidget(self._import_realtime_btn)

        self._load_realtime_btn = QPushButton("加载模型")
        self._load_realtime_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._load_realtime_btn.clicked.connect(self._on_load_realtime_model)
        realtime_btn_row.addWidget(self._load_realtime_btn)

        self._release_realtime_btn = QPushButton("释放模型")
        self._release_realtime_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._release_realtime_btn.clicked.connect(self._on_release_realtime_model)
        realtime_btn_row.addWidget(self._release_realtime_btn)

        realtime_btn_row.addStretch()
        realtime_layout.addLayout(realtime_btn_row)

        # 模型自动加载选项（勾选时自动保存）
        self._realtime_auto_load_checkbox = QCheckBox("程序启动自动加载语音识别模型")
        self._realtime_auto_load_checkbox.setChecked(getattr(config, 'ASR_REALTIME_AUTO_LOAD', False))
        self._realtime_auto_load_checkbox.stateChanged.connect(self._on_realtime_auto_load_changed)
        realtime_layout.addWidget(self._realtime_auto_load_checkbox)

        # 实时识别开关（勾选时自动保存）
        self._asr_realtime_checkbox = QCheckBox("启用实时语音识别（边说边识别）")
        self._asr_realtime_checkbox.setChecked(getattr(config, 'ASR_REALTIME_ENABLED', True))
        self._asr_realtime_checkbox.stateChanged.connect(self._on_asr_realtime_enabled_changed)
        realtime_layout.addWidget(self._asr_realtime_checkbox)

        asr_tab_layout.addWidget(realtime_group)

        # 实时测试
        test_group = QGroupBox("实时测试")
        test_layout = QVBoxLayout(test_group)

        # 测试按钮行
        test_btn_row = QHBoxLayout()
        self._test_asr_btn = QPushButton("开始实时测试")
        self._test_asr_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._test_asr_btn.clicked.connect(self._on_toggle_realtime_test)
        test_btn_row.addWidget(self._test_asr_btn)
        test_btn_row.addStretch()
        test_layout.addLayout(test_btn_row)

        # 状态标签
        self._asr_test_status = QLabel()
        self._asr_test_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        self._asr_test_status.setWordWrap(True)
        test_layout.addWidget(self._asr_test_status)

        # 结果显示区域
        self._asr_test_result = QTextEdit()
        self._asr_test_result.setReadOnly(True)
        self._asr_test_result.setPlaceholderText("实时识别结果将显示在这里...")
        self._asr_test_result.setMaximumHeight(150)
        test_layout.addWidget(self._asr_test_result)

        # 复制按钮
        copy_btn_row = QHBoxLayout()
        self._copy_asr_result_btn = QPushButton("复制结果")
        self._copy_asr_result_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._copy_asr_result_btn.clicked.connect(self._on_copy_asr_result)
        self._copy_asr_result_btn.setEnabled(False)
        copy_btn_row.addWidget(self._copy_asr_result_btn)
        copy_btn_row.addStretch()
        test_layout.addLayout(copy_btn_row)

        asr_tab_layout.addWidget(test_group)

        asr_tab_layout.addStretch()
        
        tab_widget.addTab(asr_tab, "语音识别配置")
        
        self._asr_tab = asr_tab
        
        # ===== TTS 文本转语音配置标签页 =====
        tts_tab = QWidget()
        tts_tab_layout = QVBoxLayout(tts_tab)
        tts_tab_layout.setContentsMargins(8, 8, 8, 8)
        tts_tab_layout.setSpacing(12)
        
        tts_title = QLabel("TTS 文本转语音配置")
        tts_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        tts_tab_layout.addWidget(tts_title)
        
        # 说明文字
        tts_info_label = QLabel("使用 sherpa-onnx VITS 模型进行本地文本转语音。\n支持自定义导入模型，或使用默认中文模型（首次加载自动下载）。")
        tts_info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        tts_info_label.setWordWrap(True)
        tts_tab_layout.addWidget(tts_info_label)
        
        # 模型路径配置
        tts_model_group = QGroupBox("模型配置")
        tts_model_layout = QVBoxLayout(tts_model_group)
        
        # 模型类型选择
        model_type_row = QHBoxLayout()
        model_type_label = QLabel("模型类型：")
        model_type_row.addWidget(model_type_label)
        self._tts_model_type_combo = QComboBox()
        self._tts_model_type_combo.addItem("中文模型（sherpa-onnx-vits-zh-ll）", "zh")
        self._tts_model_type_combo.addItem("中英文模型（vits-melo-tts-zh_en）", "zh_en")
        current_model_type = getattr(config, 'TTS_MODEL_TYPE', 'zh')
        idx = self._tts_model_type_combo.findData(current_model_type)
        if idx >= 0:
            self._tts_model_type_combo.setCurrentIndex(idx)
        self._tts_model_type_combo.currentIndexChanged.connect(self._on_tts_model_type_changed)
        model_type_row.addWidget(self._tts_model_type_combo)
        model_type_row.addStretch()
        tts_model_layout.addLayout(model_type_row)
        
        # 本地模型选择
        local_model_row = QHBoxLayout()
        local_model_label = QLabel("本地模型：")
        local_model_row.addWidget(local_model_label)
        self._tts_local_model_combo = QComboBox()
        self._tts_local_model_combo.addItem("使用预设模型", "")
        self._populate_tts_local_models_combo()
        self._tts_local_model_combo.currentIndexChanged.connect(self._on_tts_local_model_selected)
        local_model_row.addWidget(self._tts_local_model_combo)
        local_model_row.addStretch()
        tts_model_layout.addLayout(local_model_row)
        
        # 模型类型说明
        model_type_info = QLabel(
            "中文模型：纯中文，5个音色（约50MB）\n"
            "中英文模型：支持中英文混合朗读（约100MB）"
        )
        model_type_info.setStyleSheet("color: #6b7280; font-size: 9pt;")
        tts_model_layout.addWidget(model_type_info)
        
        # 自定义模型路径
        path_row = QHBoxLayout()
        self._tts_model_path_edit = QLineEdit()
        self._tts_model_path_edit.setPlaceholderText("留空则使用自动下载的模型")
        current_tts_path = getattr(config, 'TTS_MODEL_PATH', '')
        self._tts_model_path_edit.setText(current_tts_path)
        path_row.addWidget(self._tts_model_path_edit)
        
        browse_tts_btn = QPushButton("浏览")
        browse_tts_btn.setObjectName("skillAgentSettingsAddConfigButton")
        browse_tts_btn.clicked.connect(self._on_browse_tts_model)
        path_row.addWidget(browse_tts_btn)
        tts_model_layout.addLayout(path_row)
        
        self._tts_model_status = QLabel()
        self._tts_model_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        tts_model_layout.addWidget(self._tts_model_status)
        
        save_tts_path_btn = QPushButton("保存路径")
        save_tts_path_btn.setObjectName("skillAgentSettingsAddConfigButton")
        save_tts_path_btn.clicked.connect(self._on_save_tts_model_path)
        tts_model_layout.addWidget(save_tts_path_btn)
        
        tts_tab_layout.addWidget(tts_model_group)
        
        # 模型加载
        tts_load_group = QGroupBox("模型加载")
        tts_load_layout = QVBoxLayout(tts_load_group)
        
        self._tts_load_progress = QProgressBar()
        self._tts_load_progress.setVisible(False)
        tts_load_layout.addWidget(self._tts_load_progress)
        
        self._tts_load_status = QLabel()
        self._tts_load_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        tts_load_layout.addWidget(self._tts_load_status)
        
        tts_load_btn_row = QHBoxLayout()
        self._load_tts_btn = QPushButton("加载模型")
        self._load_tts_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._load_tts_btn.clicked.connect(self._on_load_tts_model)
        tts_load_btn_row.addWidget(self._load_tts_btn)
        
        self._release_tts_btn = QPushButton("释放模型")
        self._release_tts_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._release_tts_btn.clicked.connect(self._on_release_tts_model)
        tts_load_btn_row.addWidget(self._release_tts_btn)
        
        tts_load_btn_row.addStretch()
        tts_load_layout.addLayout(tts_load_btn_row)
        
        # 自动加载选项（勾选时自动保存）
        self._tts_auto_load_checkbox = QCheckBox("程序启动自动加载语音合成模型")
        self._tts_auto_load_checkbox.setChecked(getattr(config, 'TTS_AUTO_LOAD', False))
        self._tts_auto_load_checkbox.stateChanged.connect(self._on_tts_auto_load_changed)
        tts_load_layout.addWidget(self._tts_auto_load_checkbox)
        
        tts_tab_layout.addWidget(tts_load_group)
        
        # 语音参数配置
        tts_params_group = QGroupBox("语音参数")
        tts_params_layout = QVBoxLayout(tts_params_group)
        
        # 说话人选择
        speaker_row = QHBoxLayout()
        speaker_label = QLabel("音色：")
        speaker_row.addWidget(speaker_label)
        self._tts_speaker_combo = QComboBox()
        self._tts_speaker_combo.addItem("默认", 0)
        speaker_row.addWidget(self._tts_speaker_combo)
        speaker_row.addStretch()
        tts_params_layout.addLayout(speaker_row)
        
        # 语速调节
        speed_row = QHBoxLayout()
        speed_label = QLabel("语速：")
        speed_row.addWidget(speed_label)
        self._tts_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._tts_speed_slider.setMinimum(50)
        self._tts_speed_slider.setMaximum(200)
        self._tts_speed_slider.setValue(100)
        self._tts_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._tts_speed_slider.setTickInterval(25)
        speed_row.addWidget(self._tts_speed_slider)
        self._tts_speed_label = QLabel("1.0")
        self._tts_speed_label.setMinimumWidth(40)
        speed_row.addWidget(self._tts_speed_label)
        self._tts_speed_slider.valueChanged.connect(self._on_tts_speed_changed)
        tts_params_layout.addLayout(speed_row)
        
        # 保存参数按钮
        save_params_btn = QPushButton("保存参数")
        save_params_btn.setObjectName("skillAgentSettingsAddConfigButton")
        save_params_btn.clicked.connect(self._on_save_tts_params)
        tts_params_layout.addWidget(save_params_btn)
        
        tts_tab_layout.addWidget(tts_params_group)
        
        # 测试朗读
        tts_test_group = QGroupBox("测试朗读")
        tts_test_layout = QVBoxLayout(tts_test_group)
        
        test_text_row = QHBoxLayout()
        self._tts_test_text_edit = QLineEdit()
        self._tts_test_text_edit.setPlaceholderText("输入测试文本，如：你好世界")
        self._tts_test_text_edit.setText("你好，这是一个语音合成测试。")
        test_text_row.addWidget(self._tts_test_text_edit)
        tts_test_layout.addLayout(test_text_row)
        
        test_btn_row = QHBoxLayout()
        self._tts_test_btn = QPushButton("开始朗读")
        self._tts_test_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._tts_test_btn.clicked.connect(self._on_test_tts)
        test_btn_row.addWidget(self._tts_test_btn)
        
        self._tts_stop_btn = QPushButton("停止朗读")
        self._tts_stop_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._tts_stop_btn.clicked.connect(self._on_stop_tts)
        self._tts_stop_btn.setEnabled(False)
        test_btn_row.addWidget(self._tts_stop_btn)
        
        test_btn_row.addStretch()
        tts_test_layout.addLayout(test_btn_row)
        
        self._tts_test_status = QLabel()
        self._tts_test_status.setStyleSheet("color: #6b7280; font-size: 9pt;")
        tts_test_layout.addWidget(self._tts_test_status)
        
        tts_tab_layout.addWidget(tts_test_group)
        
        # 自定义模型说明
        custom_model_group = QGroupBox("自定义模型说明")
        custom_model_layout = QVBoxLayout(custom_model_group)
        
        custom_info = QLabel(
            "支持导入自定义 VITS ONNX 模型：\n"
            "1. 模型目录需包含：model.onnx、tokens.txt、lexicon.txt\n"
            "2. 多音色模型需包含：dict/ 目录（jieba 分词词典）\n"
            "3. 可使用自己训练的 VITS 模型（需导出为 ONNX 格式）\n"
            "4. 或下载其他预训练模型：https://github.com/k2-fsa/sherpa-onnx/releases"
        )
        custom_info.setStyleSheet("color: #6b7280; font-size: 9pt;")
        custom_info.setWordWrap(True)
        custom_model_layout.addWidget(custom_info)
        
        tts_tab_layout.addWidget(custom_model_group)
        
        tts_tab_layout.addStretch()
        
        tab_widget.addTab(tts_tab, "语音合成配置")
        
        self._tts_tab = tts_tab

        # ===== 系统提示词配置标签页 =====
        prompt_tab = QWidget()
        prompt_tab_layout = QVBoxLayout(prompt_tab)
        prompt_tab_layout.setContentsMargins(8, 8, 8, 8)
        prompt_tab_layout.setSpacing(12)
        
        prompt_title = QLabel("系统提示词模板配置")
        prompt_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        prompt_tab_layout.addWidget(prompt_title)
        
        # 说明文字
        prompt_info_label = QLabel(
            "配置三种会话类型的系统提示词模板。\n"
            "模板使用占位符（如 {BASE_INFO}）来动态填充内容。"
        )
        prompt_info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        prompt_info_label.setWordWrap(True)
        prompt_tab_layout.addWidget(prompt_info_label)
        
        # 会话类型选择
        type_select_group = QGroupBox("会话类型选择")
        type_select_layout = QHBoxLayout(type_select_group)
        
        type_label = QLabel("当前会话类型：")
        type_select_layout.addWidget(type_label)
        
        self._prompt_type_combo = QComboBox()
        conv_types = get_all_conversation_types_with_display_names()
        for conv_type, display_name in conv_types.items():
            self._prompt_type_combo.addItem(display_name, conv_type)
        self._prompt_type_combo.currentIndexChanged.connect(self._on_prompt_type_changed)
        type_select_layout.addWidget(self._prompt_type_combo)
        type_select_layout.addStretch()
        
        prompt_tab_layout.addWidget(type_select_group)
        
        # 主编辑区域 - 使用分割器
        prompt_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：模板编辑器
        template_edit_group = QGroupBox("模板编辑器")
        template_edit_layout = QVBoxLayout(template_edit_group)
        
        self._template_edit = QTextEdit()
        self._template_edit.setFont(QFont("Consolas", 10))
        self._template_edit.setPlaceholderText("在此编辑模板内容...")
        self._template_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        template_edit_layout.addWidget(self._template_edit)
        
        # 操作按钮
        template_btn_layout = QHBoxLayout()
        
        self._save_template_btn = QPushButton("保存模板")
        self._save_template_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._save_template_btn.clicked.connect(self._on_save_template)
        template_btn_layout.addWidget(self._save_template_btn)
        
        self._reset_template_btn = QPushButton("重置为默认")
        self._reset_template_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._reset_template_btn.clicked.connect(self._on_reset_template)
        template_btn_layout.addWidget(self._reset_template_btn)
        
        self._preview_template_btn = QPushButton("预览效果")
        self._preview_template_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._preview_template_btn.clicked.connect(self._on_preview_template)
        template_btn_layout.addWidget(self._preview_template_btn)
        
        template_btn_layout.addStretch()
        template_edit_layout.addLayout(template_btn_layout)
        
        prompt_splitter.addWidget(template_edit_group)
        
        # 右侧：占位符列表
        placeholder_group = QGroupBox("可用占位符")
        placeholder_layout = QVBoxLayout(placeholder_group)
        
        placeholder_info = QLabel("以下占位符可在模板中使用：")
        placeholder_info.setStyleSheet("color: #6b7280; font-size: 9pt;")
        placeholder_layout.addWidget(placeholder_info)
        
        self._placeholder_table = QTableWidget()
        self._placeholder_table.setColumnCount(2)
        self._placeholder_table.setHorizontalHeaderLabels(["占位符", "说明"])
        self._placeholder_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._placeholder_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._placeholder_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._placeholder_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._placeholder_table.setAlternatingRowColors(True)
        self._placeholder_table.verticalHeader().setVisible(False)
        self._placeholder_table.verticalHeader().setDefaultSectionSize(30)
        placeholder_layout.addWidget(self._placeholder_table)
        
        # 填充占位符列表
        placeholder_descriptions = get_all_placeholder_descriptions()
        self._placeholder_table.setRowCount(len(placeholder_descriptions))
        for row, (placeholder, description) in enumerate(placeholder_descriptions.items()):
            placeholder_item = QTableWidgetItem(f"{{{placeholder}}}")
            placeholder_item.setFont(QFont("Consolas", 9))
            self._placeholder_table.setItem(row, 0, placeholder_item)
            desc_item = QTableWidgetItem(description)
            desc_item.setFont(QFont("Microsoft YaHei", 9))
            self._placeholder_table.setItem(row, 1, desc_item)
        
        prompt_splitter.addWidget(placeholder_group)
        prompt_splitter.setSizes([700, 200])

        # 验证状态显示
        self._template_validation_label = QLabel()
        self._template_validation_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        prompt_tab_layout.addWidget(self._template_validation_label)
        
        # 模板内容变化时验证
        self._template_edit.textChanged.connect(self._on_template_text_changed)

        # 让分割器占据主要空间
        prompt_tab_layout.addWidget(prompt_splitter, stretch=1)

        tab_widget.addTab(prompt_tab, "系统提示词配置")
        
        self._prompt_tab = prompt_tab

        # ===== 用户自定义Skill管理标签页 =====
        user_skill_tab = QWidget()
        user_skill_tab_layout = QVBoxLayout(user_skill_tab)
        user_skill_tab_layout.setContentsMargins(8, 8, 8, 8)
        user_skill_tab_layout.setSpacing(12)
        
        try:
            from ui.settings.skill_management_page import SkillManagementPage
            self._user_skill_page = SkillManagementPage(
                user_skill_tab,
            )
            user_skill_tab_layout.addWidget(self._user_skill_page)
        except ImportError as e:
            logger.warning(f"无法加载用户Skill管理页面: {e}")
            error_label = QLabel(f"用户Skill管理模块加载失败: {e}")
            error_label.setStyleSheet("color: #ef4444;")
            user_skill_tab_layout.addWidget(error_label)
        
        tab_widget.addTab(user_skill_tab, "用户Skill管理")
        
        self._user_skill_tab = user_skill_tab

        self._tab_widget = tab_widget
        layout.addWidget(tab_widget)

        # ===== Live2D 2D Live 引擎配置标签页 =====
        live2d_tab = QWidget()
        live2d_tab_layout = QVBoxLayout(live2d_tab)
        live2d_tab_layout.setContentsMargins(8, 8, 8, 8)
        live2d_tab_layout.setSpacing(12)
        
        live2d_title = QLabel("2D Live 悬浮球配置")
        live2d_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        live2d_tab_layout.addWidget(live2d_title)
        
        # 说明文字
        live2d_info_label = QLabel(
            "配置 Live2D 模型作为悬浮球的视觉表现形式。\n"
            "模型文件应放置在 PersonalData/2DLiveFiles 目录下。\n"
            "支持 Live2D Cubism 3/4 格式（.model3.json）。"
        )
        live2d_info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        live2d_info_label.setWordWrap(True)
        live2d_tab_layout.addWidget(live2d_info_label)
        
        # 启用开关
        live2d_enable_group = QGroupBox("启用设置")
        live2d_enable_layout = QVBoxLayout(live2d_enable_group)
        
        self._live2d_enable_check = QCheckBox("启用 Live2D 悬浮球模式（替代传统纯色按钮）")
        self._live2d_enable_check.stateChanged.connect(self._on_live2d_enable_changed)
        live2d_enable_layout.addWidget(self._live2d_enable_check)
        
        live2d_tab_layout.addWidget(live2d_enable_group)
        
        # 模型选择
        live2d_model_group = QGroupBox("模型选择")
        live2d_model_layout = QVBoxLayout(live2d_model_group)
        
        model_select_row = QHBoxLayout()
        model_select_label = QLabel("选择模型：")
        model_select_row.addWidget(model_select_label)
        
        self._live2d_model_combo = QComboBox()
        self._live2d_model_combo.currentIndexChanged.connect(self._on_live2d_model_changed)
        model_select_row.addWidget(self._live2d_model_combo)
        model_select_row.addStretch()
        live2d_model_layout.addLayout(model_select_row)
        
        # 刷新和加载按钮
        btn_row = QHBoxLayout()
        self._live2d_refresh_btn = QPushButton("刷新模型列表")
        self._live2d_refresh_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._live2d_refresh_btn.clicked.connect(self._refresh_live2d_model_list)
        btn_row.addWidget(self._live2d_refresh_btn)
        
        self._live2d_load_btn = QPushButton("加载模型")
        self._live2d_load_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._live2d_load_btn.clicked.connect(self._on_live2d_load_clicked)
        btn_row.addWidget(self._live2d_load_btn)
        
        btn_row.addStretch()
        live2d_model_layout.addLayout(btn_row)
        
        # 模型信息显示
        self._live2d_model_info_label = QLabel()
        self._live2d_model_info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        self._live2d_model_info_label.setWordWrap(True)
        live2d_model_layout.addWidget(self._live2d_model_info_label)
        
        live2d_tab_layout.addWidget(live2d_model_group)
        
        # 尺寸设置
        live2d_size_group = QGroupBox("悬浮球尺寸")
        live2d_size_layout = QVBoxLayout(live2d_size_group)
        
        width_row = QHBoxLayout()
        width_label = QLabel("宽度（像素）：")
        width_row.addWidget(width_label)
        self._live2d_width_spin = QSpinBox()
        self._live2d_width_spin.setMinimum(50)
        self._live2d_width_spin.setMaximum(500)
        self._live2d_width_spin.setValue(200)
        self._live2d_width_spin.valueChanged.connect(self._on_live2d_size_changed)
        width_row.addWidget(self._live2d_width_spin)
        width_row.addStretch()
        live2d_size_layout.addLayout(width_row)
        
        height_row = QHBoxLayout()
        height_label = QLabel("高度（像素）：")
        height_row.addWidget(height_label)
        self._live2d_height_spin = QSpinBox()
        self._live2d_height_spin.setMinimum(50)
        self._live2d_height_spin.setMaximum(500)
        self._live2d_height_spin.setValue(200)
        self._live2d_height_spin.valueChanged.connect(self._on_live2d_size_changed)
        height_row.addWidget(self._live2d_height_spin)
        height_row.addStretch()
        live2d_size_layout.addLayout(height_row)
        
        live2d_tab_layout.addWidget(live2d_size_group)
        
        # 模型目录说明
        live2d_dir_group = QGroupBox("模型目录说明")
        live2d_dir_layout = QVBoxLayout(live2d_dir_group)
        
        dir_info = QLabel(
            "Live2D 模型应放置在 PersonalData/2DLiveFiles 目录下。\n"
            "每个模型应放在独立的子目录中，目录结构如下：\n\n"
            "PersonalData/2DLiveFiles/\n"
            "├── model_name_1/\n"
            "│   ├── model.model3.json\n"
            "│   ├── model.moc3\n"
            "│   ├── textures/\n"
            "│   │   └── texture_00.png\n"
            "│   └── motions/\n"
            "│       └── idle.motion3.json\n"
            "└── model_name_2/\n"
            "    └── ...\n\n"
            "支持的格式：Live2D Cubism 3/4（.model3.json）"
        )
        dir_info.setStyleSheet("color: #6b7280; font-size: 9pt;")
        dir_info.setWordWrap(True)
        live2d_dir_layout.addWidget(dir_info)
        
        live2d_tab_layout.addWidget(live2d_dir_group)
        
        live2d_tab_layout.addStretch()
        
        tab_widget.addTab(live2d_tab, "2D Live 配置")
        
        self._live2d_tab = live2d_tab

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("配置组列表")
        title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        layout.addWidget(title)

        self._config_list_widget = QWidget()
        self._config_list_layout = QVBoxLayout(self._config_list_widget)
        self._config_list_layout.setContentsMargins(0, 0, 0, 0)
        self._config_list_layout.setSpacing(4)
        self._config_list_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._config_list_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll, stretch=1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        row1 = QHBoxLayout()
        self._add_btn = QPushButton("添加配置组")
        self._add_btn.setObjectName("skillAgentSettingsAddConfigButton")
        self._add_btn.clicked.connect(self._on_add_config)
        row1.addWidget(self._add_btn)

        self._delete_btn = QPushButton("删除配置组")
        self._delete_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
        self._delete_btn.clicked.connect(self._on_delete_config)
        row1.addWidget(self._delete_btn)
        btn_layout.addLayout(row1)

        row3 = QHBoxLayout()
        self._move_up_btn = QPushButton("↑ 上移")
        self._move_up_btn.setObjectName("skillAgentSettingsMoveUpButton")
        self._move_up_btn.clicked.connect(self._on_move_up)
        row3.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("↓ 下移")
        self._move_down_btn.setObjectName("skillAgentSettingsMoveDownButton")
        self._move_down_btn.clicked.connect(self._on_move_down)
        row3.addWidget(self._move_down_btn)
        btn_layout.addLayout(row3)

        layout.addLayout(btn_layout)

        return panel

    def _create_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._config_edit_panel = ConfigEditPanel()
        self._config_edit_panel.config_saved.connect(self._on_config_saved)
        self._config_edit_panel.setEnabled(False)
        layout.addWidget(self._config_edit_panel)

        params_group = QGroupBox("当前 LLM 请求参数（只读）")
        params_layout = QVBoxLayout(params_group)
        self._params_edit = QTextEdit()
        self._params_edit.setReadOnly(True)
        self._params_edit.setFont(QFont("Consolas", 9))
        self._params_edit.setMinimumHeight(100)
        self._params_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        params_layout.addWidget(self._params_edit)
        layout.addWidget(params_group)

        return panel

    def _setup_bottom_buttons(self, layout: QVBoxLayout) -> None:
        btn_layout = QHBoxLayout()

        self._apply_all_btn = QPushButton("应用全部配置")
        self._apply_all_btn.setObjectName("skillAgentSettingsApplyButton")
        self._apply_all_btn.clicked.connect(self._on_apply_all)
        btn_layout.addWidget(self._apply_all_btn)

        self._reset_btn = QPushButton("恢复默认")
        self._reset_btn.setObjectName("skillAgentSettingsResetButton")
        self._reset_btn.clicked.connect(self._on_reset_config)
        btn_layout.addWidget(self._reset_btn)

        btn_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("关闭")
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)

        layout.addLayout(btn_layout)

    def _refresh_config_list(self) -> None:
        logger.debug("[SettingsDialog] _refresh_config_list called")
        # 清空现有配置列表
        while self._config_list_layout.count() > 1:
            item = self._config_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._config_widgets: dict[str, ConfigItemWidget] = {}
        configs = list_configs()
        active_config = get_active_config_item()
        active_id = active_config.id if active_config else None
        logger.debug(f"[SettingsDialog] Active config id from data: {active_id}")

        # 重新创建所有组件，自己管理互斥性
        for config_item in configs:
            is_active = (config_item.id == active_id)
            widget = ConfigItemWidget(config_item, is_active)
            widget.selected.connect(self._on_config_selected)
            widget.activated.connect(self._on_config_activate)
            self._config_list_layout.insertWidget(self._config_list_layout.count() - 1, widget)
            self._config_widgets[config_item.id] = widget
            logger.debug(f"[SettingsDialog] Created widget for {config_item.id}, is_active={is_active}")

        self._selected_config_id: str | None = active_id
        
        if active_id:
            self._load_config_to_editor(active_id)
            
        self._update_button_states()

    def _on_config_selected(self, config_id: str) -> None:
        """配置被选中用于查看/编辑"""
        self._selected_config_id = config_id
        self._load_config_to_editor(config_id)
        self._update_button_states()

    def _on_config_activate(self, config_id: str) -> None:
        """配置被激活"""
        logger.debug(f"[SettingsDialog] _on_config_activate called for {config_id}")
        if set_active_config(config_id):
            logger.debug(f"[SettingsDialog] set_active_config succeeded for {config_id}")
            self._selected_config_id = config_id
            
            # 完全自己管理互斥性：遍历所有配置项，设置正确的激活状态
            for cid, widget in self._config_widgets.items():
                is_active = (cid == config_id)
                logger.debug(f"[SettingsDialog] Setting {cid} active={is_active}")
                widget.set_active(is_active)
            
            self._load_config_to_editor(config_id)
            self._update_status_bar()
            self._refresh_params()
            if self._on_config_changed:
                self._on_config_changed()

    def _load_config_to_editor(self, config_id: str) -> None:
        configs = list_configs()
        for config_item in configs:
            if config_item.id == config_id:
                self._config_edit_panel.load_config(config_item)
                return
        self._config_edit_panel.load_config(None)

    def _update_button_states(self) -> None:
        configs = list_configs()
        has_selection = self._selected_config_id is not None
        can_delete = len(configs) > 1 and has_selection

        self._delete_btn.setEnabled(can_delete)

        if has_selection:
            config_ids = [c.id for c in configs]
            idx = config_ids.index(self._selected_config_id) if self._selected_config_id in config_ids else -1
            self._move_up_btn.setEnabled(idx > 0)
            self._move_down_btn.setEnabled(idx >= 0 and idx < len(config_ids) - 1)
        else:
            self._move_up_btn.setEnabled(False)
            self._move_down_btn.setEnabled(False)

    def _on_add_config(self) -> None:
        active_config = get_active_config_item()
        if active_config:
            new_config = LLMConfigItem(
                id=generate_config_id(),
                name="新配置",
                model_name=active_config.model_name,
                api_key=active_config.api_key,
                base_url=active_config.base_url,
                temperature=active_config.temperature,
                top_p=active_config.top_p,
                frequency_penalty=active_config.frequency_penalty,
                enable_thinking=active_config.enable_thinking,
            )
        else:
            current = get_current_config()
            new_config = LLMConfigItem.from_llm_config(current, "新配置")

        add_config(new_config)
        self._refresh_config_list()
        self._selected_config_id = new_config.id
        self._load_config_to_editor(new_config.id)
        self._update_status_bar()
        QMessageBox.information(self, "提示", f"已添加配置组「{new_config.name}」，请在右侧编辑参数")

    def _on_delete_config(self) -> None:
        if not self._selected_config_id:
            return

        configs = list_configs()
        if len(configs) <= 1:
            QMessageBox.warning(self, "警告", "至少需要保留一个配置组")
            return

        config_to_delete = None
        for c in configs:
            if c.id == self._selected_config_id:
                config_to_delete = c
                break

        if not config_to_delete:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除配置组「{config_to_delete.name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            active_config = get_active_config_item()
            was_active = active_config and active_config.id == self._selected_config_id

            if delete_config(self._selected_config_id):
                if was_active:
                    new_active = get_active_config_item()
                    if new_active:
                        self._selected_config_id = new_active.id
                else:
                    self._selected_config_id = None

                self._refresh_config_list()
                self._update_status_bar()
                if self._selected_config_id:
                    self._load_config_to_editor(self._selected_config_id)
                else:
                    self._config_edit_panel.load_config(None)
                QMessageBox.information(self, "提示", "配置组已删除")

    def _on_move_up(self) -> None:
        if self._selected_config_id and move_config_up(self._selected_config_id):
            self._refresh_config_list()
            self._update_status_bar()

    def _on_move_down(self) -> None:
        if self._selected_config_id and move_config_down(self._selected_config_id):
            self._refresh_config_list()
            self._update_status_bar()

    def _on_auto_switch_changed(self, state: int) -> None:
        multi_config = get_current_multi_config()
        multi_config.auto_switch_on_failure = state == Qt.CheckState.Checked.value
        set_multi_config(multi_config)

    def _on_config_saved(self) -> None:
        self._refresh_config_list()
        self._update_status_bar()
        if self._on_config_changed:
            self._on_config_changed()

    def _on_apply_all(self) -> None:
        self._refresh_params()
        QMessageBox.information(self, "提示", "配置已应用")
        if self._on_config_changed:
            self._on_config_changed()

    def _on_reset_config(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要恢复默认配置吗？这将使用 .env 文件中的设置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            reset_to_default()
            self._refresh_config_list()
            self._update_status_bar()
            self._refresh_params()
            self._auto_switch_check.setChecked(is_auto_switch_enabled())
            QMessageBox.information(self, "提示", "已恢复默认配置")
            if self._on_config_changed:
                self._on_config_changed()

    def _update_status_bar(self) -> None:
        active_config = get_active_config_item()
        if active_config:
            status_text = f"当前激活：「{active_config.name}」({active_config.model_name})"
        else:
            status_text = "无激活配置"

        switch_events = get_switch_events()
        if switch_events:
            last_event = switch_events[-1]
            status_text += f" | 最近切换: {last_event.get('reason', '未知')}"

        self._status_bar.showMessage(status_text)

    def _refresh_params(self) -> None:
        self._params_edit.setPlainText(_llm_request_params_text())

    def _repopulate_skill_rows(self) -> None:
        self._skill_checks.clear()
        self._skills_inner = QWidget()
        self._skills_inner.setObjectName("skillAgentSettingsSkillsInner")
        self._skills_layout = QVBoxLayout(self._skills_inner)
        self._skills_layout.setContentsMargins(8, 8, 8, 8)
        self._skills_layout.setSpacing(6)
        self._skills_scroll.setWidget(self._skills_inner)

        skills = sorted(
            self._skill_agent.registry.list_skills(),
            key=lambda s: (s.skill_id or "").lower(),
        )
        for s in skills:
            sid = (s.skill_id or "").strip()
            if not sid:
                continue
            cb = QCheckBox("启用")
            cb.setChecked(sid not in self._disabled)
            cb.stateChanged.connect(lambda _st, _sid=sid, _cb=cb: self._on_skill_toggled(_sid, _cb))
            row = QHBoxLayout()
            row.addWidget(cb)
            
            skill_type = getattr(s, 'skill_type', 'user')
            type_indicator = ""
            if skill_type == "builtin":
                type_indicator = " [内置]"
            
            name_lab = QLabel(f"{sid} · {s.name or ''}{type_indicator}")
            name_lab.setWordWrap(True)
            row.addWidget(name_lab, stretch=1)
            
            edit_btn = QPushButton("编辑")
            edit_btn.setObjectName("skillAgentSettingsAddConfigButton")
            edit_btn.clicked.connect(lambda _, _sid=sid, _s=s: self._on_edit_skill(_sid, _s))
            row.addWidget(edit_btn)
            
            if skill_type != "builtin":
                delete_btn = QPushButton("删除")
                delete_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
                delete_btn.clicked.connect(lambda _, _sid=sid, _s=s: self._on_delete_skill(_sid, _s))
                row.addWidget(delete_btn)
            
            self._skills_layout.addLayout(row)
            self._skill_checks.append((sid, cb))
        self._skills_layout.addStretch(1)

    def _on_delete_skill(self, skill_id: str, skill: Any) -> None:
        skill_type = getattr(skill, 'skill_type', 'user')
        if skill_type == "builtin":
            QMessageBox.warning(self, "警告", "系统内置 Skill 不可移除")
            return
        
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 Skill「{skill_id}」吗？\n\n这将删除该 Skill 的文件夹及其所有内容。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                success = self._skill_agent.registry.delete_skill(skill_id)
                if success:
                    self._disabled.discard(skill_id)
                    save_disabled_skill_ids(self._disabled)
                    self._repopulate_skill_rows()
                    QMessageBox.information(self, "提示", f"Skill「{skill_id}」已删除")
                else:
                    QMessageBox.warning(self, "警告", f"删除 Skill「{skill_id}」失败")
            except Exception as e:
                QMessageBox.warning(self, "警告", f"删除 Skill 时发生错误: {e}")

    def _on_edit_skill(self, skill_id: str, skill: Any) -> None:
        """打开 Skill 会话绑定设置对话框"""
        skill_name = getattr(skill, "name", skill_id)
        dialog = SkillBindingDialog(self, skill_id, skill_name)
        dialog.exec()

    def _on_skill_toggled(self, skill_id: str, cb: QCheckBox) -> None:
        if cb.isChecked():
            self._disabled.discard(skill_id)
        else:
            self._disabled.add(skill_id)
        save_disabled_skill_ids(self._disabled)

    def _refresh_task_list(self) -> None:
        filter_data = self._task_status_filter.currentData()
        status: TaskStatus | None = None if filter_data == "all" else filter_data
        tasks = scheduled_tasks.list_tasks(status=status)
        self._task_table.setRowCount(len(tasks))
        self._tasks_data: list[ScheduledTask] = tasks

        repeat_map = {"none": "单次", "daily": "每日", "weekly": "每周", "monthly": "每月"}
        notify_map = {"system": "系统通知", "toast": "浮动窗口"}
        exec_map = {"notification": "通知弹窗", "agent_conversation": "智能体会话"}
        status_map = {"pending": "待触发", "triggered": "已触发", "cancelled": "已取消"}

        for row, task in enumerate(tasks):
            self._task_table.setItem(row, 0, QTableWidgetItem(task.title))
            content_item = QTableWidgetItem(task.content[:50] + "..." if len(task.content) > 50 else task.content)
            self._task_table.setItem(row, 1, content_item)
            if task.repeat_type == "none":
                time_str = task.trigger_time.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = task.trigger_time.strftime("%H:%M")
            self._task_table.setItem(row, 2, QTableWidgetItem(time_str))
            self._task_table.setItem(row, 3, QTableWidgetItem(repeat_map.get(task.repeat_type, task.repeat_type)))
            self._task_table.setItem(row, 4, QTableWidgetItem(exec_map.get(task.execution_type, task.execution_type)))
            self._task_table.setItem(row, 5, QTableWidgetItem(notify_map.get(task.notification_type, task.notification_type)))
            self._task_table.setItem(row, 6, QTableWidgetItem(status_map.get(task.status, task.status)))

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 4, 4, 4)
            action_layout.setSpacing(10)

            edit_btn = QPushButton("编辑")
            edit_btn.setObjectName("skillAgentSettingsAddConfigButton")
            edit_btn.setMinimumWidth(70)
            edit_btn.setMinimumHeight(32)
            edit_btn.clicked.connect(lambda _, t=task: self._edit_task_direct(t))
            action_layout.addWidget(edit_btn)

            cancel_btn = QPushButton("取消")
            cancel_btn.setObjectName("skillAgentSettingsDeleteConfigButton")
            cancel_btn.setMinimumWidth(70)
            cancel_btn.setMinimumHeight(32)
            cancel_btn.clicked.connect(lambda _, t=task: self._cancel_task_direct(t))
            if task.status != "pending":
                cancel_btn.setEnabled(False)
            action_layout.addWidget(cancel_btn)

            self._task_table.setCellWidget(row, 7, action_widget)

        self._task_table.resizeColumnsToContents()
        self._update_task_button_states()

    def _on_task_filter_changed(self) -> None:
        self._refresh_task_list()

    def _update_task_button_states(self) -> None:
        selected_rows = self._task_table.selectedItems()
        has_selection = len(selected_rows) > 0
        self._edit_task_btn.setEnabled(has_selection)
        self._delete_task_btn.setEnabled(has_selection)

    def _on_add_task(self) -> None:
        dialog = TaskEditDialog(self, user_id="default")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_task_list()
            QMessageBox.information(self, "提示", "任务已添加")

    def _on_edit_task(self) -> None:
        selected_rows = self._task_table.selectedItems()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row < len(self._tasks_data):
            self._edit_task_direct(self._tasks_data[row])

    def _edit_task_direct(self, task: ScheduledTask) -> None:
        dialog = TaskEditDialog(self, task=task, user_id="default")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_task_list()
            QMessageBox.information(self, "提示", "任务已更新")

    def _on_delete_task(self) -> None:
        selected_rows = self._task_table.selectedItems()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row >= len(self._tasks_data):
            return
        task = self._tasks_data[row]
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除任务「{task.title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if scheduled_tasks.delete_task(task.task_id):
                self._refresh_task_list()
                QMessageBox.information(self, "提示", "任务已删除")

    def _cancel_task_direct(self, task: ScheduledTask) -> None:
        if task.status != "pending":
            return
        reply = QMessageBox.question(
            self,
            "确认取消",
            f"确定要取消任务「{task.title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            scheduled_tasks.update_task_status(task.task_id, "cancelled")
            self._refresh_task_list()
            QMessageBox.information(self, "提示", "任务已取消")

    def _on_autostart_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        if enabled:
            success = autostart.enable_autostart()
            if success:
                QMessageBox.information(self, "提示", "开机自启动已启用")
            else:
                QMessageBox.warning(self, "警告", "启用开机自启动失败")
                self._autostart_check.setChecked(False)
        else:
            success = autostart.disable_autostart()
            if success:
                QMessageBox.information(self, "提示", "开机自启动已禁用")
            else:
                QMessageBox.warning(self, "警告", "禁用开机自启动失败")
                self._autostart_check.setChecked(True)
        self._update_autostart_status()

    def _update_autostart_status(self) -> None:
        status = autostart.get_autostart_status()
        # 阻止信号触发，避免每次打开设置页面都弹出提示
        self._autostart_check.blockSignals(True)
        if status["enabled"]:
            self._autostart_check.setChecked(True)
            self._autostart_status_label.setText("状态：已启用开机自启动")
        else:
            self._autostart_check.setChecked(False)
            self._autostart_status_label.setText("状态：未启用开机自启动")
        self._autostart_check.blockSignals(False)

    def _on_scheduled_task_show_window_changed(self, state: int) -> None:
        """处理定时任务弹出窗口选项变更"""
        enabled = state == Qt.CheckState.Checked.value
        try:
            success = config.set_config("SCHEDULED_TASK_SHOW_WINDOW", "true" if enabled else "false")
            if success:
                # 更新内存中的配置值
                config.SCHEDULED_TASK_SHOW_WINDOW = enabled
            else:
                QMessageBox.warning(self, "警告", "保存设置失败")
                # 恢复原值
                self._scheduled_task_show_window_check.blockSignals(True)
                self._scheduled_task_show_window_check.setChecked(not enabled)
                self._scheduled_task_show_window_check.blockSignals(False)
        except Exception as e:
            logger.exception(f"保存定时任务设置失败: {e}")
            QMessageBox.warning(self, "警告", f"保存设置失败: {e}")

    def _update_scheduled_task_show_window_status(self) -> None:
        """更新定时任务弹出窗口选项的状态"""
        try:
            # 使用 config 模块的函数重新读取配置值
            _stsw = config.get_config("SCHEDULED_TASK_SHOW_WINDOW")
            current_value = config._env_bool(_stsw, False)
            self._scheduled_task_show_window_check.setChecked(current_value)
        except Exception as e:
            logger.exception(f"读取定时任务设置失败: {e}")

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._skill_agent.reload_skills()
        self._disabled = set(load_disabled_skill_ids())
        self._repopulate_skill_rows()
        self._refresh_config_list()
        self._refresh_params()
        self._update_status_bar()
        self._auto_switch_check.setChecked(is_auto_switch_enabled())
        self._refresh_task_list()
        self._update_autostart_status()
        self._update_scheduled_task_show_window_status()
        self._refresh_asr_model_status()
        self._refresh_tts_model_status()
        self._refresh_prompt_template_status()
        self._refresh_live2d_settings()
        # 刷新用户Skill管理页面
        if hasattr(self, '_user_skill_page'):
            self._user_skill_page.refresh()
    
    def _refresh_asr_model_status(self) -> None:
        """刷新 ASR 模型状态"""
        # 刷新实时识别开关状态
        realtime_enabled = getattr(config, 'ASR_REALTIME_ENABLED', True)
        self._asr_realtime_checkbox.blockSignals(True)
        self._asr_realtime_checkbox.setChecked(realtime_enabled)
        self._asr_realtime_checkbox.blockSignals(False)
        
        # 刷新流式模型状态
        self._refresh_realtime_model_status()
        
        # 刷新音频设备列表
        self._refresh_audio_devices_list()
    
    def _refresh_realtime_model_status(self) -> None:
        """刷新语音识别模型状态"""
        is_loaded = is_online_model_loaded()
        model_path = get_online_model_path()
        device = get_online_device()
        try:
            gpu_available = check_gpu_available()
        except Exception as e:
            logger.warning(f"检测 GPU 可用性失败，默认使用 CPU: {e}")
            gpu_available = False
        
        # 优先检查本地模型路径
        local_path = self._local_model_path_edit.text()
        if local_path and Path(local_path).exists():
            # 检查本地路径是否包含有效的模型文件
            encoder_files = list(Path(local_path).glob("encoder*.onnx"))
            if encoder_files:
                model_downloaded = True
                model_dir_display = local_path
            else:
                model_downloaded = False
                model_dir_display = local_path
        else:
            # 获取当前选中的模型
            model_key = self._get_selected_model_key()
            
            # 处理自定义模型
            if model_key.startswith("custom:"):
                model_name = model_key[7:]  # 去掉 "custom:" 前缀
            else:
                models = get_streaming_models_list()
                model_config = models.get(model_key)
                model_name = model_config["name"] if model_config else DEFAULT_ONLINE_MODEL_NAME
            
            # 检查模型是否已下载
            model_dir = get_asr_model_dir() / model_name
            model_downloaded = model_dir.exists()
            model_dir_display = str(model_dir)
        
        gpu_status = "GPU 可用" if gpu_available else "GPU 不可用"
        
        if is_loaded:
            device_display = device.upper() if device else "CPU"
            self._realtime_model_status.setText(f"状态：模型已加载 | 运行设备：{device_display} | {gpu_status}")
            self._download_realtime_btn.setEnabled(False)
            self._load_realtime_btn.setEnabled(False)
            self._release_realtime_btn.setEnabled(True)
        elif model_downloaded:
            self._realtime_model_status.setText(f"状态：模型已下载，未加载 | {gpu_status}")
            # 本地路径或自定义模型不能下载
            self._download_realtime_btn.setEnabled(False)
            self._load_realtime_btn.setEnabled(True)
            self._release_realtime_btn.setEnabled(False)
        else:
            self._realtime_model_status.setText(f"状态：模型未下载 | {gpu_status}")
            # 本地路径不存在时，不能下载
            if local_path:
                self._download_realtime_btn.setEnabled(False)
            else:
                # 获取当前选中的模型
                model_key = self._get_selected_model_key()
                # 自定义模型不能下载
                if model_key.startswith("custom:"):
                    self._download_realtime_btn.setEnabled(False)
                else:
                    self._download_realtime_btn.setEnabled(True)
            self._load_realtime_btn.setEnabled(False)
            self._release_realtime_btn.setEnabled(False)
        
        # 刷新模型自动加载 checkbox 状态
        realtime_auto_load = getattr(config, 'ASR_REALTIME_AUTO_LOAD', False)
        self._realtime_auto_load_checkbox.blockSignals(True)
        self._realtime_auto_load_checkbox.setChecked(realtime_auto_load)
        self._realtime_auto_load_checkbox.blockSignals(False)
    
    def _populate_streaming_models_combo(self) -> None:
        """填充流式模型下拉框"""
        models = get_streaming_models_list()
        self._streaming_model_combo.blockSignals(True)
        self._streaming_model_combo.clear()
        
        # 添加预设模型
        for model_key, model_config in models.items():
            display_name = model_config["display_name"]
            self._streaming_model_combo.addItem(display_name, model_key)
        
        # 扫描 ASR 模型目录，添加本地模型
        asr_model_dir = get_asr_model_dir()
        if asr_model_dir.exists():
            for subdir in asr_model_dir.iterdir():
                if subdir.is_dir():
                    # 检查是否包含模型文件
                    encoder_files = list(subdir.glob("encoder*.onnx"))
                    if encoder_files:
                        # 检查是否已在预设列表中
                        subdir_name = subdir.name
                        is_predefined = False
                        for model_key, model_config in models.items():
                            if model_config["name"] == subdir_name:
                                is_predefined = True
                                break
                        
                        if not is_predefined:
                            # 添加本地模型
                            custom_key = f"custom:{subdir_name}"
                            self._streaming_model_combo.addItem(f"[本地] {subdir_name}", custom_key)
        
        # 设置默认选中的模型
        default_key = get_default_model_key()
        for i in range(self._streaming_model_combo.count()):
            if self._streaming_model_combo.itemData(i) == default_key:
                self._streaming_model_combo.setCurrentIndex(i)
                break
        
        self._streaming_model_combo.blockSignals(False)
        
        # 更新模型详情
        self._update_model_detail_label()
    
    def _on_streaming_model_selected(self, index: int) -> None:
        """模型选择变化时的处理"""
        self._update_model_detail_label()
        self._refresh_realtime_model_status()
    
    def _update_model_detail_label(self) -> None:
        """更新模型详情标签"""
        models = get_streaming_models_list()
        current_index = self._streaming_model_combo.currentIndex()
        if current_index >= 0:
            model_key = self._streaming_model_combo.itemData(current_index)
            
            # 处理自定义模型
            if model_key.startswith("custom:"):
                model_name = model_key[7:]  # 去掉 "custom:" 前缀
                self._model_detail_label.setText(f"[本地导入] {model_name}")
            else:
                model_config = models.get(model_key)
                if model_config:
                    size_mb = model_config["size_mb"]
                    languages = ", ".join(model_config["languages"])
                    self._model_detail_label.setText(f"大小: {size_mb}MB | 语言: {languages}")
    
    def _get_selected_model_key(self) -> str:
        """获取当前选中的模型键名"""
        current_index = self._streaming_model_combo.currentIndex()
        if current_index >= 0:
            return self._streaming_model_combo.itemData(current_index)
        return get_default_model_key()
    
    def _on_download_realtime_model(self) -> None:
        """下载语音识别模型（异步）"""
        model_key = self._get_selected_model_key()
        models = get_streaming_models_list()
        model_config = models.get(model_key)
        display_name = model_config["display_name"] if model_config else "模型"
        
        self._download_realtime_btn.setEnabled(False)
        self._load_realtime_btn.setEnabled(False)
        self._realtime_load_progress.setVisible(True)
        self._realtime_load_progress.setValue(0)
        self._realtime_load_status.setText(f"正在准备下载 {display_name}...")
        
        # 创建下载工作线程
        self._realtime_download_worker = RealtimeModelDownloadWorker(model_key, self)
        
        # 连接信号
        self._realtime_download_worker.progress_updated.connect(
            lambda progress, status: (
                self._realtime_load_progress.setValue(progress),
                self._realtime_load_status.setText(status)
            )
        )
        self._realtime_download_worker.finished.connect(self._on_realtime_download_finished)
        self._realtime_download_worker.error.connect(self._on_realtime_download_error)
        
        # 启动下载
        self._realtime_download_worker.start()
    
    def _on_realtime_download_finished(self, downloaded_path: str) -> None:
        """语音识别模型下载完成"""
        self._realtime_load_progress.setVisible(False)
        self._realtime_load_status.setText("模型下载完成")
        QMessageBox.information(self, "提示", f"语音识别模型下载成功\n路径: {downloaded_path}")
        self._refresh_realtime_model_status()
        
        # 清理工作线程
        if hasattr(self, '_realtime_download_worker'):
            self._realtime_download_worker.deleteLater()
            del self._realtime_download_worker
    
    def _on_realtime_download_error(self, error_msg: str) -> None:
        """语音识别模型下载失败"""
        self._realtime_load_progress.setVisible(False)
        self._realtime_load_status.setText(f"下载失败: {error_msg}")
        QMessageBox.warning(self, "警告", f"语音识别模型下载失败: {error_msg}")
        self._refresh_realtime_model_status()
        
        # 清理工作线程
        if hasattr(self, '_realtime_download_worker'):
            self._realtime_download_worker.deleteLater()
            del self._realtime_download_worker
    
    def _on_realtime_auto_load_changed(self, state: int) -> None:
        """语音识别模型自动加载勾选状态改变时自动保存"""
        from PySide6.QtCore import Qt
        auto_load = state == Qt.CheckState.Checked.value
        config.set_config("ASR_REALTIME_AUTO_LOAD", str(auto_load).lower())
        config.ASR_REALTIME_AUTO_LOAD = auto_load
    
    def _on_select_local_model_path(self) -> None:
        """选择本地模型路径"""
        from PySide6.QtWidgets import QFileDialog
        
        # 打开目录选择对话框
        dialog = QFileDialog(self)
        dialog.setWindowTitle("选择本地模型目录")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        
        # 如果已有路径，设置为起始目录
        current_path = self._local_model_path_edit.text()
        if current_path and Path(current_path).exists():
            dialog.setDirectory(current_path)
        
        if dialog.exec():
            selected_dirs = dialog.selectedFiles()
            if selected_dirs:
                selected_path = selected_dirs[0]
                self._local_model_path_edit.setText(selected_path)
    
    def _on_local_model_path_changed(self, path: str) -> None:
        """本地模型路径改变时保存到配置"""
        # 保存到配置
        config.set_config("ASR_LOCAL_MODEL_PATH", path)
        config.ASR_LOCAL_MODEL_PATH = path
        
        # 如果路径有效，更新模型下拉框选中状态
        if path and Path(path).exists():
            # 检查路径是否包含有效的模型文件
            encoder_files = list(Path(path).glob("encoder*.onnx"))
            if encoder_files:
                # 在下拉框中查找对应的自定义模型项
                model_name = Path(path).name
                custom_key = f"custom:{model_name}"
                found = False
                for i in range(self._streaming_model_combo.count()):
                    if self._streaming_model_combo.itemData(i) == custom_key:
                        self._streaming_model_combo.setCurrentIndex(i)
                        found = True
                        break
                
                # 如果下拉框中没有这个模型，刷新下拉框
                if not found:
                    self._populate_streaming_models_combo()
                    # 再次查找
                    for i in range(self._streaming_model_combo.count()):
                        if self._streaming_model_combo.itemData(i) == custom_key:
                            self._streaming_model_combo.setCurrentIndex(i)
                            break
    
    def _on_load_realtime_model(self) -> None:
        """加载语音识别模型"""
        # 优先使用本地模型路径
        local_path = self._local_model_path_edit.text()
        if local_path and Path(local_path).exists():
            # 检查路径是否包含有效的模型文件
            encoder_files = list(Path(local_path).glob("encoder*.onnx"))
            if encoder_files:
                model_path = local_path
            else:
                QMessageBox.warning(self, "警告", f"本地路径不包含有效的模型文件：{local_path}")
                return
        else:
            # 使用下拉框选择的模型
            model_key = self._get_selected_model_key()
            
            # 处理自定义模型
            if model_key.startswith("custom:"):
                model_name = model_key[7:]  # 去掉 "custom:" 前缀
            else:
                models = get_streaming_models_list()
                model_config = models.get(model_key)
                model_name = model_config["name"] if model_config else DEFAULT_ONLINE_MODEL_NAME

            model_path = str(get_asr_model_dir() / model_name)
        
        self._download_realtime_btn.setEnabled(False)
        self._load_realtime_btn.setEnabled(False)
        self._realtime_load_progress.setVisible(True)
        self._realtime_load_progress.setValue(0)
        self._realtime_load_status.setText("正在加载语音识别模型...")
        
        try:
            def load_callback(progress: int, status: str):
                self._realtime_load_progress.setValue(progress)
                self._realtime_load_status.setText(status)
            
            success = load_online_model(model_path=model_path, callback=load_callback)
            
            self._realtime_load_progress.setVisible(False)
            
            if success:
                self._realtime_load_status.setText("模型加载完成")
                QMessageBox.information(self, "提示", "语音识别模型加载成功")
            else:
                self._realtime_load_status.setText("加载失败")
                QMessageBox.warning(self, "警告", "语音识别模型加载失败")
            
            self._refresh_realtime_model_status()
        except Exception as e:
            logger.exception(f"加载语音识别模型时发生异常: {e}")
            self._realtime_load_progress.setVisible(False)
            self._realtime_load_status.setText(f"加载失败: {str(e)}")
            QMessageBox.warning(self, "警告", f"加载语音识别模型时发生错误: {str(e)}")
            self._refresh_realtime_model_status()
    
    def _on_release_realtime_model(self) -> None:
        """释放语音识别模型"""
        release_online_model()
        self._realtime_load_status.setText("模型已释放")
        QMessageBox.information(self, "提示", "语音识别模型已释放")
        self._refresh_realtime_model_status()

    def _on_import_realtime_model(self) -> None:
        """导入本地模型"""
        from PySide6.QtWidgets import QFileDialog
        
        # 打开文件选择对话框
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("选择模型文件或目录")
        file_dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        file_dialog.setNameFilter("模型文件 (*.tar.bz2);;所有文件 (*)")
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                selected_path = selected_files[0]
                
                # 根据导入文件/目录确定模型名称
                if selected_path.endswith('.tar.bz2'):
                    # 从文件名提取模型名称（去掉 .tar.bz2 后缀）
                    model_name = Path(selected_path).stem  # 例如: sherpa-onnx-streaming-paraformer-bilingual-zh-en
                elif Path(selected_path).is_dir():
                    # 使用目录名作为模型名称
                    model_name = Path(selected_path).name
                else:
                    QMessageBox.warning(self, "警告", "请选择 .tar.bz2 文件或包含模型文件的目录")
                    return
                
                # 禁用按钮
                self._import_realtime_btn.setEnabled(False)
                self._download_realtime_btn.setEnabled(False)
                self._load_realtime_btn.setEnabled(False)
                
                # 显示进度
                self._realtime_load_progress.setVisible(True)
                self._realtime_load_progress.setValue(0)
                self._realtime_load_status.setText("正在导入模型...")
                
                # 创建导入工作线程
                self._realtime_import_worker = RealtimeModelImportWorker(selected_path, model_name, self)
                
                # 连接信号
                self._realtime_import_worker.progress_updated.connect(
                    lambda progress, status: (
                        self._realtime_load_progress.setValue(progress),
                        self._realtime_load_status.setText(status)
                    )
                )
                self._realtime_import_worker.finished.connect(self._on_realtime_import_finished)
                self._realtime_import_worker.error.connect(self._on_realtime_import_error)
                
                # 启动导入
                self._realtime_import_worker.start()
    
    def _on_realtime_import_finished(self, imported_path: str) -> None:
        """模型导入完成"""
        self._realtime_load_progress.setVisible(False)
        self._realtime_load_status.setText("模型导入完成")
        QMessageBox.information(self, "提示", f"模型已导入到: {imported_path}")
        
        # 刷新模型下拉框，让新导入的模型显示出来
        self._populate_streaming_models_combo()
        
        # 选中新导入的模型
        imported_name = Path(imported_path).name
        custom_key = f"custom:{imported_name}"
        for i in range(self._streaming_model_combo.count()):
            if self._streaming_model_combo.itemData(i) == custom_key:
                self._streaming_model_combo.setCurrentIndex(i)
                break
        
        self._refresh_realtime_model_status()
        
        # 清理工作线程
        if hasattr(self, '_realtime_import_worker'):
            self._realtime_import_worker.deleteLater()
            del self._realtime_import_worker
    
    def _on_realtime_import_error(self, error_msg: str) -> None:
        """模型导入失败"""
        self._realtime_load_progress.setVisible(False)
        self._realtime_load_status.setText(f"导入失败: {error_msg}")
        QMessageBox.warning(self, "警告", f"模型导入失败: {error_msg}")
        self._refresh_realtime_model_status()
        
        # 清理工作线程
        if hasattr(self, '_realtime_import_worker'):
            self._realtime_import_worker.deleteLater()
            del self._realtime_import_worker

    def _on_asr_realtime_enabled_changed(self, state: int) -> None:
        """实时语音识别开关状态改变时自动保存"""
        from PySide6.QtCore import Qt
        enabled = state == Qt.CheckState.Checked.value
        config.set_config("ASR_REALTIME_ENABLED", str(enabled).lower())
        config.ASR_REALTIME_ENABLED = enabled

    # ===== 音频设备相关方法 =====

    def _refresh_audio_devices_list(self) -> None:
        """刷新音频设备列表"""
        logger.info("开始刷新音频设备列表")
        
        # 获取当前配置的设备ID
        current_device_id = config.get_audio_input_device()
        
        # 获取可用设备列表
        devices = config.get_audio_devices()
        
        # 阻止信号触发
        self._audio_device_combo.blockSignals(True)
        
        # 清空下拉框
        self._audio_device_combo.clear()
        
        # 添加"默认设备"选项（对应 device_id=None）
        self._audio_device_combo.addItem("默认设备", None)
        
        # 添加设备列表
        for device in devices:
            device_id = device['id']
            device_name = device['name']
            # 显示格式：设备名称 (ID: X)
            display_name = f"{device_name} (ID: {device_id})"
            self._audio_device_combo.addItem(display_name, device_id)
        
        # 根据当前配置选中对应的设备
        if current_device_id is None:
            self._audio_device_combo.setCurrentIndex(0)  # 默认设备
            logger.debug("选中默认设备")
        else:
            # 查找匹配的设备
            found = False
            for i in range(self._audio_device_combo.count()):
                if self._audio_device_combo.itemData(i) == current_device_id:
                    self._audio_device_combo.setCurrentIndex(i)
                    logger.debug(f"选中设备 ID={current_device_id}")
                    found = True
                    break
            if not found:
                # 设备不可用，回退到默认设备
                self._audio_device_combo.setCurrentIndex(0)
                logger.warning(f"配置的设备 ID={current_device_id} 不可用，回退到默认设备")
        
        # 恢复信号
        self._audio_device_combo.blockSignals(False)
        
        # 更新状态标签
        if devices:
            self._audio_device_status.setText(f"已发现 {len(devices)} 个输入设备")
        else:
            self._audio_device_status.setText("未发现输入设备，请检查音频设备连接")
        
        logger.info(f"音频设备列表刷新完成，发现 {len(devices)} 个设备")

    def _on_refresh_audio_devices(self) -> None:
        """刷新设备列表按钮点击处理"""
        logger.info("用户点击刷新设备列表按钮")
        
        # 显示刷新状态
        self._audio_device_status.setText("正在刷新设备列表...")
        self._refresh_devices_btn.setEnabled(False)
        
        # 刷新设备列表
        self._refresh_audio_devices_list()
        
        # 恢复按钮状态
        self._refresh_devices_btn.setEnabled(True)
        
        # 显示刷新完成提示
        QMessageBox.information(self, "提示", "设备列表已刷新")

    def _on_audio_device_changed(self, index: int) -> None:
        """设备选择改变时的处理"""
        device_id = self._audio_device_combo.itemData(index)
        
        logger.info(f"用户选择音频设备: ID={device_id}")
        
        # 自动保存设备选择
        success = config.set_audio_input_device(device_id)
        
        if success:
            if device_id is None:
                self._audio_device_status.setText("已保存：使用系统默认设备")
                logger.info("音频设备配置已保存：使用系统默认设备")
            else:
                device_name = self._audio_device_combo.currentText()
                self._audio_device_status.setText(f"已保存：{device_name}")
                logger.info(f"音频设备配置已保存：ID={device_id}")
        else:
            self._audio_device_status.setText("保存失败，请重试")
            logger.error("音频设备配置保存失败")

    def _on_test_audio_device(self) -> None:
        """测试设备按钮点击处理"""
        logger.info("用户点击测试设备按钮")
        
        # 获取当前选择的设备ID
        device_id = self._audio_device_combo.currentData()
        
        # 禁用测试按钮
        self._test_device_btn.setEnabled(False)
        
        # 显示进度条和状态
        self._device_test_progress.setVisible(True)
        self._device_test_progress.setValue(0)
        self._device_test_status.setText("准备录制测试音频...")
        
        # 创建测试工作线程
        self._audio_device_test_worker = AudioDeviceTestWorker(device_id=device_id, parent=self)
        self._audio_device_test_worker.progress_updated.connect(self._on_device_test_progress)
        self._audio_device_test_worker.finished.connect(self._on_device_test_finished)
        self._audio_device_test_worker.error.connect(self._on_device_test_error)
        self._audio_device_test_worker.start()

    def _on_device_test_progress(self, progress: int, status: str) -> None:
        """设备测试进度更新"""
        self._device_test_progress.setValue(progress)
        self._device_test_status.setText(status)

    def _on_device_test_finished(self, result: str) -> None:
        """设备测试完成"""
        self._device_test_progress.setVisible(False)
        self._device_test_status.setText(result)
        self._test_device_btn.setEnabled(True)
        
        # 清理工作线程
        if hasattr(self, '_audio_device_test_worker') and self._audio_device_test_worker:
            self._audio_device_test_worker.deleteLater()
            self._audio_device_test_worker = None
        
        logger.info(f"设备测试完成: {result}")

    def _on_device_test_error(self, error: str) -> None:
        """设备测试出错"""
        self._device_test_progress.setVisible(False)
        self._device_test_status.setText(f"测试失败: {error}")
        self._test_device_btn.setEnabled(True)
        
        # 清理工作线程
        if hasattr(self, '_audio_device_test_worker') and self._audio_device_test_worker:
            self._audio_device_test_worker.deleteLater()
            self._audio_device_test_worker = None
        
        logger.error(f"设备测试失败: {error}")

    # ===== 实时 ASR 测试相关方法 =====

    def _on_toggle_realtime_test(self) -> None:
        """切换实时测试状态"""
        # 检查是否正在测试
        if hasattr(self, '_realtime_asr_test_worker') and self._realtime_asr_test_worker is not None:
            # 正在测试，停止测试
            self._realtime_asr_test_worker.stop()
            self._test_asr_btn.setText("开始实时测试")
            self._asr_test_status.setText("正在停止测试...")
            return

        # 检查流式模型是否已加载
        if not is_online_model_loaded():
            QMessageBox.warning(self, "警告", "语音识别模型未加载，请先加载模型后再进行测试")
            return

        # 开始实时测试
        self._asr_test_result.clear()
        self._copy_asr_result_btn.setEnabled(False)
        self._test_asr_btn.setText("停止测试")
        self._asr_test_status.setText("准备开始实时测试...")

        # 获取当前选择的音频设备
        device_id = self._audio_device_combo.currentData()

        # 创建并启动工作线程
        self._realtime_asr_test_worker = RealtimeASRTestWorker(device_id=device_id, parent=self)
        self._realtime_asr_test_worker.result_updated.connect(self._on_realtime_asr_result_updated)
        self._realtime_asr_test_worker.status_updated.connect(self._on_realtime_asr_status_updated)
        self._realtime_asr_test_worker.error.connect(self._on_realtime_asr_error)
        self._realtime_asr_test_worker.finished.connect(self._on_realtime_asr_finished)
        self._realtime_asr_test_worker.start()

    def _on_realtime_asr_result_updated(self, result: str) -> None:
        """实时识别结果更新"""
        self._asr_test_result.setPlainText(result)
        self._copy_asr_result_btn.setEnabled(True)

    def _on_realtime_asr_status_updated(self, status: str) -> None:
        """实时测试状态更新"""
        self._asr_test_status.setText(status)

    def _on_realtime_asr_error(self, error: str) -> None:
        """实时测试出错"""
        self._test_asr_btn.setText("开始实时测试")
        self._asr_test_status.setText(f"测试失败: {error}")
        QMessageBox.warning(self, "警告", f"实时测试失败: {error}")

        # 清理工作线程
        if hasattr(self, '_realtime_asr_test_worker') and self._realtime_asr_test_worker:
            self._realtime_asr_test_worker.deleteLater()
            self._realtime_asr_test_worker = None

    def _on_realtime_asr_finished(self) -> None:
        """实时测试完成"""
        self._test_asr_btn.setText("开始实时测试")
        self._asr_test_status.setText("测试完成")

        # 清理工作线程
        if hasattr(self, '_realtime_asr_test_worker') and self._realtime_asr_test_worker:
            self._realtime_asr_test_worker.deleteLater()
            self._realtime_asr_test_worker = None

    def _on_copy_asr_result(self) -> None:
        """复制 ASR 识别结果到剪贴板"""
        from PySide6.QtWidgets import QApplication
        text = self._asr_test_result.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self._asr_test_status.setText("结果已复制到剪贴板")

    # ===== TTS 相关方法 =====
    
    def _refresh_tts_model_status(self) -> None:
        """刷新 TTS 模型状态"""
        from tts import is_tts_model_loaded, get_tts_model_path, get_num_speakers
        is_loaded = is_tts_model_loaded()
        model_path = get_tts_model_path()
        num_speakers = get_num_speakers()
        
        # 音色名称映射（sherpa-onnx-vits-zh-ll 模型）
        speaker_names = {
            0: "苏映雪（女声）",
            1: "顾念（女声）",
            2: "付思雨（女声）",
            3: "冰娇（女声）",
            4: "巴总（男声）",
        }
        
        if is_loaded:
            self._tts_model_status.setText(f"状态：模型已加载（支持 {num_speakers} 个音色）")
            self._load_tts_btn.setEnabled(False)
            self._release_tts_btn.setEnabled(True)
            self._tts_test_btn.setEnabled(True)
            
            # 更新说话人选项
            self._tts_speaker_combo.clear()
            for i in range(num_speakers):
                name = speaker_names.get(i, f"音色 {i}")
                self._tts_speaker_combo.addItem(name, i)
        else:
            config_path = self._tts_model_path_edit.text().strip()
            if config_path:
                from pathlib import Path
                if Path(config_path).exists():
                    self._tts_model_status.setText(f"状态：模型路径有效，未加载")
                    self._load_tts_btn.setEnabled(True)
                    self._release_tts_btn.setEnabled(False)
                    self._tts_test_btn.setEnabled(False)
                else:
                    self._tts_model_status.setText(f"状态：模型目录不存在")
                    self._load_tts_btn.setEnabled(False)
                    self._release_tts_btn.setEnabled(False)
                    self._tts_test_btn.setEnabled(False)
            else:
                self._tts_model_status.setText("状态：未配置路径（将使用默认模型）")
                self._load_tts_btn.setEnabled(True)
                self._release_tts_btn.setEnabled(False)
                self._tts_test_btn.setEnabled(False)
        
        # 加载保存的参数
        speaker_id = getattr(config, 'TTS_SPEAKER_ID', 0)
        speed = getattr(config, 'TTS_SPEED', 1.0)
        
        idx = self._tts_speaker_combo.findData(speaker_id)
        if idx >= 0:
            self._tts_speaker_combo.setCurrentIndex(idx)
        
        self._tts_speed_slider.setValue(int(speed * 100))
        self._tts_speed_label.setText(f"{speed:.1f}")
    
    def _on_browse_tts_model(self) -> None:
        """浏览选择 TTS 模型目录"""
        from PySide6.QtWidgets import QFileDialog
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "选择 TTS 模型目录",
            ""
        )
        if dir_path:
            self._tts_model_path_edit.setText(dir_path)
            self._refresh_tts_model_status()
    
    def _on_save_tts_model_path(self) -> None:
        """保存 TTS 模型路径"""
        model_path = self._tts_model_path_edit.text().strip()
        
        # 空路径表示使用自动下载的模型
        if model_path:
            from pathlib import Path
            if not Path(model_path).exists():
                QMessageBox.warning(self, "警告", "模型目录不存在")
                return
        
        config.set_config("TTS_MODEL_PATH", model_path)
        config.TTS_MODEL_PATH = model_path
        
        QMessageBox.information(self, "提示", "模型路径已保存")
        self._refresh_tts_model_status()
    
    def _on_tts_model_type_changed(self, index: int) -> None:
        """TTS 模型类型选择变化时自动保存"""
        model_type = self._tts_model_type_combo.currentData()
        config.set_config("TTS_MODEL_TYPE", model_type)
        config.TTS_MODEL_TYPE = model_type
        
        # 清空模型路径，让系统使用自动下载的模型
        self._tts_model_path_edit.setText("")
        config.set_config("TTS_MODEL_PATH", "")
        config.TTS_MODEL_PATH = ""
        
        # 重置本地模型选择
        self._tts_local_model_combo.setCurrentIndex(0)
        
        # 提示用户需要重新加载模型
        QMessageBox.information(
            self,
            "提示",
            f"已切换到 {self._tts_model_type_combo.currentText()}\n请点击\"加载模型\"按钮下载并加载新模型"
        )
        self._refresh_tts_model_status()
    
    def _populate_tts_local_models_combo(self) -> None:
        """填充本地 TTS 模型下拉框"""
        from tts import get_local_tts_models_list, get_tts_model_dir, TTS_MODEL_OPTIONS
        
        self._tts_local_model_combo.blockSignals(True)
        # 保留第一项"使用预设模型"
        self._tts_local_model_combo.clear()
        self._tts_local_model_combo.addItem("使用预设模型", "")
        
        # 添加预设模型（已下载的）
        tts_dir = get_tts_model_dir()
        if tts_dir.exists():
            for model_type, model_config in TTS_MODEL_OPTIONS.items():
                model_name = model_config["model_name"]
                model_dir = tts_dir / model_name
                if model_dir.exists():
                    onnx_files = list(model_dir.glob("*.onnx"))
                    if onnx_files:
                        display_name = f"[已下载] {model_config['name']}"
                        self._tts_local_model_combo.addItem(display_name, str(model_dir))
        
        # 添加本地自定义模型
        local_models = get_local_tts_models_list()
        for model_name, model_path in local_models.items():
            display_name = f"[本地] {model_name}"
            self._tts_local_model_combo.addItem(display_name, model_path)
        
        # 从配置中恢复选中的模型
        saved_path = getattr(config, 'TTS_MODEL_PATH', '')
        if saved_path:
            for i in range(self._tts_local_model_combo.count()):
                if self._tts_local_model_combo.itemData(i) == saved_path:
                    self._tts_local_model_combo.setCurrentIndex(i)
                    break
        
        self._tts_local_model_combo.blockSignals(False)
    
    def _on_tts_local_model_selected(self, index: int) -> None:
        """本地 TTS 模型选择变化时的处理"""
        model_path = self._tts_local_model_combo.currentData()
        
        # 更新路径输入框
        self._tts_model_path_edit.setText(model_path if model_path else "")
        
        # 保存到配置
        config.set_config("TTS_MODEL_PATH", model_path if model_path else "")
        config.TTS_MODEL_PATH = model_path if model_path else ""
        
        # 刷新状态
        self._refresh_tts_model_status()
    
    def _on_tts_speed_changed(self, value: int) -> None:
        """语速滑块值改变"""
        speed = value / 100.0
        self._tts_speed_label.setText(f"{speed:.1f}")
    
    def _on_load_tts_model(self) -> None:
        """加载 TTS 模型"""
        from tts import load_tts_model
        
        # 获取配置的模型路径和模型类型
        model_path = self._tts_model_path_edit.text().strip()
        model_type = self._tts_model_type_combo.currentData()
        
        self._load_tts_btn.setEnabled(False)
        self._release_tts_btn.setEnabled(False)
        self._tts_load_progress.setVisible(True)
        self._tts_load_progress.setValue(0)
        self._tts_load_status.setText("正在加载模型...")
        
        try:
            def load_callback(progress: int, status: str):
                self._tts_load_progress.setValue(progress)
                self._tts_load_status.setText(status)
            
            # 如果有配置路径，使用它；否则根据模型类型自动下载
            if model_path:
                success = load_tts_model(model_path, callback=load_callback, auto_download=False)
            else:
                success = load_tts_model(model_type=model_type, callback=load_callback, auto_download=True)
            
            self._tts_load_progress.setVisible(False)
            
            if success:
                self._tts_load_status.setText("模型加载完成")
                QMessageBox.information(self, "提示", "TTS 模型加载成功")
            else:
                self._tts_load_status.setText("加载失败")
                QMessageBox.warning(self, "警告", "TTS 模型加载失败")
            
            self._refresh_tts_model_status()
        except Exception as e:
            logger.exception(f"加载 TTS 模型时发生异常: {e}")
            self._tts_load_progress.setVisible(False)
            self._tts_load_status.setText(f"加载失败: {str(e)}")
            QMessageBox.warning(self, "警告", f"加载 TTS 模型时发生错误: {str(e)}")
            self._refresh_tts_model_status()
    
    def _on_release_tts_model(self) -> None:
        """释放 TTS 模型"""
        from tts import release_tts_model
        release_tts_model()
        self._tts_load_status.setText("模型已释放")
        QMessageBox.information(self, "提示", "TTS 模型已释放")
        self._refresh_tts_model_status()
    
    def _on_save_tts_params(self) -> None:
        """保存 TTS 参数"""
        speaker_id = self._tts_speaker_combo.currentData()
        speed = self._tts_speed_slider.value() / 100.0
        
        config.set_config("TTS_SPEAKER_ID", str(speaker_id))
        config.set_config("TTS_SPEED", str(speed))
        
        config.TTS_SPEAKER_ID = speaker_id
        config.TTS_SPEED = speed
        
        QMessageBox.information(self, "提示", "TTS 参数已保存")
    
    def _on_save_tts_auto_load(self) -> None:
        """保存 TTS 自动加载配置"""
        auto_load = self._tts_auto_load_checkbox.isChecked()
        config.set_config("TTS_AUTO_LOAD", str(auto_load).lower())
        config.TTS_AUTO_LOAD = auto_load
        QMessageBox.information(self, "提示", f"已保存：程序启动{'自动加载' if auto_load else '不自动加载'}语音合成模型")
    
    def _on_tts_auto_load_changed(self, state: int) -> None:
        """TTS 自动加载勾选状态改变时自动保存"""
        from PySide6.QtCore import Qt
        auto_load = state == Qt.CheckState.Checked.value
        config.set_config("TTS_AUTO_LOAD", str(auto_load).lower())
        config.TTS_AUTO_LOAD = auto_load
    
    def _on_test_tts(self) -> None:
        """测试朗读"""
        from tts import speak_text, is_tts_model_loaded
        
        if not is_tts_model_loaded():
            QMessageBox.warning(self, "警告", "请先加载 TTS 模型")
            return
        
        text = self._tts_test_text_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "警告", "请输入测试文本")
            return
        
        speaker_id = self._tts_speaker_combo.currentData()
        speed = self._tts_speed_slider.value() / 100.0
        
        self._tts_test_btn.setEnabled(False)
        self._tts_stop_btn.setEnabled(True)
        self._tts_test_status.setText("正在朗读...")
        
        def on_finished():
            self._tts_test_btn.setEnabled(True)
            self._tts_stop_btn.setEnabled(False)
            self._tts_test_status.setText("朗读完成")
        
        self._tts_playing = True
        
        def _speak():
            try:
                speak_text(text, speaker_id, speed, on_finished)
            except Exception as e:
                logger.exception(f"朗读时发生错误: {e}")
                self._tts_test_status.setText(f"朗读失败: {str(e)}")
                on_finished()
        
        import threading
        self._tts_thread = threading.Thread(target=_speak, daemon=True)
        self._tts_thread.start()
    
    def _on_stop_tts(self) -> None:
        """停止朗读"""
        try:
            import sounddevice as sd
            sd.stop()
            self._tts_test_btn.setEnabled(True)
            self._tts_stop_btn.setEnabled(False)
            self._tts_test_status.setText("朗读已停止")
        except Exception as e:
            logger.exception(f"停止朗读时发生错误: {e}")

    # ===== 系统提示词配置相关方法 =====

    def _on_prompt_type_changed(self, index: int) -> None:
        """会话类型切换时加载对应的模板"""
        conv_type = self._prompt_type_combo.currentData()
        if conv_type:
            self._load_template_for_type(conv_type)

    def _load_template_for_type(self, conv_type: str) -> None:
        """加载指定会话类型的模板"""
        template = get_template_for_conversation_type(conv_type)
        # 阻止信号触发，避免验证时重复触发
        self._template_edit.blockSignals(True)
        self._template_edit.setPlainText(template)
        self._template_edit.blockSignals(False)
        # 手动触发验证
        self._validate_current_template()

    def _validate_current_template(self) -> None:
        """验证当前模板中的占位符"""
        template = self._template_edit.toPlainText()
        is_valid, invalid_placeholders = validate_template(template)
        
        if is_valid:
            self._template_validation_label.setText("✓ 模板验证通过，所有占位符均有效")
            self._template_validation_label.setStyleSheet("color: #10b981; font-size: 9pt;")
        else:
            invalid_str = ", ".join(invalid_placeholders)
            self._template_validation_label.setText(f"⚠ 模板包含无效占位符: {invalid_str}")
            self._template_validation_label.setStyleSheet("color: #ef4444; font-size: 9pt;")

    def _on_template_text_changed(self) -> None:
        """模板内容变化时验证"""
        self._validate_current_template()

    def _on_save_template(self) -> None:
        """保存当前模板"""
        conv_type = self._prompt_type_combo.currentData()
        if not conv_type:
            return
        
        template = self._template_edit.toPlainText()
        
        # 验证模板
        is_valid, invalid_placeholders = validate_template(template)
        if not is_valid:
            QMessageBox.warning(
                self,
                "警告",
                f"模板包含无效占位符: {', '.join(invalid_placeholders)}\n请修正后再保存。"
            )
            return
        
        try:
            update_template_for_conversation_type(conv_type, template)
            QMessageBox.information(self, "提示", "模板已保存")
        except Exception as e:
            logger.exception(f"保存模板失败: {e}")
            QMessageBox.warning(self, "警告", f"保存模板失败: {str(e)}")

    def _on_reset_template(self) -> None:
        """重置当前模板为默认模板"""
        conv_type = self._prompt_type_combo.currentData()
        if not conv_type:
            return
        
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要将当前模板重置为默认模板吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                reset_template_for_conversation_type(conv_type)
                self._load_template_for_type(conv_type)
                QMessageBox.information(self, "提示", "模板已重置为默认")
            except Exception as e:
                logger.exception(f"重置模板失败: {e}")
                QMessageBox.warning(self, "警告", f"重置模板失败: {str(e)}")

    def _on_preview_template(self) -> None:
        """预览模板填充后的效果"""
        conv_type = self._prompt_type_combo.currentData()
        if not conv_type:
            return
        
        template = self._template_edit.toPlainText()
        
        # 创建预览对话框
        preview_dialog = QDialog(self)
        preview_dialog.setWindowTitle(f"模板预览 - {self._prompt_type_combo.currentText()}")
        preview_dialog.setModal(True)
        preview_dialog.resize(600, 500)
        
        layout = QVBoxLayout(preview_dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # 说明文字
        info_label = QLabel("以下为使用示例数据填充后的模板效果预览：")
        info_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        layout.addWidget(info_label)
        
        # 预览内容
        preview_text = QTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setFont(QFont("Consolas", 10))
        preview_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        
        # 使用 DynamicSystemPrompt 的 preview_with_sample_data 方法
        try:
            dsp = DynamicSystemPrompt(_template=template, _conversation_type=conv_type)
            preview_content = dsp.preview_with_sample_data()
            preview_text.setPlainText(preview_content)
        except Exception as e:
            preview_text.setPlainText(f"预览生成失败: {str(e)}")
        
        layout.addWidget(preview_text)
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(preview_dialog.accept)
        layout.addWidget(close_btn)
        
        preview_dialog.exec()

    def _refresh_prompt_template_status(self) -> None:
        """刷新系统提示词模板状态"""
        # 加载当前选中会话类型的模板
        conv_type = self._prompt_type_combo.currentData()
        if conv_type:
            self._load_template_for_type(conv_type)

    # ===== Live2D 2D Live 配置相关方法 =====

    def _refresh_live2d_model_list(self) -> None:
        """刷新 Live2D 模型列表"""
        from ui.live2d_model_manager import scan_models
        
        self._live2d_model_combo.clear()
        models = scan_models()
        
        if not models:
            self._live2d_model_combo.addItem("未找到可用模型", "")
            self._live2d_model_info_label.setText("提示：请将 Live2D 模型放置在 PersonalData/2DLiveFiles 目录下")
            return
        
        current_model = getattr(config, 'LIVE2D_MODEL_NAME', '')
        
        for model_info in models:
            self._live2d_model_combo.addItem(model_info.name, model_info.name)
        
        # 选中当前配置的模型
        if current_model:
            idx = self._live2d_model_combo.findData(current_model)
            if idx >= 0:
                self._live2d_model_combo.setCurrentIndex(idx)
        
        # 显示第一个模型的信息
        self._update_live2d_model_info()

    def _update_live2d_model_info(self) -> None:
        """更新模型信息显示"""
        from ui.live2d_model_manager import scan_models
        
        model_name = self._live2d_model_combo.currentData()
        if not model_name:
            self._live2d_model_info_label.setText("")
            return
        
        models = scan_models()
        for model_info in models:
            if model_info.name == model_name:
                motions = ", ".join(model_info.available_motions[:5])
                if len(model_info.available_motions) > 5:
                    motions += f" 等 {len(model_info.available_motions)} 个"
                
                physics_status = "已配置" if model_info.has_physics else "未配置"
                
                self._live2d_model_info_label.setText(
                    f"模型名称：{model_info.name}\n"
                    f"动作组：{motions}\n"
                    f"物理引擎：{physics_status}\n"
                    f"模型目录：{model_info.model_dir.name}"
                )
                return
        
        self._live2d_model_info_label.setText("未找到该模型信息")

    def _on_live2d_enable_changed(self, state: int) -> None:
        """Live2D 启用状态改变"""
        enabled = state == Qt.CheckState.Checked.value
        config.set_config("LIVE2D_ENABLED", str(enabled).lower())
        config.LIVE2D_ENABLED = enabled
        
        # 更新 UI 状态
        self._live2d_model_combo.setEnabled(enabled)
        self._live2d_refresh_btn.setEnabled(enabled)
        self._live2d_load_btn.setEnabled(enabled)
        self._live2d_width_spin.setEnabled(enabled)
        self._live2d_height_spin.setEnabled(enabled)

    def _on_live2d_load_clicked(self) -> None:
        """点击加载 Live2D 模型，运行时动态切换"""
        enabled = self._live2d_enable_check.isChecked()
        
        if enabled:
            self._apply_live2d_mode()
        else:
            self._apply_button_mode()

    def _apply_live2d_mode(self) -> None:
        """应用 Live2D 模式到悬浮球"""
        if not self.parent():
            return
        
        main_window = self.parent()
        if not hasattr(main_window, '_floating_ball') or main_window._floating_ball is None:
            QMessageBox.warning(self, "警告", "无法获取悬浮球组件")
            return
        
        floating_ball = main_window._floating_ball
        
        # 重新读取配置
        import importlib
        importlib.reload(config)
        
        success = floating_ball.switch_to_live2d_mode()
        if success:
            # 手动加载模型
            floating_ball.load_live2d_model()
            model_name = self._live2d_model_combo.currentData() or "默认"
            QMessageBox.information(self, "提示", f"Live2D 模式已启用\n模型: {model_name}")
        else:
            QMessageBox.warning(self, "警告", "切换到 Live2D 模式失败\n请检查模型是否存在")

    def _apply_button_mode(self) -> None:
        """应用按钮模式到悬浮球"""
        if not self.parent():
            return
        
        main_window = self.parent()
        if not hasattr(main_window, '_floating_ball') or main_window._floating_ball is None:
            return
        
        floating_ball = main_window._floating_ball
        floating_ball.switch_to_button_mode()
        
        QMessageBox.information(self, "提示", "已切换回按钮模式")

    def _on_live2d_model_changed(self, index: int) -> None:
        """Live2D 模型选择改变"""
        model_name = self._live2d_model_combo.currentData()
        if model_name:
            config.set_config("LIVE2D_MODEL_NAME", model_name)
            config.LIVE2D_MODEL_NAME = model_name
            self._update_live2d_model_info()

    def _on_live2d_size_changed(self, value: int) -> None:
        """Live2D 悬浮球尺寸改变"""
        width = self._live2d_width_spin.value()
        height = self._live2d_height_spin.value()
        
        config.set_config("LIVE2D_BALL_WIDTH", str(width))
        config.set_config("LIVE2D_BALL_HEIGHT", str(height))
        config.LIVE2D_BALL_WIDTH = width
        config.LIVE2D_BALL_HEIGHT = height

    def _refresh_live2d_settings(self) -> None:
        """刷新 Live2D 设置界面"""
        # 启用状态
        enabled = getattr(config, 'LIVE2D_ENABLED', False)
        self._live2d_enable_check.blockSignals(True)
        self._live2d_enable_check.setChecked(enabled)
        self._live2d_enable_check.blockSignals(False)
        
        # 更新 UI 状态
        self._live2d_model_combo.setEnabled(enabled)
        self._live2d_refresh_btn.setEnabled(enabled)
        self._live2d_load_btn.setEnabled(enabled)
        self._live2d_width_spin.setEnabled(enabled)
        self._live2d_height_spin.setEnabled(enabled)
        
        # 模型列表
        self._refresh_live2d_model_list()
        
        # 尺寸
        width = getattr(config, 'LIVE2D_BALL_WIDTH', 200)
        height = getattr(config, 'LIVE2D_BALL_HEIGHT', 200)
        self._live2d_width_spin.blockSignals(True)
        self._live2d_height_spin.blockSignals(True)
        self._live2d_width_spin.setValue(width)
        self._live2d_height_spin.setValue(height)
        self._live2d_width_spin.blockSignals(False)
        self._live2d_height_spin.blockSignals(False)