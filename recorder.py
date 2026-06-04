from __future__ import annotations

import os
import shutil
import tarfile
import threading
import urllib.request
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from logger import get_module_logger
from resource_path import paths
import config

logger = get_module_logger("recorder")

# 全局 sherpa-onnx 模型实例
_onnx_recognizer = None
_onnx_model_path = None

# 默认模型下载配置
DEFAULT_MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2"
DEFAULT_MODEL_NAME = "sherpa-onnx-paraformer-zh-int8-2025-10-07"


def get_default_model_dir() -> Path:
    """获取默认模型目录路径"""
    model_dir = paths.personal_data_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def download_onnx_model(callback: Callable[[int, str], None] = None) -> Optional[Path]:
    """
    自动下载 ONNX INT8 模型到 PersonalData/model 目录
    
    Args:
        callback: 进度回调函数 (progress: int, status: str)
    
    Returns:
        模型目录路径，如果失败则返回 None
    """
    model_dir = get_default_model_dir()
    target_dir = model_dir / DEFAULT_MODEL_NAME
    
    # 如果模型已存在，直接返回
    if target_dir.exists():
        # 检查是否有必要的模型文件
        onnx_files = list(target_dir.glob("*.onnx"))
        if onnx_files:
            logger.info(f"模型已存在: {target_dir}")
            return target_dir
    
    if callback:
        callback(5, "正在准备下载模型...")
    
    logger.info(f"开始下载 ONNX INT8 模型到: {model_dir}")
    
    try:
        # 下载压缩包
        tar_path = model_dir / f"{DEFAULT_MODEL_NAME}.tar.bz2"
        
        if callback:
            callback(10, "正在下载模型文件（约 80MB）...")
        
        def download_progress(block_num, block_size, total_size):
            if total_size > 0:
                progress = int(10 + (block_num * block_size / total_size) * 50)
                if callback and progress <= 60:
                    callback(progress, f"正在下载模型文件（约 80MB）...")
        
        urllib.request.urlretrieve(DEFAULT_MODEL_URL, tar_path, download_progress)
        
        if callback:
            callback(65, "正在解压模型文件...")
        
        # 解压
        with tarfile.open(tar_path, 'r:bz2') as tar:
            tar.extractall(model_dir)
        
        # 删除压缩包
        tar_path.unlink()
        
        if callback:
            callback(95, "模型下载完成")
        
        logger.info(f"模型下载并解压完成: {target_dir}")
        return target_dir
        
    except Exception as e:
        logger.exception(f"下载模型失败: {e}")
        if callback:
            callback(0, f"下载失败: {e}")
        return None


