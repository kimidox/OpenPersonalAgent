from __future__ import annotations

import os
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List

from logger import get_module_logger
from resource_path import paths
import config

logger = get_module_logger("recorder")

_whisper_model = None
_model_download_progress = 0
_current_model_size = None
_original_hf_endpoint = None


def get_models_dir() -> Path:
    """获取模型存储目录"""
    models_dir = paths.personal_data_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def get_available_model_sizes() -> List[str]:
    """获取可用的模型大小列表"""
    return ["tiny", "base", "small", "medium", "large"]


def get_model_info(model_size: str) -> dict:
    """获取模型信息"""
    model_infos = {
        "tiny": {"name": "Tiny", "size_mb": 75, "description": "最小模型，速度最快"},
        "base": {"name": "Base", "size_mb": 150, "description": "基础模型，推荐日常使用"},
        "small": {"name": "Small", "size_mb": 500, "description": "小型模型，准确度较好"},
        "medium": {"name": "Medium", "size_mb": 1500, "description": "中型模型，准确度高"},
        "large": {"name": "Large", "size_mb": 3000, "description": "大型模型，准确度最高"},
    }
    return model_infos.get(model_size, {"name": model_size, "size_mb": 0, "description": "未知模型"})


def download_whisper_model(model_size: str = None, callback: Callable[[int, str], None] = None) -> bool:
    """
    预下载 Whisper 模型到 PersonalData/models
    
    Args:
        model_size: 模型大小，默认使用配置中的值
        callback: 进度回调函数 (progress: int, status: str)
    
    Returns:
        是否下载成功
    """
    try:
        from faster_whisper import utils
        import os
        
        # 设置 Hugging Face 镜像站，避免从 huggingface.co 直接下载
        # 使用 hf-mirror.com 作为镜像站
        original_hf_endpoint = os.environ.get('HF_ENDPOINT')
        os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
        
        if model_size is None:
            model_size = getattr(config, 'WHISPER_MODEL_SIZE', 'base')
        
        models_dir = get_models_dir()
        model_output_dir = models_dir / model_size
        model_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"开始下载 Whisper 模型: {model_size} 到 {model_output_dir}")
        logger.info(f"使用镜像站: {os.environ['HF_ENDPOINT']}")
        
        if callback:
            callback(10, f"正在下载模型 {model_size}...")
        
        # 使用 faster_whisper.utils.download_model 下载模型
        utils.download_model(
            model_size,
            output_dir=str(model_output_dir)
        )
        
        if callback:
            callback(100, "模型下载完成")
        
        logger.info(f"Whisper 模型 {model_size} 下载完成")
        
        # 恢复原始的 HF_ENDPOINT 环境变量
        if original_hf_endpoint is not None:
            os.environ['HF_ENDPOINT'] = original_hf_endpoint
        elif 'HF_ENDPOINT' in os.environ:
            del os.environ['HF_ENDPOINT']
        
        return True
        
    except ImportError:
        logger.error("faster-whisper 库未安装")
        if callback:
            callback(0, "错误: faster-whisper 未安装")
        # 恢复原始的 HF_ENDPOINT 环境变量
        if 'original_hf_endpoint' in locals():
            if original_hf_endpoint is not None:
                os.environ['HF_ENDPOINT'] = original_hf_endpoint
            elif 'HF_ENDPOINT' in os.environ:
                del os.environ['HF_ENDPOINT']
        return False
    except Exception as e:
        logger.exception(f"下载 Whisper 模型失败: {e}")
        if callback:
            callback(0, f"下载失败: {e}")
        # 恢复原始的 HF_ENDPOINT 环境变量
        if 'original_hf_endpoint' in locals():
            if original_hf_endpoint is not None:
                os.environ['HF_ENDPOINT'] = original_hf_endpoint
            elif 'HF_ENDPOINT' in os.environ:
                del os.environ['HF_ENDPOINT']
        return False


