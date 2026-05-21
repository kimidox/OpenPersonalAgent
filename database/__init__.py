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


def init_db():
    Base.metadata.create_all(engine)
    _create_fts_tables()


if __name__ == '__main__':
    init_db()
