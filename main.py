import sys

from logger import setup_logger, install_exception_hook, get_logger
from database import init_db
from memory.migration import run_migration, is_migration_completed
from ui import main as main_desktop_agent
from ui_skill_agent import main as main_skill_agent


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
    
    try:
        main_skill_agent()
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        raise
    finally:
        logger.info("程序退出")


if __name__ == "__main__":
    main()
