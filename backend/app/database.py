"""数据库：按路径惰性建引擎（key 缓存），SQLModel 统一建表。"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

from .config import get_data_dir


def get_db_path():
    return get_data_dir() / "cs2hq.db"


_engine_cache: dict[str, object] = {}


def get_engine():
    path = str(get_db_path())
    if path not in _engine_cache:
        _engine_cache[path] = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
    return _engine_cache[path]


def create_db_and_tables() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _run_migrations(engine)


# 轻量迁移（幂等：列已存在时忽略报错）。结构变更后在此追加。
_MIGRATIONS = [
    "ALTER TABLE matchstat ADD COLUMN we REAL",
    "ALTER TABLE match ADD COLUMN detail_json JSON",
    "ALTER TABLE bilivideo ADD COLUMN mv_uuid VARCHAR",
    # 学道具 v2（2026-11-23 grill-me 八问共识）：分区列 + 收藏列（幂等：try/except 已存在则跳过）
    "ALTER TABLE grenadecard ADD COLUMN zone VARCHAR",
    "ALTER TABLE grenadecard ADD COLUMN favorited BOOLEAN DEFAULT 0",
    # AI 教练图片对话（2026-11-23 OCR 间接路线）：消息带图 id 列
    "ALTER TABLE chatmessage ADD COLUMN image_ids VARCHAR",
]


def _run_migrations(engine) -> None:
    from sqlalchemy import text

    with engine.connect() as conn:
        for sql in _MIGRATIONS:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:  # noqa: BLE001 — 列已存在
                conn.rollback()


def get_session():
    with Session(get_engine()) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def session_factory() -> Session:
    """供后台任务使用的独立会话工厂。"""
    return Session(get_engine())
