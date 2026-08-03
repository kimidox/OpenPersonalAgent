"""
ASR模块统一接口

此模块提供ASR（Automatic Speech Recognition，自动语音识别）功能的统一接口。
所有公共接口都通过此模块导出，保持向后兼容性。

模块结构：
- model.py: 模型状态管理、配置常量
- infrastructure.py: 模型下载、目录管理、迁移
- service.py: 模型加载、音频转录
- recorder.py: 音频录音管理

使用示例：
    # 导入模型加载函数
    from asr import load_onnx_model, load_online_model

    # 导入录音器
    from asr import AudioRecorder, get_recorder

    # 导入转录函数
    from asr import transcribe_audio_with_onnx

    # 检查模型状态
    from asr import is_onnx_model_loaded, get_onnx_device
"""

# ============================================================================
# 从各子模块导出所有公共接口
# ============================================================================

# 从model.py导出
from asr.model import (
    # 状态查询函数
    is_onnx_model_loaded,
    is_online_model_loaded,
    get_onnx_device,
    get_online_device,
    get_onnx_model_path,
    get_online_model_path,

    # 目录管理函数
    get_asr_model_dir,
    get_default_model_dir,

    # 模型列表查询函数
    get_streaming_models_list,
    get_default_model_key,

    # 配置常量
    STREAMING_MODELS,
    DEFAULT_MODEL_URL,
    DEFAULT_MODEL_NAME,
    DEFAULT_ONLINE_MODEL_NAME,
)

# 从infrastructure.py导出
from asr.infrastructure import (
    # 模型下载函数
    download_onnx_model,
    download_specific_online_model,

    # GPU检测函数
    check_gpu_available,

    # 目录管理函数
    ensure_model_dirs,

    # 模型迁移函数
    identify_model_type,
    migrate_models_to_separate_dirs,
)

# 从service.py导出
from asr.service import (
    # 模型加载函数
    load_onnx_model,
    load_online_model,

    # 模型释放函数
    release_onnx_model,
    release_online_model,

    # 音频转录函数
    transcribe_audio_with_onnx,

    # 流式识别管理函数
    create_online_stream,
    process_online_stream,
    get_online_stream_result,
    destroy_online_stream,
)

# 从recorder.py导出
from asr.recorder import (
    # 录音器类
    AudioRecorder,
    AudioTranscribeWorker,

    # 单例函数
    get_recorder,
)


# ============================================================================
# 定义__all__列表
# ============================================================================

__all__ = [
    # model.py - 状态查询
    'is_onnx_model_loaded',
    'is_online_model_loaded',
    'get_onnx_device',
    'get_online_device',
    'get_onnx_model_path',
    'get_online_model_path',

    # model.py - 目录管理
    'get_asr_model_dir',
    'get_default_model_dir',

    # model.py - 模型列表
    'get_streaming_models_list',
    'get_default_model_key',

    # model.py - 配置常量
    'STREAMING_MODELS',
    'DEFAULT_MODEL_URL',
    'DEFAULT_MODEL_NAME',
    'DEFAULT_ONLINE_MODEL_NAME',

    # infrastructure.py - 模型下载
    'download_onnx_model',
    'download_specific_online_model',

    # infrastructure.py - GPU检测
    'check_gpu_available',

    # infrastructure.py - 目录管理
    'ensure_model_dirs',

    # infrastructure.py - 模型迁移
    'identify_model_type',
    'migrate_models_to_separate_dirs',

    # service.py - 模型加载
    'load_onnx_model',
    'load_online_model',

    # service.py - 模型释放
    'release_onnx_model',
    'release_online_model',

    # service.py - 音频转录
    'transcribe_audio_with_onnx',

    # service.py - 流式识别
    'create_online_stream',
    'process_online_stream',
    'get_online_stream_result',
    'destroy_online_stream',

    # recorder.py - 录音器
    'AudioRecorder',
    'AudioTranscribeWorker',
    'get_recorder',
]