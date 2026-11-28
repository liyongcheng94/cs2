"""SQLite 每日快照备份：启动时自动执行，同日幂等，滚动保留 7 份。"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..config import get_data_dir

KEEP = 7


def backups_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _day_stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d")


def create_daily_backup(now: datetime | None = None, db_path: Path | None = None) -> Path:
    """当日快照：cs2hq-YYYYMMDD.db；同日已存在则直接返回（幂等）。"""
    src = db_path or (get_data_dir() / "cs2hq.db")
    d = backups_dir()
    target = d / f"cs2hq-{_day_stamp(now)}.db"
    if target.exists():
        return target
    if src.exists():
        shutil.copy2(src, target)
        logger.info(f"[备份] 快照 {target.name} ({target.stat().st_size} bytes)")
    return target


def prune_backups(keep: int = KEEP, d: Path | None = None) -> int:
    """滚动保留最近 keep 份备份（按文件名排序即按日期序），返回删除数。"""
    d = d or backups_dir()
    files = sorted(d.glob("cs2hq-*.db"))
    removed = 0
    for f in files[:-keep] if len(files) > keep else []:
        f.unlink()
        removed += 1
    return removed


def run_daily_backup(keep: int = KEEP) -> dict:
    """备份 + 清理一条龙（lifespan 启动时调用）。"""
    target = create_daily_backup()
    removed = prune_backups(keep=keep)
    return {"backup": str(target), "pruned": removed}
