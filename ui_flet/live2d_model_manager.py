"""
Live2D 模型管理器 - 扫描和管理 PersonalData/2DLiveFiles 目录下的 Live2D 模型

功能:
- 扫描目录寻找有效的 Live2D 模型（查找 .model3.json 文件）
- 解析模型元数据（名称、可用动作等）
- 返回可用模型列表及其信息
- 验证模型文件是否存在（moc3、贴图等）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from resource_path import paths
from logger import get_module_logger

logger = get_module_logger("Live2DModelManager")

LIVE2D_DIR_NAME = "2DLiveFiles"
MODEL3_JSON_SUFFIX = ".model3.json"


@dataclass
class Live2DModelInfo:
    """Live2D 模型信息"""
    name: str
    model_dir: Path
    model_json: Path  # path to .model3.json
    available_motions: list[str] = field(default_factory=list)  # list of motion group names
    has_physics: bool = False


def _get_live2d_base_dir() -> Path:
    """获取 Live2D 模型根目录"""
    return paths.personal_data_dir / LIVE2D_DIR_NAME


def _find_model3_json(model_dir: Path) -> Optional[Path]:
    """在模型目录中查找 .model3.json 文件"""
    logger.debug(f"_find_model3_json: 开始查找，模型目录: {model_dir}")
    
    if not model_dir.is_dir():
        logger.warning(f"_find_model3_json: 目录不存在或不是目录: {model_dir}")
        return None

    # 直接在目录下查找
    logger.debug(f"_find_model3_json: 在目录下直接查找 {MODEL3_JSON_SUFFIX} 文件...")
    for f in model_dir.iterdir():
        logger.debug(f"_find_model3_json: 检查文件: {f.name}, 是否匹配: {f.name.endswith(MODEL3_JSON_SUFFIX)}")
        if f.is_file() and f.name.endswith(MODEL3_JSON_SUFFIX):
            logger.info(f"_find_model3_json: ✓ 在目录下找到模型文件: {f}")
            return f

    # 可能在一级子目录中
    logger.debug(f"_find_model3_json: 在一级子目录中查找...")
    for sub in model_dir.iterdir():
        if sub.is_dir():
            logger.debug(f"_find_model3_json: 检查子目录: {sub.name}")
            for f in sub.iterdir():
                logger.debug(f"_find_model3_json: 检查子目录文件: {f.name}, 是否匹配: {f.name.endswith(MODEL3_JSON_SUFFIX)}")
                if f.is_file() and f.name.endswith(MODEL3_JSON_SUFFIX):
                    logger.info(f"_find_model3_json: ✓ 在子目录中找到模型文件: {f}")
                    return f

    logger.warning(f"_find_model3_json: ✗ 未找到 {MODEL3_JSON_SUFFIX} 文件，目录: {model_dir}")
    return None


def _parse_motion_groups(model_json_data: dict) -> list[str]:
    """从 model3.json 中解析可用动作组名称"""
    motions = []
    motion_groups = model_json_data.get("FileReferences", {}).get("Motions", {})
    if isinstance(motion_groups, dict):
        motions = sorted(motion_groups.keys())
    elif isinstance(motion_groups, list):
        # 有些模型使用数组格式
        motions = [f"motion_{i}" for i in range(len(motion_groups))]
    return motions


def _has_physics_file(model_json_data: dict, model_dir: Path) -> bool:
    """检查模型是否有物理配置文件"""
    phys_path = model_json_data.get("FileReferences", {}).get("Physics")
    if phys_path:
        phys_full = model_dir / phys_path
        return phys_full.exists()
    return False


def _validate_model_files(model_json_data: dict, model_dir: Path) -> bool:
    """验证模型必需文件是否存在"""
    file_refs = model_json_data.get("FileReferences", {})

    # 检查 moc3 文件
    moc_path = file_refs.get("Moc")
    if not moc_path:
        logger.warning("模型缺少 Moc 文件引用")
        return False
    if not (model_dir / moc_path).exists():
        logger.warning(f"Moc 文件不存在: {moc_path}")
        return False

    # 检查贴图文件
    textures = file_refs.get("Textures", [])
    if not textures:
        logger.warning("模型缺少贴图文件")
        return False
    for tex_path in textures:
        if not (model_dir / tex_path).exists():
            logger.warning(f"贴图文件不存在: {tex_path}")
            return False

    return True


def get_model_info(model_dir: Path) -> Optional[Live2DModelInfo]:
    """
    解析单个模型目录，返回模型信息

    Args:
        model_dir: 模型目录路径

    Returns:
        Live2DModelInfo 或 None（如果模型无效）
    """
    if not model_dir.is_dir():
        return None

    model_json_path = _find_model3_json(model_dir)
    if model_json_path is None:
        logger.debug(f"未找到 model3.json: {model_dir}")
        return None

    try:
        with open(model_json_path, "r", encoding="utf-8") as f:
            model_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"解析模型 JSON 失败 {model_json_path}: {e}")
        return None

    # 验证必需文件
    if not _validate_model_files(model_data, model_dir):
        logger.warning(f"模型文件不完整: {model_dir}")
        return None

    # 解析信息
    name = model_data.get("Name", model_dir.name)
    motions = _parse_motion_groups(model_data)
    has_phys = _has_physics_file(model_data, model_dir)

    return Live2DModelInfo(
        name=name,
        model_dir=model_dir,
        model_json=model_json_path,
        available_motions=motions,
        has_physics=has_phys,
    )


def scan_models() -> list[Live2DModelInfo]:
    """
    扫描 PersonalData/2DLiveFiles 目录寻找所有可用的 Live2D 模型

    Returns:
        有效的 Live2DModelInfo 列表
    """
    base_dir = _get_live2d_base_dir()

    if not base_dir.exists():
        logger.info(f"Live2D 模型目录不存在: {base_dir}")
        return []

    if not base_dir.is_dir():
        logger.warning(f"Live2D 模型路径不是目录: {base_dir}")
        return []

    models = []
    for item in sorted(base_dir.iterdir()):
        if not item.is_dir():
            continue

        info = get_model_info(item)
        if info is not None:
            models.append(info)
            logger.info(f"发现 Live2D 模型: {info.name} (动作: {info.available_motions})")
        else:
            logger.debug(f"跳过无效模型目录: {item.name}")

    logger.info(f"共扫描到 {len(models)} 个有效的 Live2D 模型")
    return models


def get_default_model_dir() -> Optional[Path]:
    """
    获取第一个可用的模型目录

    Returns:
        第一个模型的目录路径，如果没有模型则返回 None
    """
    models = scan_models()
    if models:
        return models[0].model_dir
    return None
