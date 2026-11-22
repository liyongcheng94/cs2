"""全场详细数据契约：v1 端点按需拉取 + 缓存（第二次不重复请求）+ 401 透传。"""
import httpx
import pytest


def _seed_match(client, match_id="PVP@V1"):
    client.post("/api/tasks", json={"type": "wanmei_sync"})  # 确保任务类型注册不必要；直接种 Match
    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        if s.exec(select(Match).where(Match.match_id == match_id)).first() is None:
            import datetime as dt

            s.add(Match(match_id=match_id, map_name="荒漠迷城", win=True,
                        played_at=dt.datetime(2026, 11, 21, 20, 0, 0)))
            s.commit()


@pytest.fixture()
def v1_stub(client, monkeypatch):
    from app.services import wanmei_sync
    from app.services.wanmei import WanmeiAPI

    calls = {"n": 0}

    class StubAPI(WanmeiAPI):
        def __init__(self):
            super().__init__(token="t", steam_id="76561198339750836", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"statusCode": 0})))

        async def match_detail_v1(self, match_id):
            calls["n"] += 1
            return {"base": {"matchId": match_id, "mapEn": "de_mirage"},
                    "players": [{"playerId": "76561198339750836", "kill": 13, "kast": 14.0}]}

    monkeypatch.setattr(wanmei_sync, "build_api_from_settings", lambda session: StubAPI())
    return calls


def test_detail_v1_fetch_and_cache(client, v1_stub):
    """
    Given 首次请求（无缓存）
    When  GET /api/matches/{id}/detail-v1 两次
    Then  第一次拉取并缓存；第二次直接返回缓存（API 计数不变）
    """
    from app.services import wanmei_sync
    from app.services.wanmei import WanmeiAPI

    _seed_match(client)
    client.put("/api/settings", json={"wanmei.access_token": "tok", "wanmei.steam_id": "76561198339750836"})

    mid = None
    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        mid = s.exec(select(Match).where(Match.match_id == "PVP@V1")).first().id

    r1 = client.get(f"/api/matches/{mid}/detail-v1")
    assert r1.status_code == 200
    assert r1.json()["players"][0]["kill"] == 13
    assert v1_stub["n"] == 1

    r2 = client.get(f"/api/matches/{mid}/detail-v1")
    assert r2.status_code == 200
    assert v1_stub["n"] == 1  # 缓存命中


def test_detail_v1_auth_401_passthrough(client, monkeypatch):
    """
    Given token 失效（WanmeiAuthError）
    When  GET detail-v1
    Then  返回 401（面板提示重登，不缓存）
    """
    from app.services import wanmei_sync
    from app.services.wanmei import WanmeiAPI, WanmeiAuthError

    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        if s.exec(select(Match).where(Match.match_id == "PVP@V401")).first() is None:
            import datetime as dt

            s.add(Match(match_id="PVP@V401", map_name="de_dust2", win=False,
                        played_at=dt.datetime(2026, 11, 21, 20, 0, 0)))
            s.commit()
    client.put("/api/settings", json={"wanmei.access_token": "dead", "wanmei.steam_id": "1"})

    class DeadAPI(WanmeiAPI):
        def __init__(self):
            super().__init__(token="dead", steam_id="1", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"statusCode": 0})))

        async def match_detail_v1(self, match_id):
            raise WanmeiAuthError("token 失效")

    monkeypatch.setattr(wanmei_sync, "build_api_from_settings", lambda session: DeadAPI())

    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        mid = s.exec(select(Match).where(Match.match_id == "PVP@V401")).first().id
    resp = client.get(f"/api/matches/{mid}/detail-v1")
    assert resp.status_code == 401
    m = s.exec(select(Match).where(Match.match_id == "PVP@V401")).first()
    assert m.detail_json is None  # 失败不缓存
