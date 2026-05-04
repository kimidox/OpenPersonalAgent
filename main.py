import sys

from logger import setup_logger, install_exception_hook, get_logger
from database import init_db
from ui import main as main_desktop_agent
from ui_skill_agent import main as main_skill_agent


def main() -> None:
    # 初始化日志
    logger = setup_logger()
    logger.info("=" * 50)
    logger.info("程序启动")
    logger.info(f"打包环境: {getattr(sys, 'frozen', False)}")
    
    # 安装全局异常钩子
    install_exception_hook()
    
    # 初始化数据库表结构
    try:
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.exception(f"数据库初始化失败: {e}")
        raise
    
    try:
        main_skill_agent()
        # main_desktop_agent()
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        raise
    finally:
        logger.info("程序退出")


if __name__ == "__main__":
    main()
