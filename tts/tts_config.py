"""
TTS配置管理模块

封装TTS配置的读写操作，提供统一的配置访问接口。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from logger import get_module_logger

logger = get_module_logger("tts_config")


@dataclass
class TTSConfigData:
    """TTS配置数据类"""
    enabled: bool = False
    voice_model: str = ""
    voice_dir: str = ""
    speed: float = 1.0
    volume: float = 1.0
    auto_read: bool = True


class TTSConfigManager:
    """
    TTS配置管理类
    
    负责从config.py读取配置和保存配置到.env文件。
    """
    
    _instance: Optional["TTSConfigManager"] = None
    _config: Optional[TTSConfigData] = None
    
    def __new__(cls) -> "TTSConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @property
    def config(self) -> TTSConfigData:
        """获取当前配置（懒加载）"""
        if self._config is None:
            self._config = self.load_config()
        return self._config
    
    def load_config(self) -> TTSConfigData:
        """
        从config.py加载配置
        
        Returns:
            TTSConfigData实例
        """
        import config as app_config
        
        config_data = TTSConfigData(
            enabled=app_config.TTS_ENABLED,
            voice_model=app_config.TTS_VOICE_MODEL or "",
            voice_dir=app_config.TTS_VOICE_DIR or "",
            speed=app_config.TTS_SPEED,
            volume=app_config.TTS_VOLUME,
            auto_read=app_config.TTS_AUTO_READ,
        )
        
        logger.debug(f"加载TTS配置: enabled={config_data.enabled}, voice_model={config_data.voice_model}")
        return config_data
    
    def reload_config(self) -> TTSConfigData:
        """
        重新加载配置
        
        Returns:
            重新加载后的TTSConfigData实例
        """
        self._config = None
        return self.config
    
    def save_config(self, config_data: Optional[TTSConfigData] = None) -> bool:
        """
        保存配置到.env文件
        
        Args:
            config_data: 要保存的配置，如果为None则保存当前配置
            
        Returns:
            是否保存成功
        """
        if config_data is None:
            config_data = self.config
        
        try:
            import config as app_config
            
            app_config.set_config("TTS_ENABLED", "true" if config_data.enabled else "false")
            app_config.set_config("TTS_VOICE_MODEL", config_data.voice_model)
            app_config.set_config("TTS_VOICE_DIR", config_data.voice_dir)
            app_config.set_config("TTS_SPEED", str(config_data.speed))
            app_config.set_config("TTS_VOLUME", str(config_data.volume))
            app_config.set_config("TTS_AUTO_READ", "true" if config_data.auto_read else "false")
            
            self._config = config_data
            
            logger.info("TTS配置已保存到.env文件")
            return True
            
        except Exception as e:
            logger.exception(f"保存TTS配置失败: {e}")
            return False
    
    def update_config(
        self,
        enabled: Optional[bool] = None,
        voice_model: Optional[str] = None,
        voice_dir: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        auto_read: Optional[bool] = None,
    ) -> TTSConfigData:
        """
        更新配置并保存
        
        Args:
            enabled: 是否启用TTS
            voice_model: 音色模型名称
            voice_dir: 音色目录路径
            speed: 语速 (0.5-2.0)
            volume: 音量 (0.0-1.0)
            auto_read: 是否自动朗读
            
        Returns:
            更新后的配置
        """
        config_data = self.config
        
        if enabled is not None:
            config_data.enabled = enabled
        if voice_model is not None:
            config_data.voice_model = voice_model
        if voice_dir is not None:
            config_data.voice_dir = voice_dir
        if speed is not None:
            config_data.speed = max(0.5, min(2.0, speed))
        if volume is not None:
            config_data.volume = max(0.0, min(1.0, volume))
        if auto_read is not None:
            config_data.auto_read = auto_read
        
        self.save_config(config_data)
        return config_data
    
    @property
    def enabled(self) -> bool:
        """是否启用TTS"""
        return self.config.enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        self.update_config(enabled=value)
    
    @property
    def voice_model(self) -> str:
        """默认音色模型名称"""
        return self.config.voice_model
    
    @voice_model.setter
    def voice_model(self, value: str):
        self.update_config(voice_model=value)
    
    @property
    def voice_dir(self) -> Path:
        """音色权重目录路径"""
        return Path(self.config.voice_dir) if self.config.voice_dir else Path("")
    
    @voice_dir.setter
    def voice_dir(self, value: str | Path):
        self.update_config(voice_dir=str(value))
    
    @property
    def speed(self) -> float:
        """语速"""
        return self.config.speed
    
    @speed.setter
    def speed(self, value: float):
        self.update_config(speed=value)
    
    @property
    def volume(self) -> float:
        """音量"""
        return self.config.volume
    
    @volume.setter
    def volume(self, value: float):
        self.update_config(volume=value)
    
    @property
    def auto_read(self) -> bool:
        """是否自动朗读AI回复"""
        return self.config.auto_read
    
    @auto_read.setter
    def auto_read(self, value: bool):
        self.update_config(auto_read=value)


def get_tts_config() -> TTSConfigManager:
    """
    获取TTS配置管理器实例
    
    Returns:
        TTSConfigManager单例
    """
    return TTSConfigManager()