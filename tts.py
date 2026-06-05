from __future__ import annotations

import os
import shutil
import tarfile
import threading
import urllib.request
import wave
from pathlib import Path
from typing import Optional, Callable

from logger import get_module_logger
from resource_path import paths
import config

logger = get_module_logger("tts")

# 全局 sherpa-onnx TTS 实例
_tts_engine = None
_tts_model_path = None

# 可用的 TTS 模型配置
TTS_MODEL_OPTIONS = {
    "zh": {
        "name": "中文模型（sherpa-onnx-vits-zh-ll）",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2",
        "model_name": "sherpa-onnx-vits-zh-ll",
        "description": "纯中文模型，5个音色",
        "speakers": ["苏映雪（女声）", "顾念（女声）", "付思雨（女声）", "冰娇（女声）", "巴总（男声）"]
    },
    "zh_en": {
        "name": "中英文模型（vits-melo-tts-zh_en）",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2",
        "model_name": "vits-melo-tts-zh_en",
        "description": "支持中英文混合朗读",
        "speakers": ["默认音色"]
    }
}

# 默认模型类型
DEFAULT_TTS_MODEL_TYPE = "zh"


def get_default_tts_model_dir() -> Path:
    """获取默认 TTS 模型目录路径"""
    model_dir = paths.personal_data_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def download_tts_model(model_type: str = "zh", callback: Callable[[int, str], None] = None) -> Optional[Path]:
    """
    自动下载 TTS 模型到 PersonalData/model 目录
    
    Args:
        model_type: 模型类型，"zh"（中文）或 "zh_en"（中英文）
        callback: 进度回调函数 (progress: int, status: str)
    
    Returns:
        模型目录路径，如果失败则返回 None
    """
    if model_type not in TTS_MODEL_OPTIONS:
        logger.error(f"不支持的模型类型: {model_type}")
        return None
    
    model_config = TTS_MODEL_OPTIONS[model_type]
    model_url = model_config["url"]
    model_name = model_config["model_name"]
    
    model_dir = get_default_tts_model_dir()
    target_dir = model_dir / model_name
    
    # 如果模型已存在，直接返回
    if target_dir.exists():
        # 检查是否有必要的模型文件
        onnx_files = list(target_dir.glob("*.onnx"))
        if onnx_files:
            logger.info(f"TTS 模型已存在: {target_dir}")
            return target_dir
    
    if callback:
        callback(5, f"正在准备下载 {model_config['name']}...")
    
    logger.info(f"开始下载 TTS 模型到: {model_dir}")
    
    try:
        # 下载压缩包
        tar_path = model_dir / f"{model_name}.tar.bz2"
        
        if callback:
            callback(10, f"正在下载 {model_config['name']}...")
        
        def download_progress(block_num, block_size, total_size):
            if total_size > 0:
                progress = int(10 + (block_num * block_size / total_size) * 50)
                if callback and progress <= 60:
                    callback(progress, f"正在下载 {model_config['name']}...")
        
        urllib.request.urlretrieve(model_url, tar_path, download_progress)
        
        if callback:
            callback(65, "正在解压模型文件...")
        
        # 解压
        with tarfile.open(tar_path, 'r:bz2') as tar:
            tar.extractall(model_dir)
        
        # 删除压缩包
        tar_path.unlink()
        
        if callback:
            callback(95, f"{model_config['name']}下载完成")
        
        logger.info(f"TTS 模型下载并解压完成: {target_dir}")
        return target_dir
        
    except Exception as e:
        logger.exception(f"下载 TTS 模型失败: {e}")
        if callback:
            callback(0, f"下载失败: {e}")
        return None


