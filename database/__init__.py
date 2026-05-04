"""
数据库模块 - 使用 PathManager 统一管理数据库路径

数据库文件位置:
- 开发环境: PersonalData/data/app.db
- 打包环境: %APPDATA%/OpenPersonalAgent/data/app.db
"""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resource_path import paths
from database.models import Base

DB_FILE = paths.get_database_path("app.db")

# 确保数据库目录存在
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

# Windows 上 SQLAlchemy 需要使用正斜杠
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


def init_db():
    Base.metadata.create_all(engine)


if __name__ == '__main__':
    init_db()
