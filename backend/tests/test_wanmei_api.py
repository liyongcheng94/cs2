"""完美平台登录 API 与同步任务契约（全部桩化：不触真实 passport、不发真实短信）。"""
import httpx
import pytest


def _stub_passport(monkeypatch, *, sms_fail=None, login_ok=True):
    from app.api import wanmei_api
    from app.services.wanmei import PassportClient

    class StubPassport(PassportClient):
        def __init__(self):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0})))

        async def captcha_init(self):
            return {"capTicket": "tkt-1", "url": "https://c.example/x.html"}

        async def send_code(self, mobile_phone, sec_code, cap_ticket):
            if sms_fail:
                from app.services.wanmei import WanmeiError

                raise WanmeiError(sms_fail)

        async def sms_login(self, mobile_phone, security_code):
            if not login_ok:
                from app.services.wanmei import WanmeiError

                raise WanmeiError("验证码错误")
            return {"token": "tok-real-123", "steam_id": "76561198929200000", "user_id": 58072600, "mobile_phone": mobile_phone}

    monkeypatch.setattr(wanmei_api, "_new_passport", lambda: StubPassport())


def test_captcha_init_returns_ticket(client, monkeypatch):
    """
    Given passport initcaptcha 桩
    When  POST /api/wanmei/captcha-init
    Then  返回 capTicket 供前端初始化 WanmeiCaptcha 滑块
    """
    _stub_passport(monkeypatch)
    resp = client.post("/api/wanmei/captcha-init")
    assert resp.status_code == 200
    assert resp.json()["capTicket"] == "tkt-1"


def test_send_code_failure_maps_to_502(client, monkeypatch):
    """
    Given 发码失败（验证码校验失败）
    When  POST /api/wanmei/send-code
    Then  502 且 detail 含原因（不重试、不发第二次短信）
    """
    _stub_passport(monkeypatch, sms_fail="验证码校验失败")
    resp = client.post(
        "/api/wanmei/send-code",
        json={"mobile_phone": "13800138000", "sec_code": "x", "cap_ticket": "tkt-1"},
    )
    assert resp.status_code == 502
    assert "验证码校验失败" in resp.json()["detail"]


def test_sms_login_stores_encrypted_token(client, monkeypatch):
    """
    Given 短信码登录成功
    When  POST /api/wanmei/sms-login
    Then  返回 steamId；token 加密落库（库中无明文）；GET status 显示已登录
    """
    import sqlite3

    from app.database import get_db_path

    _stub_passport(monkeypatch)
    resp = client.post(
        "/api/wanmei/sms-login", json={"mobile_phone": "13800138000", "security_code": "654321"}
    )
    assert resp.status_code == 200
    assert resp.json()["steam_id"] == "76561198929200000"

    conn = sqlite3.connect(get_db_path())
    try:
        row = conn.execute(
            "SELECT value_enc FROM setting WHERE key='wanmei.access_token'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and "tok-real-123" not in row[0]

    status = client.get("/api/wanmei/status").json()
    assert status["logged_in"] is True
    assert status["steam_id"] == "76561198929200000"


def test_sync_task_upserts_matches_idempotently(client, monkeypatch):
    """
    Given 已登录（token 存 settings）且 API 桩返回 2 场对局
    When  创建并执行 wanmei_sync 任务两次
    Then  任务 success；对局仍为 2 条（幂等不重复）
    """
    from app.services import task_manager, wanmei_sync
    from app.services.wanmei import WanmeiAPI

    client.put("/api/settings", json={"wanmei.access_token": "tok-x", "wanmei.steam_id": "76561198929200000"})

    rows = [
        {
            "matchId": "PVP@A1",
            "mapName": "荒漠迷城",
            "score1": 4,
            "score2": 13,
            "winTeam": 2,
            "team": 2,  # 己方在 2 队且 2 队胜 → 胜
            "startTime": "2026-11-21 20:04:01",
            "rating": 1.19,
            "pwRating": 1.33,
            "kill": 13,
            "death": 9,
            "assist": 9,
            "mvp": False,
            "pvpMvp": True,
            "we": 11.83,
            "timeStamp": 1795263938,
        },
        {
            "matchId": "PVP@B2",
            "mapName": "荒漠迷城",
            "score1": 4,
            "score2": 13,
            "winTeam": 2,
            "team": 1,  # 己方在 1 队且 2 队胜 → 负
            "startTime": "2026-11-21 18:06:43",
            "rating": 0.52,
            "kill": 6,
            "death": 13,
            "we": 5.21,
        },
    ]

    class StubAPI(WanmeiAPI):
        def __init__(self):
            super().__init__(
                token="t",
                steam_id="76561198929200000",
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0})),
            )

        async def match_list(self, page=1, page_size=20):
            # 解包后的 data 对象（真实信封 {statusCode,data:{matchList}} 由 _unwrap_data 剥离）
            return {"matchList": rows if page == 1 else []}

    monkeypatch.setattr(wanmei_sync, "build_api_from_settings", lambda session: StubAPI())

    task_id = client.post("/api/tasks", json={"type": "wanmei_sync"}).json()["id"]
    run = client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success"
    assert body["result"]["inserted"] == 2

    run2 = client.post(f"/api/tasks/{task_id}/run")
    assert run2.status_code == 200
    body2 = client.get(f"/api/tasks/{task_id}").json()
    assert body2["result"]["inserted"] == 0
    assert body2["result"]["updated"] == 2

    matches = client.get("/api/matches").json()
    assert len(matches) == 2
    ids = {m["match_id"] for m in matches}
    assert ids == {"PVP@A1", "PVP@B2"}
    # 真实字段映射：胜负用 winTeam==team 精确判定（不再靠比分启发式）
    wins = {m["match_id"]: m["win"] for m in matches}
    assert wins == {"PVP@A1": True, "PVP@B2": False}
    # WE 评分与新迁移列
    detail = client.get(f"/api/matches/{matches[0]['id']}").json()
    assert detail["stat"]["we"] == 11.83
    assert detail["match"]["map_name"] == "荒漠迷城"


