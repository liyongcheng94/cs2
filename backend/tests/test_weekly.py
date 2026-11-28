"""周报契约：近7天聚合 → MindVault「CS2周报」推送；调度周日 21:00 窗口。"""
import asyncio
import json
from datetime import datetime

from sqlmodel import select

from app.database import session_factory
from app.models import Match, MatchStat, Task
from app.services.scheduler import Scheduler
from app.services.weekly import build_weekly_markdown, weekly_report_handler


def _seed_week_matches():
    with session_factory() as s:
        now = datetime(2026, 11, 22, 12, 0, 0)
        for i, (mid, win, rating) in enumerate([
            ("PVP@W1", True, 1.2), ("PVP@W2", False, 0.8), ("PVP@W3", True, 1.05),
        ]):
            s.add(Match(match_id=mid, map_name="de_dust2", win=win, played_at=now))
            s.add(MatchStat(match_id=mid, rating=rating))
        s.commit()


def test_build_weekly_markdown_aggregates(client):
    """
    Given 近 7 天 3 场（2 胜 1 负，rating 1.2/0.8/1.05）
    When  build_weekly_markdown
    Then  胜率 67%、平均 rating 1.02，Markdown 含周键
    """
    _seed_week_matches()
    md, payload = build_weekly_markdown(session_factory(), datetime(2026, 11, 22, 21, 0, 0))
    assert payload["matches"] == 3
    assert payload["wins"] == 2
    assert payload["win_rate"] == 0.667
    assert payload["avg_rating"] == 1.017
    assert "CS2 周报" in md


def test_scheduler_weekly_sunday_window(client):
    """
    Given 周日 21:00 vs 周六同刻
    When  tick
    Then  仅周日返回 weekly_report
    """
    sunday = Scheduler(now_fn=lambda: datetime(2026, 11, 22, 21, 0, 0))  # 2026-11-22 是周日
    assert "weekly_report" in sunday.tick(datetime(2026, 11, 22, 21, 0, 0))
    saturday = Scheduler(now_fn=lambda: datetime(2026, 11, 28, 21, 0, 0))
    assert "weekly_report" not in saturday.tick(datetime(2026, 11, 28, 21, 0, 0))


def test_weekly_report_handler_pushes(client, monkeypatch):
    """
    Given MindVault 桩 + AI 桩
    When  执行 weekly_report
    Then  created=True、uuid 返回、Markdown 含 AI 周评段落
    """
    import app.services.weekly as wk
    from app.services.mindvault_client import MindVaultClient

    class StubMV(MindVaultClient):
        def __init__(self):
            super().__init__(base_url="http://stub")

        async def push_note(self, title, content, topic_name=None, topic_id=None):
            assert "AI 周评" in content  # AI 周评段落在 Markdown 里
            return {"uuid": "weekly-u1"}

    async def fake_ai_chat(self, system, user):
        data = json.loads(user)
        assert data["本周数据"]["matches"] >= 3
        return "周评：胜率 67% 高于你的历史基线，下周继续 Retake 补枪专项。"

    class StubAI:
        provider = "deepseek"

        async def chat(self, system, user):
            return await fake_ai_chat(self, system, user)

    monkeypatch.setattr(wk, "_new_mv", lambda: StubMV())
    monkeypatch.setattr(wk, "build_ai_client", lambda session: StubAI())
    task = Task(id=1, type="weekly_report")
    client.put("/api/settings", json={"mv.enabled": "1"})
    out = asyncio.run(weekly_report_handler(task, session_factory))
    assert out["created"] is True and out["uuid"] == "weekly-u1"


def test_weekly_ai_comment_actually_reaches_push(client, monkeypatch):
    """
    Given AI 桩返回可识别标记文本
    When  执行 weekly_report
    Then  该标记文本出现在推送的 Markdown 里（防：NameError 被 except 吞掉后 AI 周评静默失效——
          旧断言 "AI 周评" in content 被静态占位文案空转通过，必须断言 AI 真实输出）
    """
    import app.services.weekly as wk
    from app.services.mindvault_client import MindVaultClient

    MARK = "周评标记：本周复盘覆盖 3 场，评分趋势健康。"

    class StubMV(MindVaultClient):
        def __init__(self):
            super().__init__(base_url="http://stub")

        async def push_note(self, title, content, topic_name=None, topic_id=None):
            assert MARK in content, "AI 周评输出未到达推送内容（json 序列化路径失效）"
            return {"uuid": "weekly-u2"}

    class StubAI:
        provider = "deepseek"

        async def chat(self, system, user):
            return MARK

    monkeypatch.setattr(wk, "_new_mv", lambda: StubMV())
    monkeypatch.setattr(wk, "build_ai_client", lambda session: StubAI())
    task = Task(id=2, type="weekly_report")
    client.put("/api/settings", json={"mv.enabled": "1"})
    out = asyncio.run(weekly_report_handler(task, session_factory))
    assert out["created"] is True and out["uuid"] == "weekly-u2"