def load_tts_model(model_path: str = None, model_type: str = None, callback: Callable[[int, str], None] = None, auto_download: bool = None) -> bool:
    """
    加载 sherpa-onnx TTS 模型
    
    Args:
        model_path: TTS 模型目录路径，默认使用配置中的值或自动下载
        model_type: 模型类型，"zh"（中文）或 "zh_en"（中英文），仅在自动下载时使用
        callback: 进度回调函数 (progress: int, status: str)
        auto_download: 是否在模型不存在时自动下载，默认使用配置中的值
    
    Returns:
        是否加载成功
    """
    global _tts_engine, _tts_model_path
    
    # 如果没有指定 auto_download，使用配置中的值
    if auto_download is None:
        auto_download = getattr(config, 'TTS_AUTO_DOWNLOAD', True)
    
    # 如果没有指定模型类型，使用配置中的值或默认值
    if model_type is None:
        model_type = getattr(config, 'TTS_MODEL_TYPE', DEFAULT_TTS_MODEL_TYPE)
    
    # 如果没有指定路径，尝试使用配置或默认目录
    if model_path is None:
        model_path = getattr(config, 'TTS_MODEL_PATH', '')
        
        # 如果配置中没有路径，使用默认目录
        if not model_path and auto_download:
            model_config = TTS_MODEL_OPTIONS.get(model_type, TTS_MODEL_OPTIONS[DEFAULT_TTS_MODEL_TYPE])
            default_dir = get_default_tts_model_dir() / model_config["model_name"]
            if default_dir.exists():
                model_path = str(default_dir)
            else:
                # 自动下载模型
                if callback:
                    callback(0, f"TTS 模型未找到，正在自动下载 {model_config['name']}...")
                downloaded_path = download_tts_model(model_type, callback)
                if downloaded_path:
                    model_path = str(downloaded_path)
                    # 保存到配置
                    config.set_config("TTS_MODEL_PATH", model_path)
                    config.TTS_MODEL_PATH = model_path
                else:
                    return False
    
    if not model_path:
        if callback:
            callback(0, "错误: 未配置 TTS 模型路径")
        logger.error("TTS 模型路径未配置")
        return False
    
    model_path = Path(model_path)
    
    # 如果模型目录不存在，尝试自动下载
    if not model_path.exists() and auto_download:
        if callback:
            callback(0, "TTS 模型目录不存在，正在自动下载...")
        downloaded_path = download_tts_model(model_type, callback)
        if downloaded_path:
            model_path = downloaded_path
        else:
            return False
    
    if not model_path.exists():
        if callback:
            callback(0, f"错误: TTS 模型目录不存在: {model_path}")
        logger.error(f"TTS 模型目录不存在: {model_path}")
        return False
    
    if callback:
        callback(70, "正在初始化 TTS 引擎...")
    
    try:
        import sherpa_onnx
        
        if callback:
            callback(80, "正在加载 TTS 模型...")
        
        # 查找模型文件，优先使用非量化版本
        onnx_files = list(model_path.glob("*.onnx"))
        if not onnx_files:
            if callback:
                callback(0, f"错误: 未找到 TTS ONNX 模型文件")
            logger.error(f"未找到 TTS ONNX 模型文件: {model_path}")
            return False
        
        # 优先选择 model.onnx（非量化版本），如果没有则使用其他版本
        model_file = None
        for f in onnx_files:
            if f.name == "model.onnx":
                model_file = f
                break
        
        # 如果没有找到 model.onnx，尝试使用 model.int8.onnx 或其他
        if model_file is None:
            for f in onnx_files:
                if "int8" not in f.name.lower():
                    model_file = f
                    break
        
        # 最后才使用 int8 版本
        if model_file is None:
            model_file = onnx_files[0]
        
        logger.info(f"使用模型文件: {model_file.name}")
        
        # 查找 tokens.txt 文件
        tokens_file = model_path / "tokens.txt"
        if not tokens_file.exists():
            tokens_files = list(model_path.glob("tokens*.txt"))
            if tokens_files:
                tokens_file = tokens_files[0]
            else:
                if callback:
                    callback(0, f"错误: 未找到 tokens.txt 文件")
                logger.error(f"未找到 tokens.txt 文件: {model_path}")
                return False
        
        # 查找 lexicon.txt 文件（中文模型必需）
        lexicon_file = model_path / "lexicon.txt"
        if not lexicon_file.exists():
            lexicon_files = list(model_path.glob("lexicon*.txt"))
            if lexicon_files:
                lexicon_file = lexicon_files[0]
            else:
                if callback:
                    callback(0, f"错误: 未找到 lexicon.txt 文件")
                logger.error(f"未找到 lexicon.txt 文件: {model_path}")
                return False
        
        # 查找 dict 目录（jieba 分词词典，可选）
        dict_dir = model_path / "dict"
        
        if callback:
            callback(90, "正在创建 TTS 引擎...")
        
        # 创建 TTS 配置
        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model_file),
                    tokens=str(tokens_file),
                    lexicon=str(lexicon_file),
                    data_dir="",  # 中文模型不需要 espeak-ng-data
                ),
                num_threads=4,
            ),
            max_num_sentences=1,  # 每次生成一个句子
        )
        
        # 如果有 dict 目录，设置 jieba 分词词典
        if dict_dir.exists():
            tts_config.model.vits.dict_dir = str(dict_dir)
        
        # 创建 TTS 引擎
        _tts_engine = sherpa_onnx.OfflineTts(tts_config)
        
        _tts_model_path = str(model_path)
        
        if callback:
            callback(100, "TTS 模型加载完成")
        
        logger.info(f"TTS 模型加载完成: {model_file}")
        return True
        
    except ImportError as ie:
        logger.error(f"sherpa-onnx 库导入失败: {ie}")
        if callback:
            callback(0, "错误: sherpa-onnx 未安装，请运行 pip install sherpa-onnx")
        return False
    except Exception as e:
        logger.exception(f"加载 TTS 模型失败: {e}")
        if callback:
            callback(0, f"加载失败: {e}")
        return False


