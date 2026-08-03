"""
ASR服务模块

此模块负责提供ASR模型加载和音频转录的核心业务逻辑。

职责：
1. 模型加载（load_onnx_model, load_online_model）
2. 模型释放（release_onnx_model, release_online_model）
3. 音频转录（transcribe_audio_with_onnx及辅助函数）
4. 流式识别管理（create_online_stream, process_online_stream等）

依赖方向：
- service.py依赖model.py（模型状态管理）和infrastructure.py（下载、GPU检测）
- recorder.py依赖service.py

注意：
- AI-BRANCH-MARKER注释标记了GPU/CPU加载分支，必须保留
- 关键方法应用了结构化日志（trace_id, operation_type, phase）
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Optional, Callable

import config
from logger import get_module_logger
from utils.lazy_loader import scipy_signal

from asr.model import (
    get_asr_model_dir,
    get_default_model_dir,
    DEFAULT_MODEL_NAME,
    DEFAULT_ONLINE_MODEL_NAME,
    _set_online_recognizer,
    _set_onnx_recognizer,
    _clear_online_recognizer,
    _clear_onnx_recognizer,
    _get_online_recognizer,
    _get_onnx_recognizer,
    _get_online_stream,
    _set_online_stream,
)
from asr.infrastructure import (
    download_onnx_model,
    check_gpu_available,
)

logger = get_module_logger("asr.service")


# ============================================================================
# 模型加载函数
# ============================================================================

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
        # AI-BRANCH-MARKER: GPU/CPU加载分支
        # - 存在原因：GPU可能不可用或加载失败，需要降级到CPU
        # - 适用条件：检测到CUDA可用时尝试GPU，失败时降级CPU
        # - 不能合并原因：GPU和CPU使用不同的provider参数
        # - 必须保留规则：必须保留GPU优先尝试和降级逻辑
        try:
            if use_gpu:
                if callback:
                    callback(92, "尝试加载到 GPU...")
                logger.info("尝试使用 CUDA GPU 加载模型")
                recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    paraformer=str(model_file),
                    tokens=str(tokens_file),
                    num_threads=4,
                    sample_rate=16000,
                    decoding_method="greedy_search",
                    provider="cuda",
                )
                _set_onnx_recognizer(recognizer, str(model_path), "cuda")
                device = "cuda"
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
            recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=str(model_file),
                tokens=str(tokens_file),
                num_threads=4,
                sample_rate=16000,
                decoding_method="greedy_search",
            )
            _set_onnx_recognizer(recognizer, str(model_path), "cpu")
            device = "cpu"
            logger.info("模型加载到 CPU")

        if callback:
            callback(100, f"模型加载完成 ({device.upper()})")

        logger.info(f"sherpa-onnx 模型加载完成: {model_file}, 设备: {device}")
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
        # AI-BRANCH-MARKER: GPU/CPU加载分支
        # - 存在原因：GPU可能不可用或加载失败，需要降级到CPU
        # - 适用条件：检测到CUDA可用时尝试GPU，失败时降级CPU
        # - 不能合并原因：GPU和CPU使用不同的provider参数
        # - 必须保留规则：必须保留GPU优先尝试和降级逻辑
        try:
            if use_gpu:
                if callback:
                    callback(92, "尝试加载到 GPU...")
                logger.info("尝试使用 CUDA GPU 加载流式模型")

                if model_type == "transducer":
                    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
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
                    recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
                        encoder=str(encoder_file),
                        decoder=str(decoder_file),
                        tokens=str(tokens_file),
                        num_threads=4,
                        sample_rate=16000,
                        decoding_method="greedy_search",
                        provider="cuda",
                    )

                _set_online_recognizer(recognizer, str(model_path), "cuda")
                device = "cuda"
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
                recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    encoder=str(encoder_file),
                    decoder=str(decoder_file),
                    joiner=str(joiner_file),
                    tokens=str(tokens_file),
                    num_threads=4,
                    sample_rate=16000,
                    decoding_method="greedy_search",
                )
            else:  # paraformer
                recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
                    encoder=str(encoder_file),
                    decoder=str(decoder_file),
                    tokens=str(tokens_file),
                    num_threads=4,
                    sample_rate=16000,
                    decoding_method="greedy_search",
                )

            _set_online_recognizer(recognizer, str(model_path), "cpu")
            device = "cpu"
            logger.info(f"流式 {model_type} 模型加载到 CPU")

        if callback:
            callback(100, f"流式模型加载完成 ({device.upper()})")

        logger.info(f"sherpa-onnx 流式模型加载完成: {model_path}, 设备: {device}")
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


# ============================================================================
# 模型释放函数
# ============================================================================

def release_onnx_model():
    """释放已加载的 sherpa-onnx 模型以节省内存"""
    logger.info("释放 sherpa-onnx 模型...")

    recognizer = _get_onnx_recognizer()
    if recognizer is not None:
        try:
            del recognizer
        except Exception as e:
            logger.warning(f"清理模型资源时发生错误: {e}")

    _clear_onnx_recognizer()
    logger.info("sherpa-onnx 模型已释放")


def release_online_model():
    """释放已加载的 sherpa-onnx 流式模型以节省内存"""
    logger.info("释放 sherpa-onnx 流式模型...")

    # 先销毁识别流
    stream = _get_online_stream()
    if stream is not None:
        try:
            del stream
        except Exception as e:
            logger.warning(f"销毁识别流时发生错误: {e}")

    recognizer = _get_online_recognizer()
    if recognizer is not None:
        try:
            del recognizer
        except Exception as e:
            logger.warning(f"清理流式模型资源时发生错误: {e}")

    _clear_online_recognizer()
    logger.info("sherpa-onnx 流式模型已释放")


# ============================================================================
# 音频转录函数
# ============================================================================

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

    recognizer = _get_onnx_recognizer()
    if recognizer is None:
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

    recognizer = _get_onnx_recognizer()
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, audio_array)
    recognizer.decode_stream(stream)
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
    recognizer = _get_online_recognizer()
    if recognizer is None:
        logger.error("流式模型未加载，无法创建识别流")
        return None

    try:
        stream = recognizer.create_stream()
        _set_online_stream(stream)
        logger.info("已创建实时识别流")
        return stream
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
    stream = _get_online_stream()
    if stream is None:
        logger.error("识别流未创建")
        return False

    recognizer = _get_online_recognizer()
    if recognizer is None:
        logger.error("流式模型未加载")
        return False

    try:
        import numpy as np

        # 转换为 numpy 数组
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        # 转换为 float32 并归一化
        audio_float = audio_array.astype(np.float32) / 32768.0

        # 输入识别流
        stream = _get_online_stream()
        stream.accept_waveform(sample_rate, audio_float)

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
    stream = _get_online_stream()
    if stream is None:
        return None

    recognizer = _get_online_recognizer()
    if recognizer is None:
        return None

    try:
        # 检查是否有结果
        if recognizer.is_ready(stream):
            recognizer.decode_stream(stream)

        result = recognizer.get_result(stream)
        if result:
            return result.strip()

        return None
    except Exception as e:
        logger.exception(f"获取识别结果失败: {e}")
        return None


def destroy_online_stream():
    """销毁当前识别流，释放资源"""
    stream = _get_online_stream()
    if stream is not None:
        try:
            # sherpa-onnx 的 stream 没有显式的 destroy 方法
            # 直接设置为 None 即可
            _set_online_stream(None)
            logger.info("已销毁实时识别流")
        except Exception as e:
            logger.warning(f"销毁识别流时发生错误: {e}")
            _set_online_stream(None)