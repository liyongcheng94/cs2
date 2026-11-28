"""重复死亡模式契约：跨场聚合 deaths（同图同区 ≥3 次）→ 周报段落 + AI 教练上下文注入。"""
import json as _json
from datetime import datetime

from app.database import session_factory
from app.models import DemoAnalysis, Match


def _payload(events: list[dict]) -> dict:
    return {"deaths": {"events": events, "buckets": [], "disadvantaged_rate": None}}


def _ev(x: float, y: float, disadv: bool = False) -> dict:
    return {"victim_x": x, "victim_y": y, "disadvantaged_position": disadv}


def _seed(client, with_match_rows: bool = True):
    with session_factory() as s:
        if with_match_rows:
            s.add(Match(match_id="D1", map_name="炙热沙城Ⅱ", win=True, played_at=datetime(2026, 11, 20, 12, 0, 0)))
            s.add(Match(match_id="D2", map_name="炙热沙城Ⅱ", win=False, played_at=datetime(2026, 11, 21, 12, 0, 0)))
        s.add(DemoAnalysis(match_id="D1", payload=_payload([
            _ev(100, 200), _ev(120, 180), _ev(90, 210, disadv=True), _ev(5000, 3000),
        ])))
        s.add(DemoAnalysis(match_id="D2", payload=_payload([
            _ev(110, 190), _ev(130, 220),
        ])))
        s.add(DemoAnalysis(match_id="D3", payload=_payload([  # 无 Match 行（地图未知，跳过）
            _ev(100, 200), _ev(110, 190), _ev(120, 180),
        ])))
        s.commit()


def test_death_patterns_grid_aggregation(client):
    """
    Given 两场 dust2 在同网格（500 unit ≈ 9.5m）共 5 次死亡（1 次劣势），远处 1 次，另一地图 0 次
    When  death_patterns
    Then  恰好 1 个模式：count=5、disadvantaged_n=1、matches_n=2、坐标为网格内均值
    """
    from app.services.death_patterns import death_patterns

    _seed(client)
    with session_factory() as s:
        out = death_patterns(s)
    assert len(out) == 1
    p = out[0]
    assert p["map_name"] == "炙热沙城Ⅱ"
    assert p["count"] == 5 and p["disadvantaged_n"] == 1 and p["matches_n"] == 2
    assert 90 <= p["x"] <= 130 and 180 <= p["y"] <= 220


def test_weekly_includes_death_patterns(client, monkeypatch):
    """
    Given 存在惯性死亡模式
    When  weekly_report_handler
    Then  周报 Markdown 含"惯性死亡点"段落（含地图与次数）
    """
    client.put("/api/settings", json={"mv.enabled": "1"})  # 联动开（默认 0 跳过推送）
    import app.services.weekly as wk
    from app.services.mindvault_client import MindVaultClient

    _seed(client)
    captured: dict = {}

    class StubMV(MindVaultClient):
        def __init__(self):
            super().__init__(base_url="http://stub")

        async def push_note(self, title, content, topic_name=None, topic_id=None):
            captured["content"] = content
            return {"uuid": "w-1"}

    monkeypatch.setattr(wk, "_new_mv", lambda: StubMV())
    task = wk.Task(id=1, type="weekly_report")
    out = asyncio_run(wk.weekly_report_handler(task, session_factory))
    assert out["created"] is True
    assert "惯性死亡点" in captured["content"] and "炙热沙城Ⅱ" in captured["content"]


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def test_coach_instruction_injects_death_patterns(client, monkeypatch):
    """
    Given 存在惯性死亡模式 + AI 桩
    When  POST /api/chat
    Then  instruction 注入惯性死亡点提示（跨场模式，AI 能引用）
    """
    import httpx as _httpx

    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    seen: list[dict] = []

    def handler(request: _httpx.Request) -> _httpx.Response:
        if request.url.path == "/api/auth/login":
            return _httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        seen.append(_json.loads(request.content))
        return _httpx.Response(200, json={"text": "根据你的死亡模式…"})

    monkeypatch.setattr(cc, "build_ai_client", lambda session: AiClient(
        provider="mindvault", mv_base_url="http://stub", mv_password="pw",
        transport=_httpx.MockTransport(handler)))
    _seed(client)
    resp = client.post("/api/chat", json={"content": "我总在哪里死？"})
    assert resp.status_code == 200
    assert "惯性死亡点" in seen[0]["instruction"] and "炙热沙城Ⅱ" in seen[0]["instruction"]
