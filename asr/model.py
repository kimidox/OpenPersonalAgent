"""
ASR模型状态管理模块

此模块负责管理ASR模型的全局状态、配置常量和状态查询函数。
所有模型实例（离线模型和流式模型）都在此模块中维护。

职责：
1. 维护全局模型实例（_onnx_recognizer, _online_recognizer）
2. 定义模型配置常量（STREAMING_MODELS, DEFAULT_MODEL_URL等）
3. 提供状态查询接口（is_onnx_model_loaded等）
4. 管理模型目录路径（get_asr_model_dir等）

依赖方向：
- model.py不依赖service.py和recorder.py
- 可依赖infrastructure.py（用于目录管理）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from logger import get_module_logger
from resource_path import paths

logger = get_module_logger("asr.model")

# ============================================================================
# 全局模型状态变量
# ============================================================================

# 全局 sherpa-onnx 离线模型实例
_onnx_recognizer = None
_onnx_model_path = None
_onnx_device = None  # 当前模型运行设备："cpu" 或 "cuda"

# 全局 sherpa-onnx 流式模型实例
_online_recognizer = None
_online_model_path = None
_online_device = None  # 当前模型运行设备："cpu" 或 "cuda"
_online_stream = None  # 当前识别流

# ============================================================================
# 配置常量
# ============================================================================

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


# ============================================================================
# 状态查询函数
# ============================================================================

def is_onnx_model_loaded() -> bool:
    """
    检查 sherpa-onnx 离线模型是否已加载

    Returns:
        是否已加载
    """
    return _onnx_recognizer is not None


def is_online_model_loaded() -> bool:
    """
    检查 sherpa-onnx 流式模型是否已加载

    Returns:
        是否已加载
    """
    return _online_recognizer is not None


def get_onnx_device() -> Optional[str]:
    """
    获取当前离线模型运行的设备

    Returns:
        设备名称："cpu" 或 "cuda"，如果模型未加载则返回 None
    """
    return _onnx_device


def get_online_device() -> Optional[str]:
    """
    获取流式模型当前运行的设备

    Returns:
        设备名称（"cpu" 或 "cuda"），如果模型未加载则返回 None
    """
    return _online_device


def get_onnx_model_path() -> Optional[str]:
    """
    获取已加载离线模型的路径

    Returns:
        模型路径，如果未加载则返回 None
    """
    return _onnx_model_path


def get_online_model_path() -> Optional[str]:
    """
    获取已加载流式模型的路径

    Returns:
        模型路径，如果未加载则返回 None
    """
    return _online_model_path


# ============================================================================
# 状态设置函数
# ============================================================================

def _set_online_recognizer(recognizer, model_path: str, device: str) -> None:
    """
    设置流式模型状态

    Args:
        recognizer: sherpa-onnx 流式识别器实例
        model_path: 模型路径
        device: 运行设备 ("cpu" 或 "cuda")
    """
    global _online_recognizer, _online_model_path, _online_device
    _online_recognizer = recognizer
    _online_model_path = model_path
    _online_device = device


def _set_onnx_recognizer(recognizer, model_path: str, device: str) -> None:
    """
    设置离线模型状态

    Args:
        recognizer: sherpa-onnx 离线识别器实例
        model_path: 模型路径
        device: 运行设备 ("cpu" 或 "cuda")
    """
    global _onnx_recognizer, _onnx_model_path, _onnx_device
    _onnx_recognizer = recognizer
    _onnx_model_path = model_path
    _onnx_device = device


def _clear_online_recognizer() -> None:
    """
    清除流式模型状态
    """
    global _online_recognizer, _online_model_path, _online_device, _online_stream
    _online_recognizer = None
    _online_model_path = None
    _online_device = None
    _online_stream = None


def _clear_onnx_recognizer() -> None:
    """
    清除离线模型状态
    """
    global _onnx_recognizer, _onnx_model_path, _onnx_device
    _onnx_recognizer = None
    _onnx_model_path = None
    _onnx_device = None


# ============================================================================
# 状态获取函数（用于 service.py 访问 recognizer 实例）
# ============================================================================

def _get_online_recognizer():
    """
    获取当前流式模型识别器实例

    Returns:
        流式识别器实例，如果未加载则返回 None
    """
    return _online_recognizer


def _get_onnx_recognizer():
    """
    获取当前离线模型识别器实例

    Returns:
        离线识别器实例，如果未加载则返回 None
    """
    return _onnx_recognizer


def _get_online_stream():
    """
    获取当前流式识别流实例

    Returns:
        流式识别流实例，如果未创建则返回 None
    """
    return _online_stream


def _set_online_stream(stream) -> None:
    """
    设置流式识别流实例

    Args:
        stream: 流式识别流实例
    """
    global _online_stream
    _online_stream = stream


# ============================================================================
# 目录管理函数
# ============================================================================

def get_default_model_dir() -> Path:
    """
    获取默认模型目录路径

    Returns:
        模型目录路径 (PersonalData/model)
    """
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


# ============================================================================
# 模型列表查询函数
# ============================================================================

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