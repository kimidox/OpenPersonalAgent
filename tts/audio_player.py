"""
音频播放器 - 使用sounddevice播放音频

支持队列播放、停止当前播放、音量和语速控制。
"""
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable
import threading
import queue
import wave
import numpy as np

from logger import get_module_logger

logger = get_module_logger("audio_player")


@dataclass
class AudioTask:
    """音频播放任务"""
    audio_data: np.ndarray
    sample_rate: int
    text: str = ""
    callback: Optional[Callable[[], None]] = None


class AudioPlayer:
    """
    音频播放器
    
    使用sounddevice播放音频，支持队列播放和停止控制。
    """
    
    def __init__(self):
        self._play_queue: queue.Queue[Optional[AudioTask]] = queue.Queue()
        self._play_thread: Optional[threading.Thread] = None
        self._is_playing = False
        self._stop_flag = threading.Event()
        self._current_stream = None
        self._lock = threading.Lock()
        self._volume = 1.0
        self._is_initialized = False
    
    @property
    def is_playing(self) -> bool:
        """是否正在播放"""
        return self._is_playing
    
    @property
    def volume(self) -> float:
        """当前音量"""
        return self._volume
    
    def set_volume(self, volume: float):
        """设置音量 (0.0 - 1.0)"""
        self._volume = max(0.0, min(1.0, volume))
    
    def initialize(self) -> bool:
        """
        初始化播放器
        
        Returns:
            是否初始化成功
        """
        if self._is_initialized:
            return True
        
        try:
            import sounddevice as sd
            
            default_device = sd.query_devices(kind='output')
            logger.info(f"默认音频设备: {default_device['name']}")
            
            self._play_thread = threading.Thread(
                target=self._play_loop,
                name="TTS-AudioPlayer",
                daemon=True
            )
            self._play_thread.start()
            
            self._is_initialized = True
            logger.info("音频播放器初始化成功")
            return True
            
        except ImportError:
            logger.error("sounddevice库未安装，请运行: pip install sounddevice")
            return False
        except Exception as e:
            logger.exception(f"音频播放器初始化失败: {e}")
            return False
    
    def play(self, audio_data: np.ndarray, sample_rate: int, 
             callback: Optional[Callable[[], None]] = None) -> bool:
        """
        播放音频数据
        
        Args:
            audio_data: 音频数据（numpy数组）
            sample_rate: 采样率
            callback: 播放完成回调
            
        Returns:
            是否成功加入播放队列
        """
        if not self._is_initialized:
            if not self.initialize():
                return False
        
        task = AudioTask(
            audio_data=audio_data.copy(),
            sample_rate=sample_rate,
            callback=callback
        )
        
        self._play_queue.put(task)
        return True
    
    def play_file(self, file_path: Path, callback: Optional[Callable[[], None]] = None) -> bool:
        """
        播放音频文件
        
        Args:
            file_path: 音频文件路径（.wav）
            callback: 播放完成回调
            
        Returns:
            是否成功
        """
        if not file_path.exists():
            logger.error(f"音频文件不存在: {file_path}")
            return False
        
        try:
            with wave.open(str(file_path), 'rb') as wav_file:
                sample_rate = wav_file.getframerate()
                num_channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                
                frames = wav_file.readframes(wav_file.getnframes())
                
                if sample_width == 2:
                    audio_data = np.frombuffer(frames, dtype=np.int16)
                    audio_data = audio_data.astype(np.float32) / 32768.0
                elif sample_width == 1:
                    audio_data = np.frombuffer(frames, dtype=np.uint8)
                    audio_data = (audio_data.astype(np.float32) - 128) / 128.0
                else:
                    logger.error(f"不支持的采样宽度: {sample_width}")
                    return False
                
                if num_channels > 1:
                    audio_data = audio_data.reshape(-1, num_channels)
                    audio_data = np.mean(audio_data, axis=1)
                
                return self.play(audio_data, sample_rate, callback)
                
        except Exception as e:
            logger.exception(f"读取音频文件失败: {e}")
            return False
    
    def queue_text_audio(self, audio_data: np.ndarray, sample_rate: int, text: str,
                         callback: Optional[Callable[[], None]] = None) -> bool:
        """
        将文本对应的音频加入播放队列
        
        Args:
            audio_data: 音频数据
            sample_rate: 采样率
            text: 对应的文本（用于日志）
            callback: 播放完成回调
            
        Returns:
            是否成功加入队列
        """
        if not self._is_initialized:
            if not self.initialize():
                return False
        
        task = AudioTask(
            audio_data=audio_data.copy(),
            sample_rate=sample_rate,
            text=text,
            callback=callback
        )
        
        self._play_queue.put(task)
        logger.debug(f"音频已加入队列: {text[:30]}...")
        return True
    
    def stop(self):
        """停止当前播放并清空队列"""
        self._stop_flag.set()
        
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break
        
        with self._lock:
            if self._current_stream is not None:
                try:
                    self._current_stream.stop()
                    self._current_stream.close()
                except Exception:
                    pass
                self._current_stream = None
        
        self._stop_flag.clear()
        logger.debug("播放已停止")
    
    def stop_current(self):
        """仅停止当前播放，不清空队列"""
        self._stop_flag.set()
        
        with self._lock:
            if self._current_stream is not None:
                try:
                    self._current_stream.stop()
                    self._current_stream.close()
                except Exception:
                    pass
                self._current_stream = None
        
        self._stop_flag.clear()
    
    def clear_queue(self):
        """清空播放队列"""
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
            except queue.Empty:
                break
        logger.debug("播放队列已清空")
    
    def _play_loop(self):
        """播放线程主循环"""
        import sounddevice as sd
        
        while True:
            task = self._play_queue.get()
            
            if task is None:
                break
            
            if self._stop_flag.is_set():
                continue
            
            self._is_playing = True
            
            try:
                audio_data = task.audio_data
                
                if self._volume != 1.0:
                    audio_data = audio_data * self._volume
                    audio_data = np.clip(audio_data, -1.0, 1.0)
                
                if task.text:
                    logger.debug(f"正在播放: {task.text[:50]}...")
                
                with self._lock:
                    if self._stop_flag.is_set():
                        self._is_playing = False
                        continue
                    
                    self._current_stream = sd.OutputStream(
                        samplerate=task.sample_rate,
                        channels=1,
                        dtype='float32'
                    )
                    self._current_stream.start()
                    self._current_stream.write(audio_data)
                    self._current_stream.stop()
                    self._current_stream.close()
                    self._current_stream = None
                
                if task.callback:
                    try:
                        task.callback()
                    except Exception as e:
                        logger.warning(f"播放回调执行失败: {e}")
                
            except Exception as e:
                logger.exception(f"播放音频失败: {e}")
            
            finally:
                self._is_playing = False
    
    def release(self):
        """释放播放器资源"""
        self.stop()
        self._play_queue.put(None)
        
        if self._play_thread is not None and self._play_thread.is_alive():
            self._play_thread.join(timeout=2.0)
        
        self._is_initialized = False
        logger.info("音频播放器资源已释放")
    
    def __del__(self):
        """析构时释放资源"""
        try:
            self.release()
        except Exception:
            pass