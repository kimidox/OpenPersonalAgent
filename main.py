import sys
from pathlib import Path

from logger import setup_logger, install_exception_hook, get_logger
from database import init_db, engine
from sqlalchemy import text
from memory.migration import run_migration, is_migration_completed
from memory.reindex_fts import reindex_all_memory_segments
from ui import main as main_desktop_agent
from ui_skill_agent import main as main_skill_agent


FTS_REINDEX_FLAG = Path("PersonalData/.fts_reindexed")


def is_fts_reindexed() -> bool:
    return FTS_REINDEX_FLAG.exists()


def mark_fts_reindexed() -> None:
    FTS_REINDEX_FLAG.parent.mkdir(parents=True, exist_ok=True)
    FTS_REINDEX_FLAG.touch()


def main() -> None:
    logger = setup_logger()
    logger.info("=" * 50)
    logger.info("程序启动")
    logger.info(f"打包环境: {getattr(sys, 'frozen', False)}")
    
    install_exception_hook()
    
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.exception(f"数据库初始化失败: {e}")
        raise
    
    if not is_migration_completed():
        try:
            logger.info("开始记忆数据迁移...")
            result = run_migration()
            logger.info(f"记忆数据迁移完成: {result}")
        except Exception as e:
            logger.exception(f"记忆数据迁移失败: {e}")
    
    # 检查并执行 FTS 重新索引
    if not is_fts_reindexed():
        try:
            logger.info("开始 FTS 索引重建（jieba分词）...")
            reindex_all_memory_segments()
            mark_fts_reindexed()
            logger.info("FTS 索引重建完成")
        except Exception as e:
            logger.exception(f"FTS 索引重建失败: {e}")
    
    try:
        main_skill_agent()
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        raise
    finally:
        logger.info("程序退出")


if __name__ == "__main__":
    main()
