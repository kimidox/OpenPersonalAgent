"""
TTS引擎模块 - Sherpa-ONNX引擎封装

提供懒加载初始化、文本合成、资源释放等功能。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import threading

from logger import get_module_logger

logger = get_module_logger("tts_engine")


@dataclass
class TTSConfig:
    """TTS配置"""
    speed: float = 1.0
    volume: float = 1.0
    sample_rate: int = 22050


class TTSEngine:
    """
    Sherpa-ONNX TTS引擎封装类
    
    支持懒加载初始化，仅在首次启用时加载模型。
    """
    
    def __init__(self):
        self._tts = None
        self._is_loaded = False
        self._model_path: Optional[Path] = None
        self._config_path: Optional[Path] = None
        self._config = TTSConfig()
        self._lock = threading.Lock()
        self._provider = "cpu"
    
    @property
    def is_loaded(self) -> bool:
        """检查引擎是否已加载"""
        return self._is_loaded and self._tts is not None
    
    @property
    def config(self) -> TTSConfig:
        """获取当前配置"""
        return self._config
    
    def set_speed(self, speed: float):
        """设置语速 (0.5 - 2.0)"""
        self._config.speed = max(0.5, min(2.0, speed))
    
    def set_volume(self, volume: float):
        """设置音量 (0.0 - 1.0)"""
        self._config.volume = max(0.0, min(1.0, volume))
    
    def load_model(self, model_path: Path, config_path: Optional[Path] = None) -> bool:
        """
        加载ONNX模型
        
        Args:
            model_path: .onnx模型文件路径
            config_path: .json配置文件路径（可选，默认自动查找同名json文件）
            
        Returns:
            是否加载成功
        """
        with self._lock:
            if self._is_loaded:
                logger.info("TTS引擎已加载，先释放旧模型")
                self._release_internal()
            
            if not model_path.exists():
                logger.error(f"模型文件不存在: {model_path}")
                return False
            
            if config_path is None:
                config_path = model_path.with_suffix('.json')
            
            if not config_path.exists():
                logger.error(f"配置文件不存在: {config_path}")
                return False
            
            try:
                import sherpa_onnx
                
                model_dir = model_path.parent
                
                # 查找 tokens.txt 文件
                tokens_file = model_dir / "tokens.txt"
                if not tokens_file.exists():
                    # 如果没有 tokens.txt，再尝试其他可能
                    logger.warning(f"未找到 tokens.txt，尝试使用配置文件: {config_path}")
                    tokens_path = str(config_path)
                else:
                    tokens_path = str(tokens_file)
                    logger.info(f"使用 tokens 文件: {tokens_path}")
                
                # 新版 sherpa-onnx API: 需要先创建 OfflineTtsConfig
                tts_config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=str(model_path),
                            tokens=tokens_path,
                            data_dir=str(model_dir),
                        ),
                        num_threads=2,
                        debug=False,
                        provider=self._provider,
                    ),
                    max_num_sentences=1,
                )
                self._tts = sherpa_onnx.OfflineTts(config=tts_config)
                
                self._model_path = model_path
                self._config_path = config_path
                self._is_loaded = True
                
                if hasattr(self._tts, 'sample_rate'):
                    self._config.sample_rate = self._tts.sample_rate
                
                logger.info(f"TTS引擎加载成功: {model_path.name}")
                return True
                
            except ImportError:
                logger.error("sherpa_onnx库未安装，请运行: pip install sherpa-onnx")
                return False
            except Exception as e:
                logger.exception(f"TTS引擎加载失败: {e}")
                self._tts = None
                self._is_loaded = False
                return False
    
    def synthesize(self, text: str, speed: Optional[float] = None) -> Optional[tuple]:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            speed: 语速覆盖（可选）
            
        Returns:
            (audio_data, sample_rate) 元组，失败返回None
        """
        if not self._is_loaded or self._tts is None:
            logger.warning("TTS引擎未加载，无法合成")
            return None
        
        if not text or not text.strip():
            return None
        
        try:
            actual_speed = speed if speed is not None else self._config.speed
            
            audio = self._tts.generate(text, sid=0, speed=actual_speed)
            
            if audio is None or len(audio.samples) == 0:
                logger.warning(f"合成结果为空: {text[:50]}...")
                return None
            
            import numpy as np
            audio_data = np.array(audio.samples, dtype=np.float32)
            
            if self._config.volume != 1.0:
                audio_data = audio_data * self._config.volume
                audio_data = np.clip(audio_data, -1.0, 1.0)
            
            return (audio_data, self._config.sample_rate)
            
        except Exception as e:
            logger.exception(f"语音合成失败: {e}")
            return None
    
    def synthesize_to_file(self, text: str, output_path: Path, speed: Optional[float] = None) -> bool:
        """
        合成语音并保存到文件
        
        Args:
            text: 要合成的文本
            output_path: 输出文件路径（.wav）
            speed: 语速覆盖（可选）
            
        Returns:
            是否成功
        """
        result = self.synthesize(text, speed)
        if result is None:
            return False
        
        audio_data, sample_rate = result
        
        try:
            import wave
            import struct
            
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with wave.open(str(output_path), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                
                audio_int16 = (audio_data * 32767).astype(np.int16)
                wav_file.writeframes(audio_int16.tobytes())
            
            logger.debug(f"音频已保存: {output_path}")
            return True
            
        except Exception as e:
            logger.exception(f"保存音频文件失败: {e}")
            return False
    
    def release(self):
        """释放引擎资源（线程安全）"""
        with self._lock:
            self._release_internal()
    
    def _release_internal(self):
        """内部释放方法（需在锁内调用）"""
        if self._tts is not None:
            try:
                del self._tts
            except Exception:
                pass
            self._tts = None
        
        self._is_loaded = False
        self._model_path = None
        self._config_path = None
        logger.info("TTS引擎资源已释放")
    
    def __del__(self):
        """析构时释放资源"""
        self.release()