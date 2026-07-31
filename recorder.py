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
from utils.lazy_loader import scipy_signal

logger = get_module_logger("recorder")

# 全局 sherpa-onnx 离线模型实例
_onnx_recognizer = None
_onnx_model_path = None
_onnx_device = None  # 当前模型运行设备："cpu" 或 "cuda"

# 全局 sherpa-onnx 流式模型实例
_online_recognizer = None
_online_model_path = None
_online_device = None  # 当前模型运行设备："cpu" 或 "cuda"
_online_stream = None  # 当前识别流

# 默认模型下载配置
DEFAULT_MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2"
DEFAULT_MODEL_NAME = "sherpa-onnx-paraformer-zh-int8-2025-10-07"
DEFAULT_ONLINE_MODEL_NAME = DEFAULT_MODEL_NAME  # 兼容别名

# 流式模型列表配置
STREAMING_MODELS = {
    "paraformer-zh-int8": {
        "name": "sherpa-onnx-paraformer-zh-int8-2025-10-07",
        "display_name": "Paraformer 中文 INT8",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-int8-2025-10-07.tar.bz2",
        "size_mb": 80,
        "languages": ["中文"],
        "use_int8": True,
    },
}


def get_streaming_models_list() -> dict:
    """
    获取可用的流式模型列表
    
    Returns:
        模型配置字典，键为模型标识，值为模型配置
    """
    return STREAMING_MODELS.copy()


def get_default_model_key() -> str:
    """
    获取默认模型键名
    
    Returns:
        默认模型的键名
    """
    return "paraformer-zh-int8"


def download_specific_online_model(model_key: str, callback: Callable[[int, str], None] = None) -> Optional[Path]:
    """
    下载指定的流式模型
    
    Args:
        model_key: 模型键名
        callback: 进度回调函数 (progress: int, status: str)
    
    Returns:
        模型目录路径，如果失败则返回 None
    """
    models = get_streaming_models_list()
    model_config = models.get(model_key)
    
    if not model_config:
        logger.error(f"未找到模型配置: {model_key}")
        if callback:
            callback(0, f"未找到模型配置: {model_key}")
        return None
    
    model_name = model_config["name"]
    model_url = model_config["url"]
    display_name = model_config["display_name"]
    
    model_dir = get_asr_model_dir()
    target_dir = model_dir / model_name
    
    # 如果模型已存在，直接返回
    if target_dir.exists():
        onnx_files = list(target_dir.glob("*.onnx"))
        if onnx_files:
            logger.info(f"模型已存在: {target_dir}")
            return target_dir
    
    if callback:
        callback(5, f"正在准备下载 {display_name}...")
    
    logger.info(f"开始下载模型 {display_name} 到: {model_dir}")
    
    try:
        tar_path = model_dir / f"{model_name}.tar.bz2"
        
        if callback:
            callback(10, f"正在下载 {display_name}（约 {model_config['size_mb']}MB）...")
        
        def download_progress(block_num, block_size, total_size):
            if total_size > 0:
                progress = int(10 + (block_num * block_size / total_size) * 50)
                if callback and progress <= 60:
                    callback(progress, f"正在下载 {display_name}...")
        
        urllib.request.urlretrieve(model_url, tar_path, download_progress)
        
        if callback:
            callback(65, "正在解压模型文件...")
        
        with tarfile.open(tar_path, 'r:bz2') as tar:
            tar.extractall(model_dir)
        
        tar_path.unlink()
        
        if callback:
            callback(95, f"{display_name} 下载完成")
        
        logger.info(f"模型下载并解压完成: {target_dir}")
        return target_dir
        
    except Exception as e:
        logger.exception(f"下载模型失败: {e}")
        if callback:
            callback(0, f"下载失败: {e}")
        return None


def check_gpu_available() -> bool:
    """
    检查系统是否有可用的 GPU（CUDA）
    
    Returns:
        是否有可用的 CUDA GPU
    """
    try:
        import sherpa_onnx
        # 尝试获取 CUDA 设备数量
        # sherpa-onnx 使用 ONNX Runtime，可以通过检查 provider 来判断
        try:
            import onnxruntime as ort
            available_providers = ort.get_available_providers()
            if 'CUDAExecutionProvider' in available_providers:
                logger.info(f"检测到 CUDA GPU 可用，可用 providers: {available_providers}")
                return True
            else:
                logger.info(f"CUDA GPU 不可用，可用 providers: {available_providers}")
                return False
        except Exception as e:
            # onnxruntime 可能因 NumPy 2.x ABI 不兼容、DLL 缺失等原因加载失败，
            # 这些异常不一定是 ImportError（如 RuntimeError），故此处捕获所有异常，
            # 保证调用方（如设置界面）不会因此崩溃，默认使用 CPU。
            logger.info(f"onnxruntime 不可用，默认使用 CPU: {e}")
            return False
    except Exception as e:
        logger.warning(f"检测 GPU 时发生错误: {e}")
        return False


def get_onnx_device() -> Optional[str]:
    """
    获取当前模型运行的设备
    
    Returns:
        设备名称："cpu" 或 "cuda"，如果模型未加载则返回 None
    """
    return _onnx_device