def release_tts_model():
    """释放已加载的 TTS 模型以节省内存"""
    global _tts_engine, _tts_model_path
    
    logger.info("释放 TTS 模型...")
    
    if _tts_engine is not None:
        try:
            del _tts_engine
        except Exception as e:
            logger.warning(f"清理 TTS 模型资源时发生错误: {e}")
        _tts_engine = None
    
    _tts_model_path = None
    logger.info("TTS 模型已释放")


def is_tts_model_loaded() -> bool:
    """
    检查 TTS 模型是否已加载
    
    Returns:
        是否已加载
    """
    return _tts_engine is not None


def get_tts_model_path() -> Optional[str]:
    """
    获取已加载 TTS 模型的路径
    
    Returns:
        模型路径，如果未加载则返回 None
    """
    return _tts_model_path


def get_num_speakers() -> int:
    """
    获取 TTS 模型支持的说话人数量
    
    Returns:
        说话人数量，如果模型未加载则返回 0
    """
    if _tts_engine is None:
        return 0
    try:
        return _tts_engine.num_speakers
    except Exception:
        return 1


def text_to_speech(text: str, speaker_id: int = 0, speed: float = 1.0, output_path: Optional[Path] = None) -> Optional[Path]:
    """
    将文本转换为语音
    
    Args:
        text: 要转换的文本
        speaker_id: 说话人 ID（默认 0）
        speed: 语速（默认 1.0，范围 0.5-2.0）
        output_path: 输出音频文件路径，如果未指定则使用默认路径
        
    Returns:
        生成的音频文件路径，如果失败则返回 None
    """
    if _tts_engine is None:
        logger.error("TTS 模型未加载")
        return None
    
    if not text:
        logger.warning("文本为空，无法生成语音")
        return None
    
    try:
        logger.info(f"开始生成语音: {text[:50]}...")
        
        # 生成语音
        audio = _tts_engine.generate(text, sid=speaker_id, speed=speed)
        
        if audio is None or len(audio.samples) == 0:
            logger.warning("TTS 生成空音频")
            return None
        
        # 确定输出路径
        if output_path is None:
            tts_dir = paths.personal_data_dir / "tts"
            tts_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = tts_dir / f"tts_{timestamp}.wav"
        
        # 保存音频文件
        import sherpa_onnx
        sherpa_onnx.write_wave(str(output_path), audio.samples, audio.sample_rate)
        
        logger.info(f"语音生成完成: {output_path}")
        return output_path
        
    except Exception as e:
        logger.exception(f"生成语音时发生错误: {e}")
        return None


