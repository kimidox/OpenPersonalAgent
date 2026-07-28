import argparse
import sys
import time
from pathlib import Path

from logger import setup_logger, install_exception_hook, get_logger
from database import init_db
from memory.migration import is_migration_completed
# 已迁移到 Flet UI，不再使用 PySide6 版本的 ui 模块
# from ui import main as main_desktop_agent
# from ui_skill_agent import main as main_skill_agent
from ui_flet.main import run_app as main_skill_agent
from recorder import ensure_model_dirs, migrate_models_to_separate_dirs

# 性能监控
from performance import start_monitoring, stop_monitoring, track_time, record_success, record_failure


def parse_args():
    parser = argparse.ArgumentParser(description="PersonalWindowGLM - 个人智能助手")
    parser.add_argument(
        "--background",
        action="store_true",
        help="后台模式启动，仅显示托盘图标，不显示主窗口"
    )
    return parser.parse_args()


def main() -> None:
    # 记录启动开始时间
    app_start_time = time.time()

    args = parse_args()

    logger = setup_logger()
    logger.info("=" * 50)
    logger.info("程序启动")
    logger.info(f"打包环境: {getattr(sys, 'frozen', False)}")
    logger.info(f"后台模式: {args.background}")

    # 启动性能监控
    try:
        start_monitoring()
        logger.info("性能监控已启动")
    except Exception as e:
        logger.warning(f"性能监控启动失败: {e}")

    install_exception_hook()

    # 数据库初始化（跟踪时间）
    try:
        with track_time("db_init"):
            init_db()
        logger.info("数据库初始化完成")
        record_success("db_init")
    except Exception as e:
        logger.exception(f"数据库初始化失败: {e}")
        record_failure("db_init")
        raise

    # 初始化模型目录结构并迁移模型（跟踪时间）
    try:
        with track_time("model_init"):
            ensure_model_dirs()
            migrate_models_to_separate_dirs()
        logger.info("模型目录初始化和迁移完成")
        record_success("model_init")
    except Exception as e:
        logger.exception(f"模型目录初始化失败: {e}")
        record_failure("model_init")

    if not is_migration_completed():
        logger.info("记忆迁移检查通过（迁移功能已禁用）")

    # 计算并记录启动时间
    startup_duration = (time.time() - app_start_time) * 1000  # 毫秒
    logger.info(f"应用启动完成，总耗时: {startup_duration:.0f}ms")

    try:
        main_skill_agent(background=args.background)
    except Exception as e:
        logger.exception(f"程序异常退出: {e}")
        raise
    finally:
        # 停止性能监控
        try:
            stop_monitoring()
            logger.info("性能监控已停止")
        except Exception as e:
            logger.warning(f"性能监控停止失败: {e}")

        logger.info("程序退出")


if __name__ == "__main__":
    main()