def get_default_model_dir() -> Path:
    """获取默认模型目录路径"""
    model_dir = paths.personal_data_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def get_asr_model_dir() -> Path:
    """
    获取 ASR 模型默认目录路径
    
    Returns:
        ASR 模型目录路径 (PersonalData/model/asr)
    """
    asr_dir = paths.personal_data_dir / "model" / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"ASR 模型目录: {asr_dir}")
    return asr_dir


def ensure_model_dirs() -> None:
    """
    确保模型目录结构存在
    
    创建 ASR 和 TTS 模型的分离目录结构：
    - PersonalData/model/asr: ASR 语音识别模型
    - PersonalData/model/tts: TTS 文本转语音模型
    """
    from tts import get_tts_model_dir
    
    get_asr_model_dir()
    get_tts_model_dir()
    logger.info("模型目录结构已初始化")


def identify_model_type(model_dir: Path) -> str:
    """
    识别模型类型（ASR 或 TTS）
    
    Args:
        model_dir: 模型目录路径
        
    Returns:
        模型类型字符串："asr" 或 "tts"，如果无法识别则返回 "unknown"
    """
    # 检查是否包含 encoder/decoder 文件（ASR 模型特征）
    encoder_files = list(model_dir.glob("encoder*.onnx"))
    decoder_files = list(model_dir.glob("decoder*.onnx"))
    
    if encoder_files or decoder_files:
        logger.debug(f"识别为 ASR 模型: {model_dir.name}")
        return "asr"
    
    # 检查是否包含 model.onnx 文件（TTS 模型特征）
    tts_model_files = list(model_dir.glob("model*.onnx"))
    
    if tts_model_files and not encoder_files and not decoder_files:
        logger.debug(f"识别为 TTS 模型: {model_dir.name}")
        return "tts"
    
    logger.warning(f"无法识别模型类型: {model_dir.name}")
    return "unknown"


def migrate_models_to_separate_dirs() -> None:
    """
    将旧目录下的模型迁移到分离的 ASR 和 TTS 目录
    
    扫描 PersonalData/model 目录下的所有子目录，识别模型类型，
    并将 ASR 模型移动到 asr 子目录，TTS 模型移动到 tts 子目录。
    """
    from tts import get_tts_model_dir
    
    old_model_dir = get_default_model_dir()
    asr_dir = get_asr_model_dir()
    tts_dir = get_tts_model_dir()
    
    # 检查是否已经完成迁移（通过标记文件）
    migration_marker = old_model_dir / ".model_migration_completed"
    if migration_marker.exists():
        logger.info("模型迁移已完成，跳过迁移")
        return
    
    logger.info("开始模型迁移...")
    
    migrated_count = 0
    skipped_count = 0
    
    # 扫描旧目录下的所有子目录
    for subdir in old_model_dir.iterdir():
        # 跳过新的分离目录和标记文件
        if subdir.name in ("asr", "tts") or subdir.name.startswith("."):
            continue
        
        if not subdir.is_dir():
            continue
        
        # 识别模型类型
        model_type = identify_model_type(subdir)
        
        if model_type == "asr":
            # 移动 ASR 模型到 asr 目录
            target_dir = asr_dir / subdir.name
            if not target_dir.exists():
                logger.info(f"迁移 ASR 模型: {subdir.name} -> asr/{subdir.name}")
                shutil.move(str(subdir), str(target_dir))
                migrated_count += 1
            else:
                logger.warning(f"ASR 模型目录已存在，跳过: {target_dir}")
                skipped_count += 1
        
        elif model_type == "tts":
            # 移动 TTS 模型到 tts 目录
            target_dir = tts_dir / subdir.name
            if not target_dir.exists():
                logger.info(f"迁移 TTS 模型: {subdir.name} -> tts/{subdir.name}")
                shutil.move(str(subdir), str(target_dir))
                migrated_count += 1
            else:
                logger.warning(f"TTS 模型目录已存在，跳过: {target_dir}")
                skipped_count += 1
        
        else:
            logger.warning(f"无法识别模型类型，跳过: {subdir.name}")
            skipped_count += 1
    
    # 创建迁移完成标记
    migration_marker.touch()
    
    logger.info(f"模型迁移完成: 迁移 {migrated_count} 个模型，跳过 {skipped_count} 个模型")


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


