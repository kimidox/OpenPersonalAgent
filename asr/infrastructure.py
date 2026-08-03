"""
ASR基础设施模块

此模块负责处理ASR模型的基础设施相关功能，包括模型下载、目录管理、模型迁移等。

职责：
1. 模型下载（download_onnx_model, download_specific_online_model）
2. GPU检测（check_gpu_available）
3. 目录管理（ensure_model_dirs）
4. 模型迁移（migrate_models_to_separate_dirs）
5. 模型类型识别（identify_model_type）

依赖方向：
- infrastructure.py不依赖service.py和recorder.py
- 可依赖model.py（用于模型目录路径）
"""

from __future__ import annotations

import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Optional, Callable

from logger import get_module_logger
from asr.model import (
    get_asr_model_dir,
    get_default_model_dir,
    get_streaming_models_list,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_URL,
)

logger = get_module_logger("asr.infrastructure")


# ============================================================================
# 模型下载函数
# ============================================================================

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


# ============================================================================
# GPU检测函数
# ============================================================================

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


# ============================================================================
# 目录管理函数
# ============================================================================

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


# ============================================================================
# 模型迁移函数
# ============================================================================

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