def load_onnx_model(model_path: str = None, callback: Callable[[int, str], None] = None, auto_download: bool = True) -> bool:
    """
    加载 sherpa-onnx ONNX 模型
    
    Args:
        model_path: ONNX 模型目录路径，默认使用配置中的值或自动下载
        callback: 进度回调函数 (progress: int, status: str)
        auto_download: 是否在模型不存在时自动下载
    
    Returns:
        是否加载成功
    """
    global _onnx_recognizer, _onnx_model_path
    
    # 如果没有指定路径，尝试使用配置或默认目录
    if model_path is None:
        model_path = getattr(config, 'ASR_ONNX_MODEL_PATH', '')
        
        # 如果配置中没有路径，使用默认目录
        if not model_path and auto_download:
            default_dir = get_default_model_dir() / DEFAULT_MODEL_NAME
            if default_dir.exists():
                model_path = str(default_dir)
            else:
                # 自动下载模型
                if callback:
                    callback(0, "模型未找到，正在自动下载...")
                downloaded_path = download_onnx_model(callback)
                if downloaded_path:
                    model_path = str(downloaded_path)
                    # 保存到配置
                    config.set_config("ASR_ONNX_MODEL_PATH", model_path)
                    config.ASR_ONNX_MODEL_PATH = model_path
                else:
                    return False
    
    if not model_path:
        if callback:
            callback(0, "错误: 未配置模型路径")
        logger.error("ONNX 模型路径未配置")
        return False
    
    model_path = Path(model_path)
    
    # 如果模型目录不存在，尝试自动下载
    if not model_path.exists() and auto_download:
        if callback:
            callback(0, "模型目录不存在，正在自动下载...")
        downloaded_path = download_onnx_model(callback)
        if downloaded_path:
            model_path = downloaded_path
        else:
            return False
    
    if not model_path.exists():
        if callback:
            callback(0, f"错误: 模型目录不存在: {model_path}")
        logger.error(f"ONNX 模型目录不存在: {model_path}")
        return False
    
    if callback:
        callback(70, "正在初始化 sherpa-onnx...")
    
    try:
        import sherpa_onnx
        
        if callback:
            callback(80, "正在加载 ONNX 模型...")
        
        # 查找模型文件
        model_dir = Path(model_path)
        
        # 查找 ONNX 模型文件
        onnx_files = list(model_dir.glob("*.onnx"))
        if not onnx_files:
            if callback:
                callback(0, f"错误: 未找到 ONNX 模型文件")
            logger.error(f"未找到 ONNX 模型文件: {model_dir}")
            return False
        
        # 使用第一个 ONNX 文件（通常是 model.int8.onnx 或 model.onnx）
        model_file = onnx_files[0]
        
        # 查找 tokens.txt 文件
        tokens_file = model_dir / "tokens.txt"
        if not tokens_file.exists():
            # 尝试其他可能的名称
            tokens_files = list(model_dir.glob("tokens*.txt"))
            if tokens_files:
                tokens_file = tokens_files[0]
            else:
                if callback:
                    callback(0, f"错误: 未找到 tokens.txt 文件")
                logger.error(f"未找到 tokens.txt 文件: {model_dir}")
                return False
        
        if callback:
            callback(90, "正在创建识别器...")
        
        # 创建 OfflineRecognizer
        # Paraformer ONNX INT8 模型配置
        _onnx_recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=str(model_file),
            tokens=str(tokens_file),
            num_threads=4,
            sample_rate=16000,
            decoding_method="greedy_search",
        )
        
        _onnx_model_path = str(model_path)
        
        if callback:
            callback(100, "模型加载完成")
        
        logger.info(f"sherpa-onnx 模型加载完成: {model_file}")
        return True
        
    except ImportError as ie:
        logger.error(f"sherpa-onnx 库导入失败: {ie}")
        if callback:
            callback(0, "错误: sherpa-onnx 未安装，请运行 pip install sherpa-onnx")
        return False
    except Exception as e:
        logger.exception(f"加载 sherpa-onnx 模型失败: {e}")
        if callback:
            callback(0, f"加载失败: {e}")
        return False


def release_onnx_model():
    """释放已加载的 sherpa-onnx 模型以节省内存"""
    global _onnx_recognizer, _onnx_model_path
    
    logger.info("释放 sherpa-onnx 模型...")
    
    if _onnx_recognizer is not None:
        try:
            del _onnx_recognizer
        except Exception as e:
            logger.warning(f"清理模型资源时发生错误: {e}")
        _onnx_recognizer = None
    
    _onnx_model_path = None
    logger.info("sherpa-onnx 模型已释放")


def is_onnx_model_loaded() -> bool:
    """
    检查 sherpa-onnx 模型是否已加载
    
    Returns:
        是否已加载
    """
    return _onnx_recognizer is not None


def get_onnx_model_path() -> Optional[str]:
    """
    获取已加载模型的路径
    
    Returns:
        模型路径，如果未加载则返回 None
    """
    return _onnx_model_path


def transcribe_audio_with_onnx(audio_path: Path) -> Optional[str]:
    """
    使用 sherpa-onnx 进行语音转文本
    
    Args:
        audio_path: 音频文件路径
        
    Returns:
        转换后的文本，如果失败则返回 None
    """
    if not audio_path.exists():
        logger.error(f"音频文件不存在: {audio_path}")
        return None
    
    if _onnx_recognizer is None:
        logger.error("sherpa-onnx 模型未加载")
        return None
    
    try:
        logger.info(f"使用 sherpa-onnx 进行语音识别: {audio_path}")
        
        # 创建音频流
        import sherpa_onnx
        
        # 读取 WAV 文件
        with wave.open(str(audio_path), 'rb') as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            num_frames = wf.getnframes()
            audio_data = wf.readframes(num_frames)
        
        # 转换为 numpy 数组
        import numpy as np
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # 如果是多声道，转换为单声道
        if num_channels > 1:
            audio_array = audio_array.reshape(-1, num_channels)
            audio_array = audio_array.mean(axis=1).astype(np.int16)
        
        # 重采样到 16kHz（如果需要）
        if sample_rate != 16000:
            import scipy.signal
            audio_array = scipy.signal.resample_poly(
                audio_array,
                16000,
                sample_rate
            ).astype(np.int16)
        
        # 创建音频流
        stream = _onnx_recognizer.create_stream()
        stream.accept_waveform(16000, audio_array)
        
        # 进行识别
        _onnx_recognizer.decode_stream(stream)
        
        # 获取结果
        result = stream.result.text
        
        if result:
            logger.info(f"语音识别成功，文本长度: {len(result)}")
            return result.strip()
        else:
            logger.warning("sherpa-onnx 返回空文本")
            return None
        
    except Exception as e:
        logger.exception(f"语音识别时发生错误: {e}")
        return None


