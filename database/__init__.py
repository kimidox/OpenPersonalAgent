"""
数据库模块 - 使用 PathManager 统一管理数据库路径

数据库文件位置:
- 开发环境: PersonalData/data/app.db
- 打包环境: %APPDATA%/OpenPersonalAgent/data/app.db
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from resource_path import paths
from database.models import Base

DB_FILE = paths.get_database_path("app.db")

DB_FILE.parent.mkdir(parents=True, exist_ok=True)

db_path_str = DB_FILE.as_posix()

engine = create_engine(
    f'sqlite:///{db_path_str}',
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def get_local_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_session():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def _create_fts_tables():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_segments_fts USING fts5(
                segment_id,
                content,
                tokenize='unicode61'
            )
        """))
        conn.commit()


def _get_existing_columns(table_name: str) -> set[str]:
    """获取表的现有列名集合（单次 PRAGMA table_info）"""
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return {row[1] for row in result}


def _add_missing_columns(table_name: str, columns: dict[str, str]) -> None:
    """
    批量添加缺失的列

    Args:
        table_name: 表名
        columns: {列名: SQL定义} 字典，如 {"execution_type": "TEXT DEFAULT 'notification'"}
    """
    existing = _get_existing_columns(table_name)
    missing = {name: definition for name, definition in columns.items() if name not in existing}

    if not missing:
        return

    with engine.connect() as conn:
        for col_name, col_def in missing.items():
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"))
        conn.commit()


def _migrate_scheduled_tasks():
    """为 scheduled_tasks 表添加缺失的列（批量检查 + 批量添加）"""
    _add_missing_columns("scheduled_tasks", {
        "execution_type": "TEXT DEFAULT 'notification'",
        "execution_chain": "TEXT",
        "source_conversation_id": "TEXT",
        "skill_ids": "TEXT",
    })


def _migrate_conversations():
    """为 conversations 表添加缺失的列（批量检查 + 批量添加）"""
    _add_missing_columns("conversations", {
        "type": "TEXT DEFAULT 'agent_conversation'",
        "default_skills": "TEXT DEFAULT '[]'",
    })


def init_db():
    Base.metadata.create_all(engine)
    _create_fts_tables()
    _migrate_scheduled_tasks()
    _migrate_conversations()


if __name__ == '__main__':
    init_db()
