"""数据库引擎与会话管理。

启动时启用 SQLite WAL 模式，提升并发读性能：
- 读不阻塞写，写不阻塞读
- 班级隔离查询（SELECT）不会因并发写入而阻塞
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_simple_migrations() -> None:
    """轻量列迁移（dev 用）：检测 materials 骨架表并重建为完整业务表。

    add-class-data-isolation 创建了 materials 骨架表（仅 id/class_id/created_at），
    add-material-upload 需扩展为完整业务表。SQLite 的 ALTER TABLE ADD COLUMN 无法
    添加带外键约束的列且无法添加联合索引，骨架表无业务数据，安全 drop 后由
    create_all 重建为最新结构。
    """
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(materials)"))
        col_names = {row[1] for row in result}
        # 骨架表缺少 filename 列 → drop 重建
        if col_names and "filename" not in col_names:
            conn.execute(text("DROP TABLE IF EXISTS materials"))
            conn.commit()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """每个新连接启用 WAL 与合理的同步级别。

    - journal_mode=WAL：读不阻塞写，写不阻塞读，适合班级隔离查询场景
    - synchronous=NORMAL：WAL 模式下安全且高效
    - wal_autocheckpoint=1000：WAL 文件达 1000 页时自动 checkpoint，控制文件大小
    """
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA wal_autocheckpoint=1000;")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
