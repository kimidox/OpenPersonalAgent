#!/usr/bin/env python3
"""
模型下载脚本

用于手动下载 TTS（文本转语音）模型。

使用方法：
    python download_models.py --tts            # 下载 TTS 模型（默认中文）
    python download_models.py --tts zh         # 下载中文 TTS 模型
    python download_models.py --tts zh_en      # 下载中英文 TTS 模型
    python download_models.py --list           # 列出可用的模型
    python download_models.py --check          # 检查已下载的模型
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any

from logger import get_module_logger

logger = get_module_logger("download_models")

# 模型配置
MODEL_CONFIGS = {
    "tts_zh": {
        "name": "TTS 中文模型",
        "model_id": "sherpa-onnx-vits-zh-ll",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2",
        "model_name": "sherpa-onnx-vits-zh-ll",
        "description": "纯中文 TTS 模型，支持5个音色（苏映雪、顾念、付思雨、冰娇、巴总）",
        "size_mb": 150,
        "required_files": ["model.onnx", "tokens.txt", "lexicon.txt"],
    },
    "tts_zh_en": {
        "name": "TTS 中英文模型",
        "model_id": "vits-melo-tts-zh_en",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2",
        "model_name": "vits-melo-tts-zh_en",
        "description": "中英文混合 TTS 模型，支持中英文混合朗读",
        "size_mb": 200,
        "required_files": ["model.onnx", "model.int8.onnx", "tokens.txt", "lexicon.txt"],
    },
}


def get_model_dir() -> Path:
    """获取模型存储目录"""
    # 尝试从 resource_path 获取路径
    try:
        from resource_path import paths
        model_dir = paths.personal_data_dir / "model"
    except ImportError:
        # 如果 resource_path 不可用，使用默认路径
        model_dir = Path(__file__).parent / "PersonalData" / "model"
    
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def format_size(size_mb: float) -> str:
    """格式化文件大小"""
    if size_mb >= 1000:
        return f"{size_mb / 1000:.2f} GB"
    return f"{size_mb:.0f} MB"


def print_progress(progress: int, status: str, model_name: str = ""):
    """打印下载进度（保留print用于终端进度条）"""
    bar_width = 40
    filled = int(bar_width * progress / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    
    prefix = f"[{model_name}] " if model_name else ""
    print(f"\r{prefix}{bar} {progress}% - {status}", end="", flush=True)
    if progress == 100:
        print()  # 完成时换行


def download_model(model_key: str, model_dir: Path, show_progress: bool = True) -> Optional[Path]:
    """
    下载指定的模型
    
    Args:
        model_key: 模型键名（asr, tts_zh, tts_zh_en）
        model_dir: 模型存储目录
        show_progress: 是否显示进度条
    
    Returns:
        模型目录路径，如果失败则返回 None
    """
    if model_key not in MODEL_CONFIGS:
        logger.error("未知的模型类型 '%s'", model_key)
        return None
    
    config = MODEL_CONFIGS[model_key]
    target_dir = model_dir / config["model_name"]
    
    # 检查模型是否已存在
    if target_dir.exists():
        # 检查必要文件是否存在
        missing_files = []
        for req_file in config["required_files"]:
            if not (target_dir / req_file).exists():
                missing_files.append(req_file)
        
        if not missing_files:
            logger.info("%s 已存在: %s", config['name'], target_dir)
            return target_dir
        else:
            logger.warning("%s 目录存在但缺少文件: %s", config['name'], missing_files)
            logger.info("将重新下载...")
    
    logger.info("下载 %s", config['name'])
    logger.info("  描述: %s", config['description'])
    logger.info("  大小: %s", format_size(config['size_mb']))
    logger.info("  URL: %s", config['url'])
    logger.info("  目标: %s", target_dir)
    
    try:
        # 下载压缩包
        tar_path = model_dir / f"{config['model_name']}.tar.bz2"
        
        if show_progress:
            print_progress(0, "开始下载...", config["model_id"])
        
        def progress_callback(block_num, block_size, total_size):
            if show_progress and total_size > 0:
                progress = int((block_num * block_size / total_size) * 60)
                progress = min(progress, 60)
                downloaded_mb = (block_num * block_size) / (1024 * 1024)
                status = f"已下载 {format_size(downloaded_mb)}"
                print_progress(progress, status, config["model_id"])
        
        urllib.request.urlretrieve(config["url"], tar_path, progress_callback)
        
        if show_progress:
            print_progress(65, "下载完成，正在解压...", config["model_id"])
        
        # 解压
        with tarfile.open(tar_path, 'r:bz2') as tar:
            tar.extractall(model_dir)
        
        if show_progress:
            print_progress(90, "解压完成，正在清理...", config["model_id"])
        
        # 删除压缩包
        tar_path.unlink()
        
        if show_progress:
            print_progress(100, "完成!", config["model_id"])
        
        logger.info("%s 下载完成! 路径: %s", config['name'], target_dir)
        
        return target_dir
        
    except Exception as e:
        logger.error("下载失败: %s", e)
        # 清理临时文件
        if tar_path.exists():
            try:
                tar_path.unlink()
            except Exception as e:
                logger.debug("临时文件清理失败: %s", e)
        return None


def check_models(model_dir: Path) -> Dict[str, Any]:
    """
    检查已下载的模型
    
    Returns:
        模型状态字典
    """
    results = {}
    
    for model_key, config in MODEL_CONFIGS.items():
        target_dir = model_dir / config["model_name"]
        status = {
            "name": config["name"],
            "path": str(target_dir),
            "exists": target_dir.exists(),
            "complete": False,
            "missing_files": [],
        }
        
        if target_dir.exists():
            missing_files = []
            for req_file in config["required_files"]:
                if not (target_dir / req_file).exists():
                    missing_files.append(req_file)
            
            status["complete"] = len(missing_files) == 0
            status["missing_files"] = missing_files
        
        results[model_key] = status
    
    return results


def list_available_models():
    """列出可用的模型"""
    logger.info("可用的模型列表:")
    logger.info("=" * 60)
    
    for model_key, config in MODEL_CONFIGS.items():
        logger.info("[%s]", model_key)
        logger.info("  名称: %s", config['name'])
        logger.info("  描述: %s", config['description'])
        logger.info("  大小: %s", format_size(config['size_mb']))
        logger.info("  必要文件: %s", ', '.join(config['required_files']))
    
    logger.info("=" * 60)


def print_model_status(model_dir: Path):
    """打印模型状态"""
    results = check_models(model_dir)
    
    logger.info("已下载的模型状态:")
    logger.info("=" * 60)
    
    for model_key, status in results.items():
        symbol = "✓" if status["complete"] else ("⚠" if status["exists"] else "✗")
        logger.info("%s [%s] %s", symbol, model_key, status['name'])
        logger.info("  路径: %s", status['path'])
        
        if status["exists"]:
            if status["complete"]:
                logger.info("  状态: 完整")
            else:
                logger.warning("  状态: 不完整，缺少文件: %s", status['missing_files'])
        else:
            logger.info("  状态: 未下载")
    
    logger.info("=" * 60)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="模型下载脚本 - 用于手动下载 TTS 模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python download_models.py --tts            # 下载 TTS 模型（默认中文）
  python download_models.py --tts zh         # 下载中文 TTS 模型
  python download_models.py --tts zh_en      # 下载中英文 TTS 模型
  python download_models.py --list           # 列出可用的模型
  python download_models.py --check          # 检查已下载的模型
        """
    )
    
    parser.add_argument(
        "--tts",
        nargs="?",
        const="zh",
        choices=["zh", "zh_en"],
        help="下载 TTS 模型，可选参数: zh（中文）或 zh_en（中英文），默认 zh"
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="下载所有模型（中文TTS + 中英文TTS）"
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出可用的模型"
    )
    
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查已下载的模型状态"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="静默模式，不显示进度条"
    )
    
    args = parser.parse_args()
    
    # 获取模型目录
    model_dir = get_model_dir()
    logger.info("模型存储目录: %s", model_dir)
    
    # 列出可用模型
    if args.list:
        list_available_models()
        return
    
    # 检查模型状态
    if args.check:
        print_model_status(model_dir)
        return
    
    # 确定要下载的模型
    models_to_download = []
    
    if args.all:
        models_to_download = ["tts_zh", "tts_zh_en"]
    elif args.tts:
        if args.tts == "zh":
            models_to_download.append("tts_zh")
        elif args.tts == "zh_en":
            models_to_download.append("tts_zh_en")
    
    # 如果没有指定任何模型，下载默认中文TTS
    if not models_to_download:
        logger.info("未指定具体模型，将下载默认模型（中文TTS）")
        models_to_download = ["tts_zh"]
    
    logger.info("将下载以下模型: %s", ', '.join(models_to_download))
    
    # 下载模型
    success_count = 0
    for model_key in models_to_download:
        result = download_model(model_key, model_dir, show_progress=not args.quiet)
        if result:
            success_count += 1
    
    # 打印最终状态
    logger.info("=" * 60)
    logger.info("下载完成: %d/%d 个模型成功", success_count, len(models_to_download))
    print_model_status(model_dir)
    
    # 返回状态码
    return 0 if success_count == len(models_to_download) else 1


if __name__ == "__main__":
    sys.exit(main())