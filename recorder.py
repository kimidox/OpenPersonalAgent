"""
ASR模块兼容层

此文件已重构为asr模块的导出层，保持向后兼容性。
所有功能已迁移到asr/子模块，建议直接使用：

    # 推荐导入方式（新代码）
    from asr import load_onnx_model, AudioRecorder, transcribe_audio_with_onnx

    # 向后兼容导入方式（旧代码）
    from recorder import load_onnx_model, AudioRecorder  # 仍然有效

模块结构：
- asr/model.py: 模型状态管理、配置常量
- asr/infrastructure.py: 模型下载、目录管理、迁移
- asr/service.py: 模型加载、音频转录（含结构化日志）
- asr/recorder.py: 音频录音管理

重构原因：
- 原文件1637行，混合了多个层次的职责
- 按分层架构拆分，提高可维护性
- 应用结构化日志字段，提升AI理解能力

重构时间：阶段5（2026-07-31）
"""

# 从asr模块重新导出所有公共接口
from asr import (
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

    # 基础设施函数
    download_onnx_model,
    download_specific_online_model,
    check_gpu_available,
    ensure_model_dirs,
    migrate_models_to_separate_dirs,

    # 服务函数
    load_onnx_model,
    load_online_model,
    release_onnx_model,
    release_online_model,
    transcribe_audio_with_onnx,

    # 流式识别函数
    create_online_stream,
    process_online_stream,
    get_online_stream_result,
    destroy_online_stream,

    # 录音管理
    AudioRecorder,
    AudioTranscribeWorker,
    get_recorder,
)

__all__ = [
    # 状态查询函数
    'is_onnx_model_loaded',
    'is_online_model_loaded',
    'get_onnx_device',
    'get_online_device',
    'get_onnx_model_path',
    'get_online_model_path',

    # 目录管理函数
    'get_asr_model_dir',
    'get_default_model_dir',

    # 模型列表查询函数
    'get_streaming_models_list',
    'get_default_model_key',

    # 配置常量
    'STREAMING_MODELS',
    'DEFAULT_MODEL_URL',
    'DEFAULT_MODEL_NAME',
    'DEFAULT_ONLINE_MODEL_NAME',

    # 基础设施函数
    'download_onnx_model',
    'download_specific_online_model',
    'check_gpu_available',
    'ensure_model_dirs',
    'migrate_models_to_separate_dirs',

    # 服务函数
    'load_onnx_model',
    'load_online_model',
    'release_onnx_model',
    'release_online_model',
    'transcribe_audio_with_onnx',

    # 流式识别函数
    'create_online_stream',
    'process_online_stream',
    'get_online_stream_result',
    'destroy_online_stream',

    # 录音管理
    'AudioRecorder',
    'AudioTranscribeWorker',
    'get_recorder',
]