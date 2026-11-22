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
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def session_factory() -> Session:
    """供后台任务使用的独立会话工厂。"""
    return Session(get_engine())
