import argparse
import sys
from pathlib import Path

from logger import setup_logger, install_exception_hook, get_logger
from database import init_db, engine
from sqlalchemy import text
from memory.migration import run_migration, is_migration_completed
from memory.reindex_fts import reindex_all_memory_segments
# 已迁移到 Flet UI，不再使用 PySide6 版本的 ui 模块
# from ui import main as main_desktop_agent
# from ui_skill_agent import main as main_skill_agent
from ui_flet.main import run_app as main_skill_agent
from recorder import ensure_model_dirs, migrate_models_to_separate_dirs


FTS_REINDEX_FLAG = Path("PersonalData/.fts_reindexed")


def is_fts_reindexed() -> bool:
    return FTS_REINDEX_FLAG.exists()


def mark_fts_reindexed() -> None:
    FTS_REINDEX_FLAG.parent.mkdir(parents=True, exist_ok=True)
    FTS_REINDEX_FLAG.touch()


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
        try:
            logger.info("开始记忆数据迁移...")
            result = run_migration()
            logger.info(f"记忆数据迁移完成: {result}")
        except Exception as e:
            logger.exception(f"记忆数据迁移失败: {e}")
    
    if not is_fts_reindexed():
        try:
            logger.info("开始 FTS 索引重建（jieba分词）...")
            reindex_all_memory_segments()
            mark_fts_reindexed()
            logger.info("FTS 索引重建完成")
        except Exception as e:
            logger.exception(f"FTS 索引重建失败: {e}")
    
    try:
        main_skill_agent(background=args.background)
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        raise
    finally:
        logger.info("程序退出")


if __name__ == "__main__":
    main()