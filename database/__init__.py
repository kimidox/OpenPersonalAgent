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


def _migrate_scheduled_tasks():
    """
    为 scheduled_tasks 表添加缺失的列
    """
    with engine.connect() as conn:
        # 检查列是否已存在，不存在则添加
        # 1. execution_type 列
        try:
            conn.execute(text("SELECT execution_type FROM scheduled_tasks LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN execution_type TEXT DEFAULT 'notification'"))
        
        # 2. execution_chain 列
        try:
            conn.execute(text("SELECT execution_chain FROM scheduled_tasks LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN execution_chain TEXT"))
        
        # 3. source_conversation_id 列
        try:
            conn.execute(text("SELECT source_conversation_id FROM scheduled_tasks LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN source_conversation_id TEXT"))
        
        # 4. skill_ids 列
        try:
            conn.execute(text("SELECT skill_ids FROM scheduled_tasks LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN skill_ids TEXT"))
        
        conn.commit()


def _migrate_conversations_type():
    """
    为 conversations 表添加 type 列
    """
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT type FROM conversations LIMIT 1"))
        except Exception:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN type TEXT DEFAULT 'agent_conversation'"))
        conn.commit()


def init_db():
    Base.metadata.create_all(engine)
    _create_fts_tables()
    _migrate_scheduled_tasks()
    _migrate_conversations_type()


if __name__ == '__main__':
    init_db()