def load_onnx_model(model_path: str = None, callback: Callable[[int, str], None] = None, auto_download: bool = None) -> bool:
    """
    加载 sherpa-onnx ONNX 模型
    
    Args:
        model_path: ONNX 模型目录路径，默认使用配置中的值或自动下载
        callback: 进度回调函数 (progress: int, status: str)
        auto_download: 是否在模型不存在时自动下载，默认使用配置中的值
    
    Returns:
        是否加载成功
    """
    global _onnx_recognizer, _onnx_model_path, _onnx_device
    
    # 如果没有指定 auto_download，使用配置中的值
    if auto_download is None:
        auto_download = getattr(config, 'ASR_AUTO_DOWNLOAD', True)
    
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
        
        # 检测是否有可用的 GPU
        use_gpu = check_gpu_available()
        
        # 创建 OfflineRecognizer
        # Paraformer ONNX INT8 模型配置
        try:
            if use_gpu:
                if callback:
                    callback(92, "尝试加载到 GPU...")
                logger.info("尝试使用 CUDA GPU 加载模型")
                _onnx_recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    paraformer=str(model_file),
                    tokens=str(tokens_file),
                    num_threads=4,
                    sample_rate=16000,
                    decoding_method="greedy_search",
                    provider="cuda",
                )
                _onnx_device = "cuda"
                logger.info("模型成功加载到 CUDA GPU")
                if callback:
                    callback(95, "GPU 加载成功")
            else:
                raise Exception("GPU 不可用，使用 CPU")
        except Exception as gpu_error:
            # GPU 加载失败，降级到 CPU
            logger.warning(f"GPU 加载失败: {gpu_error}, 降级使用 CPU")
            if callback:
                callback(93, "GPU 加载失败，使用 CPU...")
            _onnx_recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=str(model_file),
                tokens=str(tokens_file),
                num_threads=4,
                sample_rate=16000,
                decoding_method="greedy_search",
            )
            _onnx_device = "cpu"
            logger.info("模型加载到 CPU")
        
        _onnx_model_path = str(model_path)
        
        if callback:
            callback(100, f"模型加载完成 ({_onnx_device.upper()})")
        
        logger.info(f"sherpa-onnx 模型加载完成: {model_file}, 设备: {_onnx_device}")
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
    global _onnx_recognizer, _onnx_model_path, _onnx_device
    
    logger.info("释放 sherpa-onnx 模型...")
    
    if _onnx_recognizer is not None:
        try:
            del _onnx_recognizer
        except Exception as e:
            logger.warning(f"清理模型资源时发生错误: {e}")
        _onnx_recognizer = None
    
    _onnx_model_path = None
    _onnx_device = None
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


# ============================================================================
# 流式模型（OnlineRecognizer）相关函数
# ============================================================================

