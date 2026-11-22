"""CS2HQ FastAPI 入口：lifespan 建表 + 画像种子 + loguru 落盘。"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from .api import api_router
from .config import APP_VERSION, get_log_dir
from .database import create_db_and_tables, session_factory
from .models import PlayerProfile, utcnow

PROFILE_BASELINE = {
    "mouse": "Acer OMR248",
    "dpi": 800,
    "sens": 1.25,
    "edpi": 1000,
    "main_map": "Dust2",
    "grades": {"狙击": "A", "残局": "B", "突破": "C", "补枪": "C", "道具": "C"},
    "pistol_we": 5.8,
    "t_rating": 1.06,
    "ct_rating": 0.97,
    "hs_rate": 0.319,
    "source": "DeepSeek 对话历史还原（2026-07）",
}


def seed_player_profile() -> None:
    with session_factory() as session:
        if session.get(PlayerProfile, "baseline") is None:
            session.add(
                PlayerProfile(key="baseline", data=PROFILE_BASELINE, updated_at=utcnow())
            )
            session.commit()
            logger.info("[启动] 已写入 player_profile baseline 种子")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(get_log_dir() / "cs2hq.log", rotation="10 MB", level="DEBUG", encoding="utf-8")
    create_db_and_tables()
    seed_player_profile()
    logger.info(f"[启动] CS2HQ v{APP_VERSION} 就绪 data={get_log_dir().parent}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="CS2HQ", version=APP_VERSION, lifespan=lifespan)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
