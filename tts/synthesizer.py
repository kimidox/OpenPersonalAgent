"""
语音合成协调器 - 整合TTS引擎、音色管理器和音频播放器

提供异步合成、朗读队列管理等功能。
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, List
import threading
import queue
import re

from .tts_engine import TTSEngine, TTSConfig
from .voice_manager import VoiceManager, VoiceInfo
from .audio_player import AudioPlayer
from logger import get_module_logger

logger = get_module_logger("synthesizer")


class SynthesizerState(Enum):
    """合成器状态"""
    IDLE = "idle"
    INITIALIZING = "initializing"
    READY = "ready"
    SYNTHESIZING = "synthesizing"
    PLAYING = "playing"
    ERROR = "error"


@dataclass
class SynthesizeTask:
    """合成任务"""
    text: str
    callback: Optional[Callable[[], None]] = None
    priority: int = 0


@dataclass
class TTSOptions:
    """TTS选项"""
    speed: float = 1.0
    volume: float = 1.0
    voice_name: Optional[str] = None
    auto_play: bool = True


class TTSSynthesizer:
    """
    语音合成协调器
    
    整合TTS引擎、音色管理器和音频播放器，
    提供统一的语音合成接口。
    """
    
    def __init__(self, voice_dir: Optional[Path] = None):
        """
        初始化合成器
        
        Args:
            voice_dir: 音色目录路径，默认为 PersonalData/voices/
        """
        self._engine = TTSEngine()
        self._voice_manager = VoiceManager(voice_dir)
        self._audio_player = AudioPlayer()
        
        self._state = SynthesizerState.IDLE
        self._enabled = False
        self._auto_read = True
        
        self._task_queue: queue.Queue[Optional[SynthesizeTask]] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        
        self._current_voice: Optional[str] = None
        self._options = TTSOptions()
        
        self._lock = threading.Lock()
        self._on_state_change: Optional[Callable[[SynthesizerState], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
    
    @property
    def state(self) -> SynthesizerState:
        """当前状态"""
        return self._state
    
    @property
    def is_enabled(self) -> bool:
        """是否启用"""
        return self._enabled
    
    @property
    def is_ready(self) -> bool:
        """是否就绪"""
        return self._state in (SynthesizerState.READY, SynthesizerState.IDLE)
    
    @property
    def is_playing(self) -> bool:
        """是否正在播放"""
        return self._audio_player.is_playing
    
    @property
    def current_voice(self) -> Optional[str]:
        """当前音色名称"""
        return self._current_voice
    
    @property
    def voice_manager(self) -> VoiceManager:
        """获取音色管理器"""
        return self._voice_manager
    
    @property
    def available_voices(self) -> List[str]:
        """获取可用音色列表"""
        return self._voice_manager.get_voice_names()
    
    @property
    def speed(self) -> float:
        """当前语速"""
        return self._options.speed
    
    @property
    def volume(self) -> float:
        """当前音量"""
        return self._options.volume
    
    def set_on_state_change(self, callback: Optional[Callable[[SynthesizerState], None]]):
        """设置状态变化回调"""
        self._on_state_change = callback
    
    def set_on_error(self, callback: Optional[Callable[[str], None]]):
        """设置错误回调"""
        self._on_error = callback
    
    def set_speed(self, speed: float):
        """设置语速 (0.5 - 2.0)"""
        self._options.speed = max(0.5, min(2.0, speed))
        self._engine.set_speed(self._options.speed)
    
    def set_volume(self, volume: float):
        """设置音量 (0.0 - 1.0)"""
        self._options.volume = max(0.0, min(1.0, volume))
        self._engine.set_volume(self._options.volume)
        self._audio_player.set_volume(self._options.volume)
    
    def set_auto_read(self, auto_read: bool):
        """设置是否自动朗读"""
        self._auto_read = auto_read
    
    def initialize(self) -> bool:
        """
        初始化合成器
        
        扫描音色、初始化播放器，但不加载模型（懒加载）。
        
        Returns:
            是否初始化成功
        """
        if self._state == SynthesizerState.READY:
            return True
        
        self._set_state(SynthesizerState.INITIALIZING)
        
        try:
            voices = self._voice_manager.scan_voices()
            logger.info(f"发现 {len(voices)} 个音色")
            
            if not self._audio_player.initialize():
                logger.error("音频播放器初始化失败")
                self._set_state(SynthesizerState.ERROR)
                return False
            
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="TTS-Synthesizer",
                daemon=True
            )
            self._worker_thread.start()
            
            self._set_state(SynthesizerState.READY)
            self._enabled = True
            
            logger.info("TTS合成器初始化成功")
            return True
            
        except Exception as e:
            logger.exception(f"TTS合成器初始化失败: {e}")
            self._set_state(SynthesizerState.ERROR)
            self._report_error(f"初始化失败: {e}")
            return False
    
    def enable(self) -> bool:
        """
        启用TTS功能
        
        Returns:
            是否启用成功
        """
        if self._enabled:
            return True
        
        if self._state != SynthesizerState.READY:
            if not self.initialize():
                return False
        
        self._enabled = True
        logger.info("TTS已启用")
        return True
    
    def disable(self):
        """禁用TTS功能"""
        self._enabled = False
        self.stop()
        logger.info("TTS已禁用")
    
    def load_voice(self, voice_name: Optional[str] = None) -> bool:
        """
        加载指定音色
        
        Args:
            voice_name: 音色名称，为None则加载默认音色
            
        Returns:
            是否加载成功
        """
        if voice_name is None:
            voice = self._voice_manager.get_default_voice()
            if voice is None:
                voices = self._voice_manager.get_voice_names()
                if not voices:
                    logger.warning("没有可用音色")
                    return False
                voice_name = voices[0]
                voice = self._voice_manager.get_voice(voice_name)
        else:
            voice = self._voice_manager.get_voice(voice_name)
        
        if voice is None:
            logger.error(f"音色不存在: {voice_name}")
            return False
        
        if self._current_voice == voice.name and self._engine.is_loaded:
            logger.debug(f"音色已加载: {voice.name}")
            return True
        
        success = self._engine.load_model(voice.model_path, voice.config_path)
        if success:
            self._current_voice = voice.name
            logger.info(f"音色加载成功: {voice.display_name}")
        else:
            self._report_error(f"音色加载失败: {voice.name}")
        
        return success
    
    def speak(self, text: str, callback: Optional[Callable[[], None]] = None,
              priority: int = 0) -> bool:
        """
        朗读文本
        
        Args:
            text: 要朗读的文本
            callback: 完成回调
            priority: 优先级（数值越大越优先）
            
        Returns:
            是否成功加入队列
        """
        if not self._enabled:
            logger.debug("TTS未启用，跳过朗读")
            return False
        
        clean_text = self._clean_text(text)
        if not clean_text:
            return False
        
        task = SynthesizeTask(
            text=clean_text,
            callback=callback,
            priority=priority
        )
        
        self._task_queue.put(task)
        return True
    
    def speak_immediately(self, text: str, callback: Optional[Callable[[], None]] = None) -> bool:
        """
        立即朗读文本（停止当前播放）
        
        Args:
            text: 要朗读的文本
            callback: 完成回调
            
        Returns:
            是否成功
        """
        self.stop()
        return self.speak(text, callback, priority=10)
    
    def stop(self):
        """停止当前播放并清空队列"""
        self._audio_player.stop()
        self._clear_queue()
        logger.debug("TTS已停止")
    
    def stop_current(self):
        """仅停止当前播放"""
        self._audio_player.stop_current()
    
    def _clear_queue(self):
        """清空任务队列"""
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
            except queue.Empty:
                break
    
    def _clean_text(self, text: str) -> str:
        """清理文本，移除不适合朗读的内容"""
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`[^`]+`', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'[*_~]+', '', text)
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'\n+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        if len(text) > 1000:
            text = text[:1000] + "..."
        
        return text
    
    def _worker_loop(self):
        """工作线程主循环"""
        while True:
            task = self._task_queue.get()
            
            if task is None:
                break
            
            if not self._enabled:
                continue
            
            try:
                self._set_state(SynthesizerState.SYNTHESIZING)
                
                if not self._engine.is_loaded:
                    if not self.load_voice():
                        logger.error("无法加载音色，跳过朗读")
                        self._set_state(SynthesizerState.ERROR)
                        continue
                
                result = self._engine.synthesize(task.text, self._options.speed)
                
                if result is None:
                    logger.warning(f"合成失败: {task.text[:50]}...")
                    continue
                
                audio_data, sample_rate = result
                
                self._set_state(SynthesizerState.PLAYING)
                
                self._audio_player.queue_text_audio(
                    audio_data=audio_data,
                    sample_rate=sample_rate,
                    text=task.text,
                    callback=task.callback
                )
                
                self._set_state(SynthesizerState.READY)
                
            except Exception as e:
                logger.exception(f"合成任务执行失败: {e}")
                self._set_state(SynthesizerState.ERROR)
                self._report_error(f"合成失败: {e}")
    
    def _set_state(self, state: SynthesizerState):
        """设置状态并触发回调"""
        with self._lock:
            self._state = state
        
        if self._on_state_change:
            try:
                self._on_state_change(state)
            except Exception as e:
                logger.warning(f"状态回调执行失败: {e}")
    
    def _report_error(self, message: str):
        """报告错误"""
        logger.error(message)
        if self._on_error:
            try:
                self._on_error(message)
            except Exception as e:
                logger.warning(f"错误回调执行失败: {e}")
    
    def release(self):
        """释放所有资源"""
        self._enabled = False
        self.stop()
        
        self._task_queue.put(None)
        
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        
        self._engine.release()
        self._audio_player.release()
        
        self._set_state(SynthesizerState.IDLE)
        logger.info("TTS合成器资源已释放")
    
    def synthesize_to_file(self, text: str, output_path: Path, 
                          voice_name: Optional[str] = None) -> bool:
        """
        合成语音并保存到文件
        
        Args:
            text: 要合成的文本
            output_path: 输出文件路径（.wav）
            voice_name: 音色名称
            
        Returns:
            是否成功
        """
        if voice_name and voice_name != self._current_voice:
            if not self.load_voice(voice_name):
                return False
        
        if not self._engine.is_loaded:
            if not self.load_voice():
                return False
        
        clean_text = self._clean_text(text)
        if not clean_text:
            return False
        
        return self._engine.synthesize_to_file(clean_text, output_path, self._options.speed)
    
    def __del__(self):
        """析构时释放资源"""
        try:
            self.release()
        except Exception:
            pass