def load_online_model(model_path: str = None, callback: Callable[[int, str], None] = None, auto_download: bool = None) -> bool:
    """
    加载 sherpa-onnx 流式模型（OnlineRecognizer）
    
    支持加载包含 encoder/decoder/joiner 文件的流式模型
    
    Args:
        model_path: 流式模型目录路径
        callback: 进度回调函数 (progress: int, status: str)
        auto_download: 是否在模型不存在时自动下载，默认使用配置中的值
    
    Returns:
        是否加载成功
    """
    global _online_recognizer, _online_model_path, _online_device
    
    # 如果没有指定 auto_download，使用配置中的值
    if auto_download is None:
        auto_download = getattr(config, 'ASR_AUTO_DOWNLOAD', True)
    
    # 如果没有指定路径，尝试使用配置或默认目录
    if model_path is None:
        # 优先使用 ASR_REALTIME_MODEL_PATH（新配置项）
        model_path = getattr(config, 'ASR_REALTIME_MODEL_PATH', '')

        # 向后兼容：如果 ASR_REALTIME_MODEL_PATH 为空，尝试读取旧配置项
        if not model_path:
            old_config_path = getattr(config, 'ASR_ONNX_MODEL_PATH', '')
            if old_config_path:
                model_path = old_config_path
                logger.info("配置项迁移：使用旧配置项 ASR_ONNX_MODEL_PATH 作为流式模型路径")

        # 如果配置中没有路径，使用默认目录
        if not model_path and auto_download:
            default_dir = get_asr_model_dir() / DEFAULT_ONLINE_MODEL_NAME
            if default_dir.exists():
                model_path = str(default_dir)
    
    if not model_path:
        if callback:
            callback(0, "错误: 未配置模型路径")
        logger.error("流式模型路径未配置")
        return False
    
    model_path = Path(model_path)
    
    if not model_path.exists():
        if callback:
            callback(0, f"错误: 模型目录不存在: {model_path}")
        logger.error(f"流式模型目录不存在: {model_path}")
        return False
    
    if callback:
        callback(70, "正在初始化 sherpa-onnx...")
    
    try:
        import sherpa_onnx
        
        if callback:
            callback(80, "正在加载流式模型...")
        
        # 查找模型文件
        model_dir = Path(model_path)
        
        # 查找 encoder/decoder/joiner 文件（流式模型特征）
        encoder_files = list(model_dir.glob("encoder*.onnx"))
        decoder_files = list(model_dir.glob("decoder*.onnx"))
        joiner_files = list(model_dir.glob("joiner*.onnx"))
        
        # 查找 tokens.txt 文件
        tokens_file = model_dir / "tokens.txt"
        if not tokens_file.exists():
            tokens_files = list(model_dir.glob("tokens*.txt"))
            if tokens_files:
                tokens_file = tokens_files[0]
            else:
                if callback:
                    callback(0, f"错误: 未找到 tokens.txt 文件")
                logger.error(f"未找到 tokens.txt 文件: {model_dir}")
                return False
        
        # 确定模型类型并加载
        if encoder_files and decoder_files and joiner_files:
            # 流式 transducer 模型（有 joiner）
            encoder_file = encoder_files[0]
            decoder_file = decoder_files[0]
            joiner_file = joiner_files[0]
            model_type = "transducer"
            logger.info(f"识别为流式 Transducer 模型: encoder={encoder_file.name}, decoder={decoder_file.name}, joiner={joiner_file.name}")
        elif encoder_files and decoder_files:
            # 流式 paraformer 模型（无 joiner）
            encoder_file = encoder_files[0]
            decoder_file = decoder_files[0]
            model_type = "paraformer"
            logger.info(f"识别为流式 Paraformer 模型: encoder={encoder_file.name}, decoder={decoder_file.name}")
        else:
            # 不是流式模型，可能用户选择了错误的模型目录
            if callback:
                callback(0, f"错误: 模型目录不包含流式模型文件 (encoder/decoder)")
            logger.error(f"模型目录不包含流式模型文件: {model_dir}")
            logger.info(f"找到的文件: encoder={encoder_files}, decoder={decoder_files}, joiner={joiner_files}")
            return False
        
        if callback:
            callback(90, "正在创建流式识别器...")
        
        # 检测是否有可用的 GPU
        use_gpu = check_gpu_available()
        
        # 优先选择 int8 模型文件
        if model_type == "transducer":
            encoder_file = next((f for f in encoder_files if 'int8' in f.name), encoder_files[0])
            decoder_file = next((f for f in decoder_files if 'int8' in f.name), decoder_files[0])
            joiner_file = next((f for f in joiner_files if 'int8' in f.name), joiner_files[0])
        else:  # paraformer
            encoder_file = next((f for f in encoder_files if 'int8' in f.name), encoder_files[0])
            decoder_file = next((f for f in decoder_files if 'int8' in f.name), decoder_files[0])
        # 加载模型
        try:
            if use_gpu:
                if callback:
                    callback(92, "尝试加载到 GPU...")
                logger.info("尝试使用 CUDA GPU 加载流式模型")

                if model_type == "transducer":
                    _online_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                        encoder=str(encoder_file),
                        decoder=str(decoder_file),
                        joiner=str(joiner_file),
                        tokens=str(tokens_file),
                        num_threads=4,
                        sample_rate=16000,
                        decoding_method="greedy_search",
                        provider="cuda",
                    )
                else:  # paraformer
                    _online_recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
                        encoder=str(encoder_file),
                        decoder=str(decoder_file),
                        tokens=str(tokens_file),
                        num_threads=4,
                        sample_rate=16000,
                        decoding_method="greedy_search",
                        provider="cuda",
                    )

                _online_device = "cuda"
                logger.info(f"流式 {model_type} 模型成功加载到 CUDA GPU")
                if callback:
                    callback(95, "GPU 加载成功")
            else:
                raise Exception("GPU 不可用，使用 CPU")
        except Exception as gpu_error:
            # GPU 加载失败，降级到 CPU
            logger.warning(f"GPU 加载流式模型失败: {gpu_error}, 降级使用 CPU")
            if callback:
                callback(93, "GPU 加载失败，使用 CPU...")

            if model_type == "transducer":
                _online_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    encoder=str(encoder_file),
                    decoder=str(decoder_file),
                    joiner=str(joiner_file),
                    tokens=str(tokens_file),
                    num_threads=4,
                    sample_rate=16000,
                    decoding_method="greedy_search",
                )
            else:  # paraformer
                _online_recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
                    encoder=str(encoder_file),
                    decoder=str(decoder_file),
                    tokens=str(tokens_file),
                    num_threads=4,
                    sample_rate=16000,
                    decoding_method="greedy_search",
                )

            _online_device = "cpu"
            logger.info(f"流式 {model_type} 模型加载到 CPU")

        _online_model_path = str(model_path)
        
        if callback:
            callback(100, f"流式模型加载完成 ({_online_device.upper()})")
        
        logger.info(f"sherpa-onnx 流式模型加载完成: {model_path}, 设备: {_online_device}")
        return True
        
    except ImportError as ie:
        logger.error(f"sherpa-onnx 库导入失败: {ie}")
        if callback:
            callback(0, "错误: sherpa-onnx 未安装，请运行 pip install sherpa-onnx")
        return False
    except Exception as e:
        logger.exception(f"加载 sherpa-onnx 流式模型失败: {e}")
        if callback:
            callback(0, f"加载失败: {e}")
        return False


def release_online_model():
    """释放已加载的 sherpa-onnx 流式模型以节省内存"""
    global _online_recognizer, _online_model_path, _online_device, _online_stream
    
    logger.info("释放 sherpa-onnx 流式模型...")

    # 先销毁识别流
    if _online_stream is not None:
        try:
            _online_stream = None
            logger.info("已销毁实时识别流")
        except Exception as e:
            logger.warning(f"销毁识别流时发生错误: {e}")
            _online_stream = None

    if _online_recognizer is not None:
        try:
            del _online_recognizer
        except Exception as e:
            logger.warning(f"清理流式模型资源时发生错误: {e}")
        _online_recognizer = None

    _online_model_path = None
    _online_device = None
    logger.info("sherpa-onnx 流式模型已释放")


