from __future__ import annotations

from pathlib import Path

from config import WORKER_DIR
from resource_path import paths
from memory.searcher import MemorySearcher
from memory.long_term_memory import LongTermMemory
from skill.memory_summarizer import migrate_skill_memory_from_file
from skill.loader import discover_skill_files, load_skill_from_path
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


def run_migration(
    user_id: str = "default",
    searcher: MemorySearcher | None = None,
) -> dict[str, int]:
    """
    执行数据迁移。

    Args:
        user_id: 用户ID
        searcher: MemorySearcher 实例（可选）

    Returns:
        迁移结果统计
    """
    if is_migration_completed():
        logger.info("迁移已完成，跳过")
        return {"long_term_memory": 0, "skill_memory": 0, "status": "skipped"}

    logger.info("开始数据迁移...")
    _searcher = searcher or MemorySearcher()
    result = {
        "long_term_memory": 0,
        "skill_memory": 0,
        "status": "completed",
    }

    memory_file_path = Path(WORKER_DIR) / "MEMORY.md"
    if memory_file_path.exists():
        ltm = LongTermMemory(
            memory_file_path=str(memory_file_path),
            user_id=user_id,
            searcher=_searcher,
        )
        result["long_term_memory"] = ltm.migrate_from_file()
        logger.info(f"长期记忆迁移完成: {result['long_term_memory']} 条")

    skills_dir = paths.get_skills_dir()
    if skills_dir.exists():
        skill_files = discover_skill_files(skills_dir)
        for skill_path in skill_files:
            try:
                skill = load_skill_from_path(skill_path)
                skill_package_name = skill_path.parent.name
                skill_memory_path = skills_dir / skill_package_name / "skill_memory.md"
                
                if skill_memory_path.exists():
                    migrated = migrate_skill_memory_from_file(
                        skill_id=skill.skill_id,
                        skill_memory_path=skill_memory_path,
                        searcher=_searcher,
                    )
                    if migrated > 0:
                        result["skill_memory"] += migrated
                        logger.info(f"Skill {skill.skill_id} 记忆迁移完成: {migrated} 条")
            except Exception as e:
                logger.error(f"迁移 Skill {skill_path} 失败: {e}")

    mark_migration_completed()
    logger.info(f"迁移完成: {result}")
    return result


if __name__ == "__main__":
    run_migration()
