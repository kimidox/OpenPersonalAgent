import argparse
import sys
from pathlib import Path

from logger import setup_logger, install_exception_hook, get_logger
from database import init_db
from memory.migration import is_migration_completed
# 已迁移到 Flet UI，不再使用 PySide6 版本的 ui 模块
# from ui import main as main_desktop_agent
# from ui_skill_agent import main as main_skill_agent
from ui_flet.main import run_app as main_skill_agent
from recorder import ensure_model_dirs, migrate_models_to_separate_dirs


def parse_args():
    parser = argparse.ArgumentParser(description="PersonalWindowGLM - 个人智能助手")
    parser.add_argument(
        "--background",
        action="store_true",
        help="后台模式启动，仅显示托盘图标，不显示主窗口"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    logger = setup_logger()
    logger.info("=" * 50)
    logger.info("程序启动")
    logger.info(f"打包环境: {getattr(sys, 'frozen', False)}")
    logger.info(f"后台模式: {args.background}")
    
    install_exception_hook()
    
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.exception(f"数据库初始化失败: {e}")
        raise
    
    # 初始化模型目录结构并迁移模型
    try:
        ensure_model_dirs()
        migrate_models_to_separate_dirs()
        logger.info("模型目录初始化和迁移完成")
    except Exception as e:
        logger.exception(f"模型目录初始化失败: {e}")
    
    if not is_migration_completed():
        logger.info("记忆迁移检查通过（迁移功能已禁用）")
    
    try:
        main_skill_agent(background=args.background)
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        raise
    finally:
        logger.info("程序退出")


if __name__ == "__main__":
    main()