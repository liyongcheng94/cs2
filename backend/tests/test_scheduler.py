"""错峰调度契约：平台同步每 2h / demo 批量凌晨 03:30 / 需登录才跑；tasks 按 priority。"""
from datetime import datetime

from app.services.scheduler import Scheduler


def test_wanmei_sync_due_every_2h_when_logged_in(client, monkeypatch):
    """
    Given 已登录完美平台
    When  tick(now) 且距上次同步 ≥2h
    Then  返回 wanmei_sync
    """
    from app.database import session_factory
    from app.services import settings_service

    with session_factory() as s:
        settings_service.set_value(s, "wanmei.access_token", "tok")
        settings_service.set_value(s, "wanmei.steam_id", "1")

    sched = Scheduler(now_fn=lambda: datetime(2026, 11, 22, 8, 0, 0))
    due = sched.tick(datetime(2026, 11, 22, 8, 0, 0))
    assert "wanmei_sync" in due
    # 2h 内不重复
    sched2 = Scheduler(now_fn=lambda: datetime(2026, 11, 22, 9, 0, 0), last_run={"wanmei_sync": datetime(2026, 11, 22, 8, 0, 0)})
    assert "wanmei_sync" not in sched2.tick(datetime(2026, 11, 22, 9, 0, 0))


def test_wanmei_sync_skipped_when_not_logged_in(client):
    """
    Given 未登录（无 token）
    When  tick
    Then  不产生 wanmei_sync（防止无效请求刷接口）
    """
    sched = Scheduler(now_fn=lambda: datetime(2026, 11, 22, 8, 0, 0))
    assert "wanmei_sync" not in sched.tick(datetime(2026, 11, 22, 8, 0, 0))


def test_demo_batch_only_in_night_window(client):
    """
    Given 存在 pending_demo 对局
    When  tick 在凌晨 03:30 窗口 vs 白天
    Then  仅凌晨返回 demo_analyze_batch（错峰评审约定）
    """
    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        s.add(Match(match_id="PVP@NIGHT1", map_name="de_dust2", played_at=datetime(2026, 11, 20), demo_status="pending_demo"))
        s.commit()

    night = Scheduler(now_fn=lambda: datetime(2026, 11, 22, 3, 30, 0))
    assert "demo_analyze_batch" in night.tick(datetime(2026, 11, 22, 3, 30, 0))
    day = Scheduler(now_fn=lambda: datetime(2026, 11, 22, 14, 0, 0))
    assert "demo_analyze_batch" not in day.tick(datetime(2026, 11, 22, 14, 0, 0))


def test_demo_batch_creates_tasks_for_pending(client):
    """
    Given 2 场 pending_demo
    When  执行 demo_analyze_batch
    Then  为每场创建 demo_analyze 任务（priority=2 高于视频总结）
    """
    import asyncio

    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match, Task
    from app.services import task_manager
    from app.services.scheduler import run_demo_analyze_batch

    with session_factory() as s:
        for i, mid in enumerate(("PVP@B1", "PVP@B2")):
            s.add(Match(match_id=mid, map_name="de_mirage", played_at=datetime(2026, 11, 20), demo_status="pending_demo"))
        s.commit()

    task = Task(id=999, type="demo_analyze_batch", payload={})
    result = asyncio.run(run_demo_analyze_batch(task, session_factory))
    assert result["enqueued"] == 2

    with session_factory() as s:
        demo_tasks = s.exec(select(Task).where(Task.type == "demo_analyze")).all()
        assert len(demo_tasks) == 2
        assert all(t.priority == 2 for t in demo_tasks)


def test_orphan_pending_tasks_marked_failed(client):
    """
    Given 一个 created_at 超 1h 的 pending 任务
    When  调度 tick
    Then  该任务被标 failed（孤儿自检），且正常调度继续
    """
    import asyncio
    import datetime as _dtmod
    from datetime import datetime as dt

    from sqlmodel import select

    from app.database import session_factory
    from app.models import Task
    from app.services import task_manager



    old = dt.utcnow() - _dtmod.timedelta(hours=2)
    with session_factory() as s:
        s.add(Task(type="dummy_ok", payload={}, status="pending", created_at=old))
        s.commit()

    from app.services.scheduler import Scheduler

    sched = Scheduler(now_fn=lambda: dt.utcnow())
    sched.tick(dt.utcnow())

    with session_factory() as s:
        t = s.exec(select(Task).where(Task.type == "dummy_ok")).first()
        assert t.status == "failed"
        assert "孤儿" in t.error

    # 清理 dummy handler 注册避免污染