def is_model_downloaded(model_size: str = None) -> bool:
    """
    检查模型是否已下载
    
    Args:
        model_size: 模型大小
    
    Returns:
        是否已下载
    """
    try:
        if model_size is None:
            model_size = getattr(config, 'WHISPER_MODEL_SIZE', 'base')
        
        models_dir = get_models_dir()
        model_path = models_dir / model_size
        
        # 检查是否有必要的模型文件
        if model_path.exists() and model_path.is_dir():
            # 检查是否有 config.json 和 model.bin 文件
            if (model_path / "config.json").exists() and (
                (model_path / "model.bin").exists() or
                (model_path / "model.safetensors").exists()
            ):
                return True
        
        # 同时也检查旧的缓存结构
        model_folder_name = f"models--Systran--faster-whisper-{model_size}"
        old_model_path = models_dir / model_folder_name
        
        if old_model_path.exists():
            snapshots_dir = old_model_path / "snapshots"
            if snapshots_dir.exists():
                for snapshot in snapshots_dir.iterdir():
                    if snapshot.is_dir():
                        return True
        
        return False
    except Exception:
        return False


def get_downloaded_models() -> List[str]:
    """获取已下载的模型列表"""
    downloaded = []
    try:
        models_dir = get_models_dir()
        for model_size in get_available_model_sizes():
            if is_model_downloaded(model_size):
                downloaded.append(model_size)
    except Exception:
        pass
    return downloaded


def set_active_model(model_size: str) -> bool:
    """
    设置当前使用的模型
    
    Args:
        model_size: 模型大小
    
    Returns:
        是否设置成功
    """
    global _whisper_model, _current_model_size
    
    if not is_model_downloaded(model_size):
        return False
    
    try:
        from config import set_config
        set_config("WHISPER_MODEL_SIZE", model_size)
        
        _whisper_model = None
        _current_model_size = model_size
        
        logger.info(f"已切换到模型: {model_size}")
        return True
    except Exception as e:
        logger.exception(f"设置模型失败: {e}")
        return False


def _get_whisper_model():
    """获取或初始化 Whisper 模型（懒加载）"""
    global _whisper_model, _current_model_size, _original_hf_endpoint
    if _whisper_model is None:
        # 尝试导入 faster_whisper，添加详细日志
        logger.info("开始导入 faster_whisper 模块...")
        try:
            import faster_whisper
            logger.info(f"faster_whisper 模块路径: {faster_whisper.__file__}")
            logger.info(f"faster_whisper 版本: {getattr(faster_whisper, '__version__', '未知')}")
            from faster_whisper import WhisperModel
            import os
            
            # 设置 Hugging Face 镜像站，保存原始值到全局变量
            _original_hf_endpoint = os.environ.get('HF_ENDPOINT')
            os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
            
            model_size = getattr(config, 'WHISPER_MODEL_SIZE', 'base')
            device = getattr(config, 'WHISPER_DEVICE', 'cpu')
            compute_type = getattr(config, 'WHISPER_COMPUTE_TYPE', 'int8')
            models_dir = get_models_dir()
            
            logger.info(f"加载 Whisper 模型: {model_size}, device={device}, compute_type={compute_type}")
            logger.info(f"使用镜像站: {os.environ['HF_ENDPOINT']}")
            
            # 首先检查模型是否已下载到指定目录
            model_path = models_dir / model_size
            if model_path.exists() and model_path.is_dir():
                # 使用已下载的模型路径
                logger.info(f"使用本地已下载的模型: {model_path}")
                _whisper_model = WhisperModel(
                    str(model_path),
                    device=device,
                    compute_type=compute_type
                )
            else:
                # 使用默认缓存机制下载
                logger.info(f"使用模型大小名称加载: {model_size}")
                _whisper_model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute_type,
                    download_root=str(models_dir)
                )
            
            _current_model_size = model_size
            logger.info("Whisper 模型加载完成")
        except ImportError as ie:
            logger.error(f"faster-whisper 库导入失败: {ie}")
            logger.error(f"导入错误详情: {type(ie).__name__}")
            # 尝试获取更多信息
            import sys
            logger.error(f"Python 路径: {sys.path}")
            try:
                import importlib.util
                spec = importlib.util.find_spec('faster_whisper')
                logger.error(f"faster_whisper spec: {spec}")
            except Exception as e:
                logger.error(f"查找 faster_whisper spec 失败: {e}")
            # 恢复原始的 HF_ENDPOINT 环境变量
            import os
            if _original_hf_endpoint is not None:
                os.environ['HF_ENDPOINT'] = _original_hf_endpoint
            elif 'HF_ENDPOINT' in os.environ:
                del os.environ['HF_ENDPOINT']
            return None
        except Exception as e:
            logger.exception(f"加载 Whisper 模型失败: {e}")
            # 恢复原始的 HF_ENDPOINT 环境变量
            import os
            if _original_hf_endpoint is not None:
                os.environ['HF_ENDPOINT'] = _original_hf_endpoint
            elif 'HF_ENDPOINT' in os.environ:
                del os.environ['HF_ENDPOINT']
            return None
    return _whisper_model