def is_online_model_loaded() -> bool:
    """
    检查 sherpa-onnx 流式模型是否已加载

    Returns:
        是否已加载
    """
    return _online_recognizer is not None


def get_online_model_path() -> Optional[str]:
    """
    获取已加载流式模型的路径

    Returns:
        模型路径，如果未加载则返回 None
    """
    return _online_model_path


def get_online_device() -> Optional[str]:
    """
    获取流式模型当前运行的设备

    Returns:
        设备名称（"cpu" 或 "cuda"），如果模型未加载则返回 None
    """
    return _online_device


# ============================================================================
# 实时识别流管理函数
# ============================================================================

def create_online_stream() -> Optional[object]:
    """
    创建实时识别流

    需要先加载流式模型

    Returns:
        OnlineStream 实例，如果失败则返回 None
    """
    global _online_stream

    if _online_recognizer is None:
        logger.error("流式模型未加载，无法创建识别流")
        return None

    try:
        _online_stream = _online_recognizer.create_stream()
        logger.info("已创建实时识别流")
        return _online_stream
    except Exception as e:
        logger.exception(f"创建实时识别流失败: {e}")
        return None


def process_online_stream(audio_data: bytes, sample_rate: int = 16000) -> bool:
    """
    处理音频数据，将音频输入识别流

    Args:
        audio_data: 音频数据（16-bit PCM）
        sample_rate: 采样率

    Returns:
        是否处理成功
    """
    global _online_stream

    if _online_stream is None:
        logger.error("识别流未创建")
        return False

    if _online_recognizer is None:
        logger.error("流式模型未加载")
        return False

    try:
        import numpy as np

        # 转换为 numpy 数组
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        # 转换为 float32 并归一化
        audio_float = audio_array.astype(np.float32) / 32768.0

        # 输入识别流
        _online_stream.accept_waveform(sample_rate, audio_float)

        return True
    except Exception as e:
        logger.exception(f"处理音频数据失败: {e}")
        return False


def get_online_stream_result() -> Optional[str]:
    """
    获取当前识别流的识别结果

    Returns:
        当前识别的文本，如果没有结果则返回 None
    """
    global _online_stream

    if _online_stream is None:
        return None

    if _online_recognizer is None:
        return None

    try:
        # 检查是否有结果
        if _online_recognizer.is_ready(_online_stream):
            _online_recognizer.decode_stream(_online_stream)

        result = _online_recognizer.get_result(_online_stream)
        if result:
            return result.strip()

        return None
    except Exception as e:
        logger.exception(f"获取识别结果失败: {e}")
        return None


def destroy_online_stream():
    """销毁当前识别流，释放资源"""
    global _online_stream

    if _online_stream is not None:
        try:
            # sherpa-onnx 的 stream 没有显式的 destroy 方法
            # 直接设置为 None 即可
            _online_stream = None
            logger.info("已销毁实时识别流")
        except Exception as e:
            logger.warning(f"销毁识别流时发生错误: {e}")
            _online_stream = None


