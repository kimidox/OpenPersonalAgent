"""
音色权重管理器 - 扫描和管理TTS音色模型

支持扫描音色目录，识别.onnx + .json模型文件配对。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict
import json

from resource_path import paths
from logger import get_module_logger

logger = get_module_logger("voice_manager")


@dataclass
class VoiceInfo:
    """音色信息"""
    name: str
    model_path: Path
    config_path: Path
    display_name: str = ""
    language: str = "zh"
    sample_rate: int = 22050
    description: str = ""
    metadata: Dict = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name
    
    def __str__(self) -> str:
        return f"VoiceInfo(name={self.name}, display={self.display_name})"
    
    def __repr__(self) -> str:
        return self.__str__()


class VoiceManager:
    """
    音色权重管理器
    
    负责扫描音色目录、识别模型文件、管理音色列表。
    """
    
    DEFAULT_VOICE_DIR_NAME = "voices"
    
    def __init__(self, voice_dir: Optional[Path] = None):
        """
        初始化音色管理器
        
        Args:
            voice_dir: 音色目录路径，默认为 PersonalData/voices/
        """
        if voice_dir is None:
            self._voice_dir = paths.personal_data_dir / self.DEFAULT_VOICE_DIR_NAME
        else:
            self._voice_dir = Path(voice_dir)
        
        self._voices: Dict[str, VoiceInfo] = {}
        self._default_voice: Optional[str] = None
    
    @property
    def voice_dir(self) -> Path:
        """获取音色目录路径"""
        return self._voice_dir
    
    @property
    def voices(self) -> Dict[str, VoiceInfo]:
        """获取所有音色"""
        return self._voices.copy()
    
    @property
    def default_voice(self) -> Optional[str]:
        """获取默认音色名称"""
        return self._default_voice
    
    def set_default_voice(self, voice_name: str) -> bool:
        """设置默认音色"""
        if voice_name in self._voices:
            self._default_voice = voice_name
            return True
        return False
    
    def scan_voices(self) -> List[VoiceInfo]:
        """
        扫描音色目录，识别所有可用音色
        
        Returns:
            发现的音色列表
        """
        self._voices.clear()
        self._default_voice = None
        
        if not self._voice_dir.exists():
            logger.info(f"音色目录不存在，将创建: {self._voice_dir}")
            self._voice_dir.mkdir(parents=True, exist_ok=True)
            return []
        
        found_voices = []
        
        for item in self._voice_dir.iterdir():
            if item.is_dir():
                voice = self._scan_voice_directory(item)
                if voice:
                    self._voices[voice.name] = voice
                    found_voices.append(voice)
            elif item.is_file() and item.suffix.lower() == '.onnx':
                voice = self._scan_voice_file(item)
                if voice:
                    self._voices[voice.name] = voice
                    found_voices.append(voice)
        
        if found_voices:
            self._default_voice = found_voices[0].name
            logger.info(f"扫描到 {len(found_voices)} 个音色")
        else:
            logger.info("未发现可用音色")
        
        return found_voices
    
    def _scan_voice_directory(self, dir_path: Path) -> Optional[VoiceInfo]:
        """
        扫描音色目录（一个目录包含一个音色的所有文件）
        
        目录结构示例：
        voices/
          └── zh-fanchen/
              ├── model.onnx
              ├── model.json
              └── info.json (可选元数据)
        """
        onnx_files = list(dir_path.glob("*.onnx"))
        if not onnx_files:
            return None
        
        for onnx_file in onnx_files:
            # 先尝试查找 <name>.json
            json_file = onnx_file.with_suffix('.json')
            if json_file.exists():
                voice = self._create_voice_info(onnx_file, json_file)
                if voice:
                    return voice
            
            # 如果找不到，再尝试查找 <name>.onnx.json
            json_file = dir_path / f"{onnx_file.name}.json"
            if json_file.exists():
                voice = self._create_voice_info(onnx_file, json_file)
                if voice:
                    return voice
        
        return None
    
    def _scan_voice_file(self, onnx_file: Path) -> Optional[VoiceInfo]:
        """
        扫描独立的音色文件（.onnx + .json 在同一目录）
        """
        # 先尝试查找 <name>.json
        json_file = onnx_file.with_suffix('.json')
        if json_file.exists():
            return self._create_voice_info(onnx_file, json_file)
        
        # 如果找不到，再尝试查找 <name>.onnx.json
        json_file = onnx_file.parent / f"{onnx_file.name}.json"
        if json_file.exists():
            return self._create_voice_info(onnx_file, json_file)
        
        logger.debug(f"跳过无配置文件的模型: {onnx_file.name}")
        return None
    
    def _create_voice_info(self, onnx_file: Path, json_file: Path) -> Optional[VoiceInfo]:
        """
        创建音色信息对象
        
        Args:
            onnx_file: ONNX模型文件路径
            json_file: JSON配置文件路径
            
        Returns:
            VoiceInfo对象或None
        """
        try:
            name = onnx_file.stem
            
            metadata = self._load_metadata(onnx_file.parent, name)
            
            with open(json_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            sample_rate = config.get('sample_rate', 22050)
            language = metadata.get('language', self._detect_language(name))
            
            voice = VoiceInfo(
                name=name,
                model_path=onnx_file,
                config_path=json_file,
                display_name=metadata.get('display_name', name),
                language=language,
                sample_rate=sample_rate,
                description=metadata.get('description', ''),
                metadata=metadata
            )
            
            logger.debug(f"发现音色: {voice}")
            return voice
            
        except Exception as e:
            logger.warning(f"解析音色配置失败 {onnx_file}: {e}")
            return None
    
    def _load_metadata(self, dir_path: Path, voice_name: str) -> Dict:
        """
        加载音色元数据
        
        查找顺序：
        1. {dir_path}/info.json
        2. {dir_path}/{voice_name}_info.json
        3. {dir_path}/{voice_name}.meta.json
        """
        possible_files = [
            dir_path / "info.json",
            dir_path / f"{voice_name}_info.json",
            dir_path / f"{voice_name}.meta.json",
        ]
        
        for meta_file in possible_files:
            if meta_file.exists():
                try:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    logger.debug(f"加载元数据失败 {meta_file}: {e}")
        
        return {}
    
    def _detect_language(self, name: str) -> str:
        """根据名称推断语言"""
        name_lower = name.lower()
        
        language_hints = {
            'zh': ['zh', 'chinese', 'cn', 'mandarin', 'fanchen', 'huayan'],
            'en': ['en', 'english', 'us', 'uk'],
            'ja': ['ja', 'japanese', 'jp'],
            'ko': ['ko', 'korean', 'kr'],
        }
        
        for lang, hints in language_hints.items():
            for hint in hints:
                if hint in name_lower:
                    return lang
        
        return 'zh'
    
    def get_voice(self, name: str) -> Optional[VoiceInfo]:
        """
        获取指定音色信息
        
        Args:
            name: 音色名称
            
        Returns:
            VoiceInfo对象或None
        """
        return self._voices.get(name)
    
    def get_voice_names(self) -> List[str]:
        """获取所有音色名称列表"""
        return list(self._voices.keys())
    
    def get_voice_display_names(self) -> Dict[str, str]:
        """
        获取音色名称到显示名称的映射
        
        Returns:
            {name: display_name} 字典
        """
        return {name: voice.display_name for name, voice in self._voices.items()}
    
    def voice_exists(self, name: str) -> bool:
        """检查音色是否存在"""
        return name in self._voices
    
    def reload(self) -> List[VoiceInfo]:
        """重新扫描音色目录"""
        return self.scan_voices()
    
    def get_default_voice(self) -> Optional[VoiceInfo]:
        """获取默认音色信息"""
        if self._default_voice:
            return self._voices.get(self._default_voice)
        return None