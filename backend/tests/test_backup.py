"""SQLite 每日快照备份契约：启动时自动备份 + 同日只留一份 + 滚动保留 7 份。"""
from pathlib import Path

from app.services.backup import (
    backups_dir,
    create_daily_backup,
    prune_backups,
)


def test_create_daily_backup_same_day_only_once(client):
    """
    Given 当日尚无备份
    When  create_daily_backup 两次
    Then  只产生一个当日文件（同日幂等），且文件非空
    """
    p1 = create_daily_backup()
    p2 = create_daily_backup()
    assert p1 == p2
    assert p1.exists() and p1.stat().st_size > 0
    assert list(backups_dir().glob("cs2hq-*.db")).__len__() == 1


def test_prune_backups_keeps_seven(client, tmp_path, monkeypatch):
    """
    Given 备份目录已有 8 份历史备份（含当日）
    When  prune_backups(keep=7)
    Then  最旧 1 份被删，剩 7 份，最新保留
    """
    import time

    d = backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for i in range(8):
        f = d / f"cs2hq-2026112{i}-000000.db"
        f.write_bytes(b"x")
        # 手动错开 mtime：i 越大越新
        ts = now - (8 - i) * 86400
        import os

        os.utime(f, (ts, ts))

    prune_backups(keep=7)
    left = sorted(f.name for f in d.glob("cs2hq-*.db"))
    assert len(left) == 7
    assert "cs2hq-20261120-000000.db" not in left  # 最旧被删
    assert "cs2hq-20261127-000000.db" in left  # 最新保留
