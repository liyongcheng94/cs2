"""错峰调度（评审约定）：平台同步每 2h、demo 解析凌晨 03:30 批量、B站限白天、周报周日（阶段5接入）。

Scheduler.tick(now) 纯函数可测；run_loop 挂 lifespan 后台协程，逐个创建任务并立即执行。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import Match, Task, utcnow

SYNC_INTERVAL_H = 2
DEMO_BATCH_HOUR = 3
DEMO_BATCH_MIN = 30


def _logged_in(session: Session) -> bool:
    from . import settings_service

    return bool(settings_service.get_value(session, "wanmei.access_token")) and bool(
        settings_service.get_value(session, "wanmei.steam_id")
    )


class Scheduler:
    """纯函数 tick：给定 now 与 last_run，返回此刻该跑的任务类型列表。"""

    def __init__(
        self,
        now_fn: Callable[[], datetime] | None = None,
        last_run: dict[str, datetime] | None = None,
        session_factory_fn: Callable[[], Session] | None = None,
    ):
        self._now_fn = now_fn or utcnow
        self.last_run = dict(last_run or {})
        self._session_factory = session_factory_fn or session_factory

    def tick(self, now: datetime) -> list[str]:
        due: list[str] = []
        with self._session_factory() as session:
            logged = _logged_in(session)
            # 平台同步：每 2h，且必须已登录（无 token 不打接口）
            last = self.last_run.get("wanmei_sync")
            if logged and (last is None or (now - last).total_seconds() >= SYNC_INTERVAL_H * 3600):
                due.append("wanmei_sync")
            # demo 批量：仅凌晨 03:30 起的窗口内触发（白天补跑也违反错峰），每天一次
            last_batch = self.last_run.get("demo_analyze_batch")
            in_window = now.hour == DEMO_BATCH_HOUR and now.minute >= DEMO_BATCH_MIN
            pending = session.exec(select(Match).where(Match.demo_status == "pending_demo")).all()
            if in_window and pending and (last_batch is None or last_batch.date() != now.date()):
                due.append("demo_analyze_batch")
        return due

    def mark(self, name: str, now: datetime | None = None) -> None:
        self.last_run[name] = now or self._now_fn()


def _create_and_run(task_type: str, payload: dict, priority: int) -> dict | None:
    from . import task_manager

    with session_factory() as session:
        if task_type not in task_manager.HANDLERS:
            return None
        task = task_manager.create_task(session, task_type, payload, priority=priority)
        task_id = task.id
    return asyncio.run(task_manager.run_task(task_id)) if task_id else None


async def run_demo_analyze_batch(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    """为全部 pending_demo 对局创建 demo_analyze 任务（priority=2 高于视频总结）。"""
    enqueued = 0
    with session_factory_fn() as session:
        pending = session.exec(select(Match).where(Match.demo_status == "pending_demo")).all()
        mids = [m.match_id for m in pending]
    for mid in mids:
        with session_factory_fn() as session:
            t = Task(
                type="demo_analyze",
                payload={"match_id": mid},
                priority=2,
            )
            session.add(t)
            session.commit()
            enqueued += 1
    logger.info(f"[调度] demo批量：为 {enqueued} 场 pending_demo 创建分析任务")
    return {"enqueued": enqueued}


def register() -> None:
    from . import task_manager

    async def _batch_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
        return await run_demo_analyze_batch(task, session_factory_fn)

    task_manager.HANDLERS["demo_analyze_batch"] = _batch_handler


async def run_forever(interval_s: int = 60) -> None:
    """lifespan 后台循环：tick → 创建任务 → 执行 → 标记。任何异常不退出循环。"""
    register()
    sched = Scheduler()
    while True:
        try:
            now = utcnow()
            for name in sched.tick(now):
                sched.mark(name, now)
                logger.info(f"[调度] 触发 {name}")
                if name == "wanmei_sync":
                    _create_and_run("wanmei_sync", {}, priority=3)
                elif name == "demo_analyze_batch":
                    _create_and_run("demo_analyze_batch", {}, priority=1)
        except Exception:  # noqa: BLE001
            logger.exception("[调度] tick 异常（循环继续）")
        await asyncio.sleep(interval_s)