def transcribe_audio_with_onnx(audio_path: Path, progress_callback: Optional[Callable[[int, str], None]] = None) -> Optional[str]:
    """
    使用 sherpa-onnx 进行语音转文本
    
    对于长音频（超过阈值），自动分割成多个片段处理，避免内存/显存溢出
    
    Args:
        audio_path: 音频文件路径
        progress_callback: 进度回调函数 (progress: int, status: str)
        
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
        
        import sherpa_onnx
        import numpy as np
        
        if progress_callback:
            progress_callback(5, "开始转录...")
        
        # 读取 WAV 文件
        if progress_callback:
            progress_callback(10, "正在加载音频文件...")
        
        with wave.open(str(audio_path), 'rb') as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            num_frames = wf.getnframes()
            audio_data = wf.readframes(num_frames)
        
        # 计算音频时长
        duration = num_frames / float(sample_rate)
        logger.info(f"音频时长: {duration:.1f} 秒 ({duration/60:.1f} 分钟)")
        
        # 分块处理的阈值（秒），默认 300 秒（5分钟）
        chunk_threshold = getattr(config, 'ASR_GPU_MAX_DURATION', 300)
        
        # 转换为 numpy 数组
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # 如果是多声道，转换为单声道
        if num_channels > 1:
            audio_array = audio_array.reshape(-1, num_channels)
            audio_array = audio_array.mean(axis=1).astype(np.int16)
        
        # 重采样到 16kHz（如果需要）
        if sample_rate != 16000:
            # 延迟加载scipy.signal
            signal = scipy_signal.load()
            if signal:
                logger.info(f"重采样: {sample_rate}Hz -> 16000Hz")
                if progress_callback:
                    progress_callback(15, f"重采样: {sample_rate}Hz -> 16000Hz")
                audio_array = signal.resample_poly(
                    audio_array,
                    16000,
                    sample_rate
                ).astype(np.int16)
            else:
                # 降级方案：使用numpy实现简单重采样
                logger.warning("scipy.signal不可用，使用numpy降级方案进行重采样")
                if progress_callback:
                    progress_callback(15, f"重采样（降级方案）: {sample_rate}Hz -> 16000Hz")
                ratio = 16000 / sample_rate
                n_samples = int(len(audio_array) * ratio)
                indices = np.linspace(0, len(audio_array) - 1, n_samples)
                audio_array = np.interp(indices, np.arange(len(audio_array)), audio_array).astype(np.int16)
        
        # 判断是否需要分块处理
        if duration > chunk_threshold:
            logger.info(f"音频时长超过阈值 ({chunk_threshold}秒)，启用分块处理")
            return _transcribe_audio_in_chunks(audio_array, duration, chunk_threshold, progress_callback)
        else:
            # 短音频直接处理
            if progress_callback:
                progress_callback(30, "正在进行语音识别...")
            result = _transcribe_audio_single(audio_array)
            if progress_callback:
                progress_callback(100, "转录完成")
            return result
        
    except Exception as e:
        logger.exception(f"语音识别时发生错误: {e}")
        if progress_callback:
            progress_callback(0, f"错误: {str(e)}")
        return None


def _transcribe_audio_single(audio_array) -> Optional[str]:
    """
    处理单个音频片段（不分块）
    
    Args:
        audio_array: numpy 数组形式的音频数据（16kHz, int16）
        
    Returns:
        转录文本
    """
    import sherpa_onnx
    
    stream = _onnx_recognizer.create_stream()
    stream.accept_waveform(16000, audio_array)
    _onnx_recognizer.decode_stream(stream)
    result = stream.result.text
    
    if result:
        logger.info(f"语音识别成功，文本长度: {len(result)}")
        return result.strip()
    else:
        logger.warning("sherpa-onnx 返回空文本")
        return None


def _transcribe_audio_in_chunks(audio_array, total_duration: float, chunk_duration: float = 300, progress_callback: Optional[Callable[[int, str], None]] = None) -> Optional[str]:
    """
    分块处理长音频
    
    Args:
        audio_array: numpy 数组形式的音频数据（16kHz, int16）
        total_duration: 音频总时长（秒）
        chunk_duration: 每个片段的时长（秒），默认 300 秒（5分钟）
        progress_callback: 进度回调函数 (progress: int, status: str)
        
    Returns:
        合并后的转录文本
    """
    import numpy as np
    
    # 计算分块参数
    sample_rate = 16000
    chunk_samples = int(chunk_duration * sample_rate)
    
    # 片段之间的重叠（1秒），避免边界处的语音被截断
    overlap_samples = int(1.0 * sample_rate)
    
    # 计算实际每个片段的大小（减去重叠部分）
    effective_chunk_samples = chunk_samples - overlap_samples
    
    # 计算需要多少个片段
    total_samples = len(audio_array)
    num_chunks = max(1, int(np.ceil((total_samples - overlap_samples) / effective_chunk_samples)))
    
    logger.info(f"分块处理: 总时长 {total_duration:.1f}秒, 分为 {num_chunks} 个片段, 每片段约 {chunk_duration}秒")
    
    if progress_callback:
        progress_callback(30, f"分块处理: 共 {num_chunks} 个片段")
    
    results = []
    
    for i in range(num_chunks):
        # 计算当前片段的起始和结束位置
        start = i * effective_chunk_samples
        end = min(start + chunk_samples, total_samples)
        
        # 提取当前片段
        chunk = audio_array[start:end]
        
        # 计算当前片段时长
        chunk_duration_actual = len(chunk) / sample_rate
        
        logger.info(f"处理片段 {i+1}/{num_chunks}: {chunk_duration_actual:.1f}秒, 位置 {start}-{end}")
        
        # 计算进度：30% 开始，到 95% 结束
        chunk_progress = 30 + int((i / num_chunks) * 65)
        if progress_callback:
            progress_callback(chunk_progress, f"处理片段 {i+1}/{num_chunks}")
        
        # 处理当前片段
        chunk_result = _transcribe_audio_single(chunk)
        
        if chunk_result:
            results.append(chunk_result)
            logger.info(f"片段 {i+1} 转录完成: {len(chunk_result)} 字符")
        else:
            logger.warning(f"片段 {i+1} 转录失败或返回空结果")
    
    # 合并所有结果
    if results:
        # 使用换行符连接各片段结果
        final_result = "\n".join(results)
        logger.info(f"分块处理完成，总文本长度: {len(final_result)} 字符")
        if progress_callback:
            progress_callback(100, "转录完成")
        return final_result
    else:
        logger.warning("所有片段转录均失败")
        if progress_callback:
            progress_callback(0, "转录失败")
        return None


class AudioRecorder:
    """
    音频录音管理器
    
    功能：
    1. 使用 sounddevice 进行录音
    2. 保存为 WAV 格式到 PersonalData/records 目录
    3. 使用 sherpa-onnx 流式模型进行实时语音识别
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
        
        # 实时识别相关
        self._realtime_callback: Optional[Callable[[str, bool], None]] = None
        self._recognition_thread: Optional[threading.Thread] = None
        self._realtime_stream = None  # sherpa-onnx OnlineStream
        
        self._ensure_records_dir()
        
    def _ensure_records_dir(self) -> Path:
        records_dir = paths.personal_data_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        return records_dir
    
    @property
    def is_recording(self) -> bool:
        return self._is_recording
    
    def start_recording(self, on_started: Optional[Callable[[], None]] = None, realtime_callback: Optional[Callable[[str, bool], None]] = None) -> bool:
        """
        开始录音
        
        Args:
            on_started: 录音开始后的回调函数
            realtime_callback: 实时识别结果回调 (text: str, is_final: bool)
                              如果流式模型已加载，录音期间会定期回调识别结果
            
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
        self._realtime_callback = realtime_callback
        # 如果流式模型已加载且有回调，创建实时识别流
        if realtime_callback and _online_recognizer is not None:
            try:
                self._realtime_stream = _online_recognizer.create_stream()
                logger.info("已创建实时识别流，录音期间将进行实时语音识别")
            except Exception as e:
                logger.warning(f"创建实时识别流失败: {e}，将仅录音不做实时识别")
                self._realtime_stream = None
        
        def _record_audio():
            try:
                def callback(indata, frames, time, status):
                    if self._stop_event.is_set():
                        raise sd.CallbackStop()
                    audio_chunk = indata.copy()
                    self._audio_frames.append(audio_chunk)

                    # 同时喂给实时识别流
                    if self._realtime_stream is not None:
                        try:
                            import numpy as np
                            audio_float = audio_chunk.flatten().astype(np.float32) / 32768.0
                            self._realtime_stream.accept_waveform(self._sample_rate, audio_float)
                        except Exception as e:
                            logger.warning(f"喂音频到识别流失败: {e}")

                # 获取音频输入设备配置
                device_id = config.get_audio_input_device()
                if device_id is not None:
                    logger.info(f"使用配置的音频输入设备: ID={device_id}")
                else:
                    logger.debug("使用系统默认音频输入设备")

                with sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype=self._dtype,
                    device=device_id,
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
        
        # 启动实时识别线程
        if self._realtime_stream is not None and realtime_callback is not None:
            self._recognition_thread = threading.Thread(
                target=self._realtime_recognition_loop,
                name="realtime-recognition",
                daemon=True
            )
            self._recognition_thread.start()
            logger.info("实时识别线程已启动")
        
        if on_started:
            try:
                on_started()
            except Exception as e:
                logger.exception(f"执行录音开始回调时发生错误: {e}")
        
        logger.info("录音已开始")
        return True
    
    def _realtime_recognition_loop(self):
        """实时识别循环，定期解码并回调结果"""
        while not self._stop_event.is_set() and self._realtime_stream is not None and self._realtime_callback is not None:
            try:
                if _online_recognizer is not None:
                    # 先尝试解码（is_ready 时才解码）
                    if _online_recognizer.is_ready(self._realtime_stream):
                        _online_recognizer.decode_stream(self._realtime_stream)

                    # 无论是否解码，都尝试获取当前累积的识别结果
                    result = _online_recognizer.get_result(self._realtime_stream)
                    if result and result.strip():
                        try:
                            self._realtime_callback(result.strip(), False)
                        except Exception as e:
                            logger.warning(f"实时识别回调失败: {e}")
            except Exception as e:
                logger.warning(f"实时识别处理失败: {e}")

            # 每 200ms 检查一次
            self._stop_event.wait(0.2)
    
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
        
        # 等待识别线程结束
        if self._recognition_thread:
            self._recognition_thread.join(timeout=1.0)
            self._recognition_thread = None
        
        if self._recording_thread:
            self._recording_thread.join(timeout=2.0)
            self._recording_thread = None
        
        # 获取实时识别的最终结果
        final_text = None
        if self._realtime_stream is not None and _online_recognizer is not None:
            try:
                # 输入尾部标记（end of segment）告诉模型音频已结束
                import numpy as np
                self._realtime_stream.accept_waveform(self._sample_rate, np.zeros(0, dtype=np.float32))
                # 尝试多次解码确保获取最终结果
                for _ in range(3):
                    if _online_recognizer.is_ready(self._realtime_stream):
                        _online_recognizer.decode_stream(self._realtime_stream)
                result = _online_recognizer.get_result(self._realtime_stream)
                if result:
                    final_text = result.strip()
                    logger.info(f"实时识别最终结果: {final_text}")
                # 回调最终结果
                if final_text and self._realtime_callback:
                    try:
                        self._realtime_callback(final_text, True)
                    except Exception as e:
                        logger.warning(f"最终结果回调失败: {e}")
            except Exception as e:
                logger.warning(f"获取实时识别最终结果失败: {e}")
            finally:
                self._realtime_stream = None
        
        self._realtime_callback = None
        
        # 如果有最终识别结果且不为空，不需要保存音频文件
        # 返回 None 表示实时识别成功，text 通过回调传递
        if final_text:
            self._audio_frames = []
            if on_stopped:
                try:
                    on_stopped()
                except Exception as e:
                    logger.exception(f"执行录音停止回调时发生错误: {e}")
            return None
        
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
    
    def get_audio_duration(self, audio_path: Path) -> Optional[float]:
        """
        获取音频文件的时长（秒）
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            音频时长（秒），如果失败则返回 None
        """
        try:
            audio_path = Path(audio_path) if isinstance(audio_path, str) else audio_path
            
            if not audio_path.exists():
                logger.error(f"音频文件不存在: {audio_path}")
                return None
            
            with wave.open(str(audio_path), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration = frames / float(rate)
                return duration
                
        except Exception as e:
            logger.exception(f"获取音频时长失败: {e}")
            return None
    
    def transcribe_audio_async(
        self,
        audio_path: Path,
        callback: Optional[Callable[[str, Optional[str], Optional[str]], None]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Optional[AudioTranscribeWorker]:
        """
        异步转录音频文件
        
        Args:
            audio_path: 音频文件路径
            callback: 转录完成回调函数 (audio_path: str, text: Optional[str], error: Optional[str])
                     - text 为 None 且 error 不为 None 表示转录失败
                     - text 不为 None 且 error 为 None 表示转录成功
            progress_callback: 进度回调函数 (progress: int, status: str)
            
        Returns:
            AudioTranscribeWorker 实例，如果音频时长超限或文件不存在则返回 None
        """
        audio_path = Path(audio_path) if isinstance(audio_path, str) else audio_path
        
        # 检查音频文件是否存在
        if not audio_path.exists():
            logger.error(f"音频文件不存在: {audio_path}")
            if callback:
                callback(str(audio_path), None, f"音频文件不存在: {audio_path}")
            return None
        
        # 检查音频时长是否超过限制
        max_duration = getattr(config, 'ASR_MAX_AUDIO_DURATION', 3600)
        duration = self.get_audio_duration(audio_path)
        
        if duration is not None and duration > max_duration:
            error_msg = f"音频时长 ({duration:.1f}秒) 超过限制 ({max_duration}秒)"
            logger.warning(error_msg)
            if callback:
                callback(str(audio_path), None, error_msg)
            return None
        
        # 创建回调函数
        def on_finished(path: str, text: str):
            if callback:
                callback(path, text, None)

        def on_error(path: str, error: str):
            if callback:
                callback(path, None, error)

        def on_progress(progress: int, status: str):
            if progress_callback:
                progress_callback(progress, status)

        # 创建转录工作线程
        worker = AudioTranscribeWorker(
            audio_path,
            on_finished=on_finished,
            on_error=on_error,
            on_progress=on_progress
        )

        # 启动工作线程
        worker.start()
        
        logger.info(f"已启动异步转录任务: {audio_path}")
        return worker


_recorder_instance: Optional[AudioRecorder] = None


def get_recorder() -> AudioRecorder:
    """获取录音器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = AudioRecorder()
    return _recorder_instance