class AudioRecorder:
    """
    音频录音管理器
    
    功能：
    1. 使用 sounddevice 进行录音
    2. 保存为 WAV 格式到 PersonalData/records 目录
    3. 使用 sherpa-onnx 进行语音转文本
    """
    
    def __init__(self):
        self._is_recording: bool = False
        self._recording_thread: Optional[threading.Thread] = None
        self._audio_frames: list = []
        self._sample_rate: int = 16000
        self._channels: int = 1
        self._dtype: str = 'int16'
        self._stop_event: threading.Event = threading.Event()
        self._current_audio_path: Optional[Path] = None
        
        self._ensure_records_dir()
        
    def _ensure_records_dir(self) -> Path:
        records_dir = paths.personal_data_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        return records_dir
    
    @property
    def is_recording(self) -> bool:
        return self._is_recording
    
    def start_recording(self, on_started: Optional[Callable[[], None]] = None) -> bool:
        """
        开始录音
        
        Args:
            on_started: 录音开始后的回调函数
            
        Returns:
            是否成功开始录音
        """
        if self._is_recording:
            logger.warning("录音已在进行中")
            return False
        
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice库未安装，无法录音")
            return False
        
        self._audio_frames = []
        self._stop_event.clear()
        self._is_recording = True
        
        def _record_audio():
            try:
                def callback(indata, frames, time, status):
                    if self._stop_event.is_set():
                        raise sd.CallbackStop()
                    self._audio_frames.append(indata.copy())
                
                with sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype=self._dtype,
                    callback=callback
                ):
                    while not self._stop_event.is_set():
                        sd.sleep(100)
                        
            except Exception as e:
                logger.exception(f"录音过程中发生错误: {e}")
                self._is_recording = False
        
        self._recording_thread = threading.Thread(
            target=_record_audio,
            name="audio-recording",
            daemon=True
        )
        self._recording_thread.start()
        
        if on_started:
            try:
                on_started()
            except Exception as e:
                logger.exception(f"执行录音开始回调时发生错误: {e}")
        
        logger.info("录音已开始")
        return True
    
    def stop_recording(self, on_stopped: Optional[Callable[[], None]] = None) -> Optional[Path]:
        """
        停止录音并保存音频文件
        
        Args:
            on_stopped: 录音停止后的回调函数
            
        Returns:
            保存的音频文件路径，如果失败则返回 None
        """
        if not self._is_recording:
            logger.warning("录音未在进行中")
            return None
        
        self._stop_event.set()
        self._is_recording = False
        
        if self._recording_thread:
            self._recording_thread.join(timeout=2.0)
            self._recording_thread = None
        
        if not self._audio_frames:
            logger.warning("没有录制到音频数据")
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            return None
        
        try:
            import numpy as np
            
            records_dir = self._ensure_records_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.wav"
            audio_path = records_dir / filename
            
            audio_data = np.concatenate(self._audio_frames, axis=0)
            
            with wave.open(str(audio_path), 'wb') as wf:
                wf.setnchannels(self._channels)
                wf.setsampwidth(2)
                wf.setframerate(self._sample_rate)
                wf.writeframes(audio_data.tobytes())
            
            self._current_audio_path = audio_path
            self._audio_frames = []
            
            logger.info(f"录音已保存到: {audio_path}")
            
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            
            return audio_path
            
        except Exception as e:
            logger.exception(f"保存音频文件时发生错误: {e}")
            self._audio_frames = []
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            return None
    
    def transcribe_audio(self, audio_path: Path) -> Optional[str]:
        """
        将音频文件转换为文本（使用 sherpa-onnx）
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            转换后的文本，如果失败则返回 None
        """
        return transcribe_audio_with_onnx(audio_path)
    
    def get_current_audio_path(self) -> Optional[Path]:
        return self._current_audio_path


_recorder_instance: Optional[AudioRecorder] = None


def get_recorder() -> AudioRecorder:
    """获取录音器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = AudioRecorder()
    return _recorder_instance