def text_to_speech_async(text: str, speaker_id: int = 0, speed: float = 1.0, 
                          callback: Callable[[Optional[Path]], None] = None) -> threading.Thread:
    """
    异步将文本转换为语音
    
    Args:
        text: 要转换的文本
        speaker_id: 说话人 ID
        speed: 语速
        callback: 完成回调函数 (audio_path: Path or None)
        
    Returns:
        线程对象
    """
    def _generate():
        try:
            result = text_to_speech(text, speaker_id, speed)
            if callback:
                callback(result)
        except Exception as e:
            logger.exception(f"异步生成语音时发生错误: {e}")
            if callback:
                callback(None)
    
    thread = threading.Thread(target=_generate, name="tts-generate", daemon=True)
    thread.start()
    return thread


def play_audio(audio_path: Path, on_finished: Callable[[], None] = None) -> threading.Thread:
    """
    播放音频文件
    
    Args:
        audio_path: 音频文件路径
        on_finished: 播放完成回调函数
        
    Returns:
        线程对象
    """
    def _play():
        try:
            import sounddevice as sd
            import numpy as np
            
            # 读取 WAV 文件
            with wave.open(str(audio_path), 'rb') as wf:
                sample_rate = wf.getframerate()
                num_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                num_frames = wf.getnframes()
                audio_data = wf.readframes(num_frames)
            
            # 转换为 numpy 数组
            if sample_width == 2:
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            elif sample_width == 4:
                audio_array = np.frombuffer(audio_data, dtype=np.int32)
            else:
                audio_array = np.frombuffer(audio_data, dtype=np.uint8)
            
            # 转换为 float32 并归一化
            audio_array = audio_array.astype(np.float32) / np.iinfo(audio_array.dtype).max
            
            # 如果是多声道，取第一个声道
            if num_channels > 1:
                audio_array = audio_array.reshape(-1, num_channels)[:, 0]
            
            # 播放音频
            sd.play(audio_array, sample_rate)
            sd.wait()
            
            logger.info(f"音频播放完成: {audio_path}")
            
            if on_finished:
                on_finished()
                
        except Exception as e:
            logger.exception(f"播放音频时发生错误: {e}")
            if on_finished:
                on_finished()
    
    thread = threading.Thread(target=_play, name="audio-play", daemon=True)
    thread.start()
    return thread


def speak_text(text: str, speaker_id: int = 0, speed: float = 1.0, 
               on_finished: Callable[[], None] = None) -> bool:
    """
    将文本转换为语音并播放（一站式接口）
    
    Args:
        text: 要朗读的文本
        speaker_id: 说话人 ID
        speed: 语速
        on_finished: 播放完成回调函数
        
    Returns:
        是否成功开始播放
    """
    if _tts_engine is None:
        logger.error("TTS 模型未加载")
        return False
    
    def _generate_and_play():
        try:
            # 生成语音
            audio_path = text_to_speech(text, speaker_id, speed)
            
            if audio_path:
                # 播放音频
                play_audio(audio_path, on_finished)
            else:
                if on_finished:
                    on_finished()
        except Exception as e:
            logger.exception(f"朗读时发生错误: {e}")
            if on_finished:
                on_finished()
    
    thread = threading.Thread(target=_generate_and_play, name="speak-text", daemon=True)
    thread.start()
    return True