class AudioTranscribeWorker(threading.Thread):
    """
    音频转录工作线程

    在后台线程中执行音频转录任务，避免阻塞主线程
    """

    def __init__(self, audio_path: Path,
                 on_finished: Callable[[str, str], None] = None,
                 on_error: Callable[[str, str], None] = None,
                 on_progress: Callable[[int, str], None] = None):
        """
        初始化转录工作线程

        Args:
            audio_path: 音频文件路径
            on_finished: 转录完成回调函数 (audio_path: str, text: str)
            on_error: 转录错误回调函数 (audio_path: str, error: str)
            on_progress: 转录进度回调函数 (progress: int, status: str)
        """
        super().__init__(daemon=True)
        self._audio_path = Path(audio_path) if isinstance(audio_path, str) else audio_path
        self._on_finished = on_finished
        self._on_error = on_error
        self._on_progress = on_progress
        self._stop_event = threading.Event()
    
    def run(self):
        """执行转录任务"""
        try:
            # 发送开始进度
            if self._on_progress:
                self._on_progress(0, "开始转录...")

            # 检查是否被取消
            if self._stop_event.is_set():
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录已取消")
                return

            # 检查音频文件是否存在
            if not self._audio_path.exists():
                if self._on_error:
                    self._on_error(str(self._audio_path), f"音频文件不存在: {self._audio_path}")
                return

            # 发送进度
            if self._on_progress:
                self._on_progress(10, "正在加载音频文件...")

            # 检查是否被取消
            if self._stop_event.is_set():
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录已取消")
                return

            # 发送进度
            if self._on_progress:
                self._on_progress(30, "正在进行语音识别...")

            # 执行转录
            result = transcribe_audio_with_onnx(self._audio_path)

            # 检查是否被取消
            if self._stop_event.is_set():
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录已取消")
                return

            # 发送完成进度
            if self._on_progress:
                self._on_progress(100, "转录完成")

            if result is not None:
                if self._on_finished:
                    self._on_finished(str(self._audio_path), result)
            else:
                if self._on_error:
                    self._on_error(str(self._audio_path), "转录失败,返回空结果")

        except Exception as e:
            logger.exception(f"转录过程中发生错误: {e}")
            if self._on_error:
                self._on_error(str(self._audio_path), str(e))

    def request_interruption(self):
        """请求取消转录任务"""
        self._stop_event.set()

    def isInterruptionRequested(self):
        """检查是否已请求取消"""
        return self._stop_event.is_set()