class AudioRecorder:
    """
    音频录音管理器
    
    功能：
    1. 使用sounddevice进行录音
    2. 保存为WAV格式到PersonalData/records目录
    3. 使用OpenAI兼容API进行语音转文本
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
        
        # 在开始录音时预加载模型
        def _preload_model():
            try:
                logger.info("开始预加载Whisper模型...")
                _get_whisper_model()
                logger.info("Whisper模型预加载完成")
            except Exception as e:
                logger.exception(f"预加载Whisper模型时发生错误: {e}")
        
        # 异步加载模型，不阻塞录音
        preload_thread = threading.Thread(target=_preload_model, daemon=True)
        preload_thread.start()
        
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
            
            # 注意：这里不立即释放模型，因为可能紧接着会调用 transcribe_audio
            # 模型会在 transcribe_audio 之后释放，或者通过显式调用 release_whisper_model 释放
            
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
        """将音频文件转换为文本（使用本地 Whisper 模型）
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            转换后的文本，如果失败则返回None
        """
        if not audio_path.exists():
            logger.error(f"音频文件不存在: {audio_path}")
            return None
        
        model = _get_whisper_model()
        if model is None:
            logger.error("Whisper 模型未加载，无法进行语音识别")
            return None
        
        try:
            language = getattr(config, 'RECORDING_TRANSCRIPTION_LANGUAGE', 'zh')
            
            segments, info = model.transcribe(
                str(audio_path),
                language=language,
                beam_size=5
            )
            
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text)
            
            text = "".join(text_parts).strip()
            logger.info(f"音频转文本成功，长度: {len(text)}, 检测语言: {info.language}")
            
            return text
            
        except Exception as e:
            logger.exception(f"音频转文本时发生错误: {e}")
            return None
    
    def get_current_audio_path(self) -> Optional[Path]:
        return self._current_audio_path


_recorder_instance: Optional[AudioRecorder] = None


def release_whisper_model():
    """释放已加载的Whisper模型以节省内存"""
    global _whisper_model, _current_model_size, _original_hf_endpoint
    
    if _whisper_model is not None:
        logger.info("释放Whisper模型...")
        try:
            # 尝试清理模型资源
            if hasattr(_whisper_model, 'model'):
                del _whisper_model.model
            del _whisper_model
        except Exception as e:
            logger.warning(f"清理模型资源时发生错误: {e}")
        
        _whisper_model = None
        _current_model_size = None
        
        # 恢复原始的HF_ENDPOINT环境变量
        if _original_hf_endpoint is not None:
            import os
            os.environ['HF_ENDPOINT'] = _original_hf_endpoint
        elif 'HF_ENDPOINT' in os.environ:
            del os.environ['HF_ENDPOINT']
        _original_hf_endpoint = None
        
        logger.info("Whisper模型已释放")


def get_recorder() -> AudioRecorder:
    """获取录音器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = AudioRecorder()
    return _recorder_instance