from __future__ import annotations

from pathlib import Path

from config import WORKER_DIR

from logger import get_module_logger

logger = get_module_logger("Migration")


MIGRATION_FLAG_FILE = ".memory_migration_completed"


def is_migration_completed() -> bool:
    flag_path = Path(WORKER_DIR) / MIGRATION_FLAG_FILE
    return flag_path.exists()


def mark_migration_completed() -> None:
    flag_path = Path(WORKER_DIR) / MIGRATION_FLAG_FILE
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.touch()


if __name__ == "__main__":
    logger.info("Migration module loaded. Use is_migration_completed() to check status.")