def test_sync_task_auth_failure_becomes_need_auth(client, monkeypatch):
    """
    Given API 桩抛 WanmeiAuthError（token 失效）
    When  执行 wanmei_sync
    Then  任务状态 NEED_AUTH（熔断），面板可见
    """
    from app.services import task_manager, wanmei_sync
    from app.services.wanmei import WanmeiAPI, WanmeiAuthError

    client.put("/api/settings", json={"wanmei.access_token": "tok-dead", "wanmei.steam_id": "1"})

    class DeadAPI(WanmeiAPI):
        def __init__(self):
            super().__init__(token="dead", steam_id="1", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 0})))

        async def match_list(self, page=1, page_size=20):
            raise WanmeiAuthError("token 失效")

    monkeypatch.setattr(wanmei_sync, "build_api_from_settings", lambda session: DeadAPI())

    task_id = client.post("/api/tasks", json={"type": "wanmei_sync"}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "NEED_AUTH"
    assert "token" in body["error"]


def test_sync_saves_season_stats(client, monkeypatch):
    """
    Given API 桩返回真实形状 detailStats
    When  执行 wanmei_sync
    Then  SeasonStats 落库；GET /api/matches/stats/season 返回趋势数据
    """
    import httpx as _httpx

    from app.services import wanmei_sync
    from app.services.wanmei import WanmeiAPI

    client.put("/api/settings", json={"wanmei.access_token": "tok", "wanmei.steam_id": "76561198339750836"})

    class StubAPI(WanmeiAPI):
        def __init__(self):
            super().__init__(token="t", steam_id="76561198339750836", transport=_httpx.MockTransport(lambda r: _httpx.Response(200, json={"statusCode": 0})))

        async def match_list(self, page=1, page_size=20):
            return {"matchList": []}

        async def detail_stats(self, season_id="recent"):
            return {"seasonId": "s-9", "historyRatings": [1.1, 0.9], "adr": 73.95}

    monkeypatch.setattr(wanmei_sync, "build_api_from_settings", lambda session: StubAPI())

    task_id = client.post("/api/tasks", json={"type": "wanmei_sync"}).json()["id"]
    run = client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success" and body["result"]["season_stats"] is True

    out = client.get("/api/matches/stats/season").json()
    assert out["season_id"] == "s-9"
    assert out["data"]["adr"] == 73.95
    assert out["data"]["historyRatings"] == [1.1, 0.9]
