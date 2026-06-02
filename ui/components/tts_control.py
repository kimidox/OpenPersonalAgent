"""
TTS控制组件 - 提供TTS功能的UI控制面板

包含TTS开关、音色选择、语速/音量调节、自动朗读开关等控件。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from logger import get_module_logger

logger = get_module_logger("tts_control")

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tts import VoiceManager, get_tts_config
from ui.styles.style_manager import StyleManager

if TYPE_CHECKING:
    from tts import TTSConfigManager


class TTSControlWidget(QWidget):
    """
    TTS控制组件
    
    提供完整的TTS设置控制界面，包括：
    - TTS开关按钮
    - 音色选择下拉框
    - 语速调节滑块
    - 音量调节滑块
    - 自动朗读开关
    - 当前状态显示
    """
    
    config_changed = Signal()
    tts_status_changed = Signal(str)
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tts_config: TTSConfigManager = get_tts_config()
        self._voice_manager: VoiceManager = VoiceManager()
        self._current_status: str = "已停止"
        self._setup_ui()
        self._apply_style()
        self._load_config()
        self._refresh_voices()
    
    def _apply_style(self) -> None:
        style = StyleManager.get_style("settings_dialog_stylesheet")
        if style:
            self.setStyleSheet(style)
    
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        
        enable_group = QGroupBox("TTS功能设置")
        enable_layout = QVBoxLayout(enable_group)
        enable_layout.setSpacing(8)
        
        enable_row = QHBoxLayout()
        self._enable_check = QCheckBox("启用TTS功能")
        self._enable_check.stateChanged.connect(self._on_enable_changed)
        enable_row.addWidget(self._enable_check)
        enable_row.addStretch()
        enable_layout.addLayout(enable_row)
        
        auto_read_row = QHBoxLayout()
        self._auto_read_check = QCheckBox("自动朗读AI回复")
        self._auto_read_check.stateChanged.connect(self._on_auto_read_changed)
        auto_read_row.addWidget(self._auto_read_check)
        auto_hint = QLabel("（当AI回复完成时自动朗读）")
        auto_hint.setStyleSheet("color: #6b7280; font-size: 9pt;")
        auto_read_row.addWidget(auto_hint)
        auto_read_row.addStretch()
        enable_layout.addLayout(auto_read_row)
        
        layout.addWidget(enable_group)
        
        voice_group = QGroupBox("音色设置")
        voice_layout = QVBoxLayout(voice_group)
        voice_layout.setSpacing(8)
        
        voice_row = QHBoxLayout()
        voice_label = QLabel("选择音色：")
        voice_label.setFont(QFont("Microsoft YaHei", 9))
        voice_row.addWidget(voice_label)
        
        self._voice_combo = QComboBox()
        self._voice_combo.setMinimumWidth(200)
        self._voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_row.addWidget(self._voice_combo)
        
        self._refresh_voice_btn = QPushButton("刷新")
        self._refresh_voice_btn.setFixedWidth(60)
        self._refresh_voice_btn.clicked.connect(self._refresh_voices)
        voice_row.addWidget(self._refresh_voice_btn)
        voice_row.addStretch()
        voice_layout.addLayout(voice_row)
        
        voice_hint_row = QHBoxLayout()
        self._voice_hint_label = QLabel("音色目录：未设置")
        self._voice_hint_label.setStyleSheet("color: #6b7280; font-size: 9pt;")
        voice_hint_row.addWidget(self._voice_hint_label)
        voice_hint_row.addStretch()
        voice_layout.addLayout(voice_hint_row)
        
        layout.addWidget(voice_group)
        
        params_group = QGroupBox("参数调节")
        params_layout = QVBoxLayout(params_group)
        params_layout.setSpacing(12)
        
        speed_row = QHBoxLayout()
        speed_label = QLabel("语速：")
        speed_label.setFont(QFont("Microsoft YaHei", 9))
        speed_label.setFixedWidth(50)
        speed_row.addWidget(speed_label)
        
        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setMinimum(50)
        self._speed_slider.setMaximum(200)
        self._speed_slider.setValue(100)
        self._speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._speed_slider.setTickInterval(25)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self._speed_slider)
        
        self._speed_value_label = QLabel("1.0x")
        self._speed_value_label.setFixedWidth(50)
        self._speed_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        speed_row.addWidget(self._speed_value_label)
        
        speed_hint = QLabel("（范围：0.5x - 2.0x）")
        speed_hint.setStyleSheet("color: #6b7280; font-size: 9pt;")
        speed_row.addWidget(speed_hint)
        speed_row.addStretch()
        params_layout.addLayout(speed_row)
        
        volume_row = QHBoxLayout()
        volume_label = QLabel("音量：")
        volume_label.setFont(QFont("Microsoft YaHei", 9))
        volume_label.setFixedWidth(50)
        volume_row.addWidget(volume_label)
        
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setMinimum(0)
        self._volume_slider.setMaximum(100)
        self._volume_slider.setValue(100)
        self._volume_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._volume_slider.setTickInterval(10)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_row.addWidget(self._volume_slider)
        
        self._volume_value_label = QLabel("100%")
        self._volume_value_label.setFixedWidth(50)
        self._volume_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        volume_row.addWidget(self._volume_value_label)
        
        volume_hint = QLabel("（范围：0% - 100%）")
        volume_hint.setStyleSheet("color: #6b7280; font-size: 9pt;")
        volume_row.addWidget(volume_hint)
        volume_row.addStretch()
        params_layout.addLayout(volume_row)
        
        layout.addWidget(params_group)
        
        status_group = QGroupBox("当前状态")
        status_layout = QVBoxLayout(status_group)
        
        status_row = QHBoxLayout()
        self._status_label = QLabel("状态：已停止")
        self._status_label.setFont(QFont("Microsoft YaHei", 9))
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_layout.addLayout(status_row)
        
        self._test_btn = QPushButton("测试朗读")
        self._test_btn.setFixedWidth(100)
        self._test_btn.clicked.connect(self._on_test_tts)
        status_layout.addWidget(self._test_btn)
        
        layout.addWidget(status_group)
        
        layout.addStretch()
    
    def _load_config(self) -> None:
        config = self._tts_config.config
        
        self._enable_check.setChecked(config.enabled)
        self._auto_read_check.setChecked(config.auto_read)
        
        speed_value = int(config.speed * 100)
        self._speed_slider.setValue(speed_value)
        self._update_speed_label(speed_value)
        
        volume_value = int(config.volume * 100)
        self._volume_slider.setValue(volume_value)
        self._update_volume_label(volume_value)
        
        voice_dir = self._tts_config.voice_dir
        if voice_dir and str(voice_dir):
            self._voice_hint_label.setText(f"音色目录：{voice_dir}")
        else:
            self._voice_hint_label.setText("音色目录：未设置")
    
    def _refresh_voices(self) -> None:
        self._voice_combo.clear()
        
        voice_dir = self._tts_config.voice_dir
        if voice_dir and str(voice_dir):
            self._voice_manager = VoiceManager(voice_dir)
        else:
            self._voice_manager = VoiceManager()
        
        voices = self._voice_manager.scan_voices()
        
        if not voices:
            self._voice_combo.addItem("未发现可用音色", "")
            self._voice_combo.setEnabled(False)
            self._voice_hint_label.setText("音色目录：未发现音色模型")
            return
        
        self._voice_combo.setEnabled(True)
        
        display_names = self._voice_manager.get_voice_display_names()
        for voice in voices:
            display_name = display_names.get(voice.name, voice.name)
            self._voice_combo.addItem(display_name, voice.name)
        
        current_voice = self._tts_config.voice_model
        if current_voice:
            for i in range(self._voice_combo.count()):
                if self._voice_combo.itemData(i) == current_voice:
                    self._voice_combo.setCurrentIndex(i)
                    break
        
        voice_dir_str = str(self._voice_manager.voice_dir)
        self._voice_hint_label.setText(f"音色目录：{voice_dir_str}")
        logger.info(f"刷新音色列表，发现 {len(voices)} 个音色")
    
    def _on_enable_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        self._tts_config.enabled = enabled
        self._update_status("已停止" if not enabled else "已启用")
        self.config_changed.emit()
    
    def _on_auto_read_changed(self, state: int) -> None:
        auto_read = state == Qt.CheckState.Checked.value
        self._tts_config.auto_read = auto_read
        self.config_changed.emit()
    
    def _on_voice_changed(self, index: int) -> None:
        if index < 0:
            return
        
        voice_name = self._voice_combo.itemData(index)
        if voice_name:
            self._tts_config.voice_model = voice_name
            self.config_changed.emit()
    
    def _on_speed_changed(self, value: int) -> None:
        speed = value / 100.0
        self._tts_config.speed = speed
        self._update_speed_label(value)
        self.config_changed.emit()
    
    def _update_speed_label(self, value: int) -> None:
        speed = value / 100.0
        self._speed_value_label.setText(f"{speed:.1f}x")
    
    def _on_volume_changed(self, value: int) -> None:
        volume = value / 100.0
        self._tts_config.volume = volume
        self._update_volume_label(value)
        self.config_changed.emit()
    
    def _update_volume_label(self, value: int) -> None:
        self._volume_value_label.setText(f"{value}%")
    
    def _on_test_tts(self) -> None:
        if not self._tts_config.enabled:
            self._update_status("TTS未启用")
            return
        
        voice_name = self._voice_combo.currentData()
        if not voice_name:
            self._update_status("请先选择音色")
            return
        
        self._update_status("正在测试朗读...")
        self.tts_status_changed.emit("testing")
        
        try:
            from tts import TTSSynthesizer
            
            voice_dir = self._tts_config.voice_dir
            synthesizer = TTSSynthesizer(voice_dir)
            
            if not synthesizer.initialize():
                self._update_status("初始化失败")
                return
            
            synthesizer.set_speed(self._tts_config.speed)
            synthesizer.set_volume(self._tts_config.volume)
            
            if not synthesizer.load_voice(voice_name):
                self._update_status("音色加载失败")
                return
            
            success = synthesizer.speak_immediately(
                "这是一个测试语音，TTS功能已正常工作。",
                callback=lambda: self._update_status("测试完成")
            )
            
            if not success:
                self._update_status("测试失败")
                
        except Exception as e:
            logger.exception(f"测试TTS失败: {e}")
            self._update_status(f"测试出错: {str(e)[:30]}")
    
    def _update_status(self, status: str) -> None:
        self._current_status = status
        self._status_label.setText(f"状态：{status}")
        self.tts_status_changed.emit(status)
    
    def set_status(self, status: str) -> None:
        self._update_status(status)
    
    def get_current_status(self) -> str:
        return self._current_status
    
    def reload_config(self) -> None:
        self._tts_config.reload_config()
        self._load_config()
        self._refresh_voices()