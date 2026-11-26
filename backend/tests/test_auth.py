"""账号体系（Phase 2，2026-11-26 grill 决策：用户名+密码+JWT cookie，完整部署给队友用）。

Given / When / Then 场景：
- 注册：新用户名成功并种 httpOnly cookie；重复用户名 409；用户名/密码缺失 422
- 登录：正确密码种 cookie；错误密码 401；不存在用户 401
- me：带 cookie 返回用户名；无 cookie/坏 token 401
- 首个注册用户 is_admin=True，其后 False
- 登出后 cookie 清除，me 401
- 数据隔离：A 的对局 A 可见、B 不可见（legacy 无主数据仅 admin 可见）
- 业务 API 未登录 401（GET /api/matches 代表）
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Match
from app.services import auth_service
from app.database import get_engine
from sqlmodel import Session


def _register(c: TestClient, username: str, password: str = "pw123456"):
    return c.post("/api/auth/register", json={"username": username, "password": password})


def test_register_success_sets_cookie(client: TestClient):
    r = _register(client, "will")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "cs2hq_token" in set_cookie and "HttpOnly" in set_cookie
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "will"


def test_register_duplicate_username_conflict(client: TestClient):
    assert _register(client, "will").status_code == 200
    assert _register(client, "will").status_code == 409


def test_first_user_is_admin_then_others_not(client: TestClient):
    """夹具已预注册 testadmin（首个用户=admin）；其后注册的都是普通用户。"""
    _register(client, "will")
    with Session(get_engine()) as s:
        from sqlmodel import select

        from app.models import User

        users = {u.username: u.is_admin for u in s.exec(select(User)).all()}
    assert users == {"testadmin": True, "will": False}


def test_login_and_logout_flow(client: TestClient):
    _register(client, "will")
    ok = client.post("/api/auth/login", json={"username": "will", "password": "pw123456"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "will"
    bad = client.post("/api/auth/login", json={"username": "will", "password": "wrong"})
    assert bad.status_code == 401
    assert client.post("/api/auth/login", json={"username": "ghost", "password": "x"}).status_code == 401
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_business_api_requires_login(tmp_path, monkeypatch):
    """未登录（无 cookie 的新 client）访问业务 API 必须 401。"""
    monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as raw:
        assert raw.get("/api/matches").status_code == 401
        assert raw.get("/api/tasks").status_code == 401


def test_invalid_token_rejected(client: TestClient):
    client.cookies.set("cs2hq_token", "garbage.token.here")
    assert client.get("/api/auth/me").status_code == 401


def test_password_hashing_roundtrip():
    h = auth_service.hash_password("pw123456")
    assert h != "pw123456" and auth_service.verify_password("pw123456", h)
    assert not auth_service.verify_password("wrong", h)


def test_data_isolation_between_users(client: TestClient):
    """admin（夹具预注册的 testadmin）可见 legacy + 自己的对局；队友登录后看不到任何一条。"""
    with Session(get_engine()) as s:
        from sqlmodel import select

        from app.models import User

        admin = s.exec(select(User).where(User.username == "testadmin")).one()

        from app.services.wanmei_sync import upsert_match

        s.add(Match(match_id="PVP@LEGACY", win=True, score1=13, score2=5, map_name="神秘古镇"))
        upsert_match(s, {"matchId": "PVP@ADMIN1", "winTeam": 1, "team": 1, "score1": 13, "score2": 5, "mapName": "神秘古镇"}, admin.id)
        s.commit()

    ids = {m["match_id"] for m in client.get("/api/matches").json()}
    assert "PVP@LEGACY" in ids and "PVP@ADMIN1" in ids

    # 队友登录后看不到任何一条
    client.post("/api/auth/logout")
    _register(client, "mate")
    ids_mate = {m["match_id"] for m in client.get("/api/matches").json()}
    assert ids_mate == set()


def test_token_has_no_iat_claim_wsl_clock_drift_safe():
    """
    Given WSL2 宿主时钟会回跳（实测 >10s），签发的 JWT 若含 iat/nbf
    When  时钟回跳后 decode（iat 落在未来）
    Then  ImmatureSignatureError → 随机 401。因此 token 必须不含 iat/nbf，
          仅靠 exp（30d）判定过期；decode 在任意时刻都应成功。
    """
    import jwt as pyjwt

    from app.services import auth_service

    token = auth_service.create_token(7)
    payload = pyjwt.decode(token, auth_service._secret(), algorithms=["HS256"])
    assert "iat" not in payload, "iat 会在时钟回跳时触发 ImmatureSignatureError（随机 401 根因）"
    assert "nbf" not in payload
    assert auth_service.decode_user_id(token) == 7


def test_legacy_task_hidden_from_normal_user(client):
    """
    Given 库里有 legacy 无主任务（user_id=None）与 admin 用户
    When  普通用户 GET 该任务 / 列表
    Then  404 / 列表不含；admin 可见。与 matches 口径一致（legacy 仅 admin 可见）。
    """
    # admin 登录（首用户），造一条 legacy 任务（直接落库 user_id=None）
    client.post("/api/auth/login", json={"username": "testadmin", "password": "pw123456"})
    from sqlmodel import Session

    from app.database import session_factory
    from app.models import Task

    with session_factory() as s:
        legacy = Task(type="wanmei_sync", payload={}, priority=5)
        s.add(legacy)
        s.commit()
        legacy_id = legacy.id

    # 注册普通用户
    client.post("/api/auth/register", json={"username": "mate", "password": "pw123456"})
    lc = __import__("fastapi.testclient", fromlist=["TestClient"])
    _ = lc  # noqa
    # 用普通用户身份访问
    import json as _json

    resp = client.post("/api/auth/login", json={"username": "mate", "password": "pw123456"})
    assert resp.status_code == 200
    # 上面 login 覆盖了 cookie：mate 现在是当前用户
    r = client.get(f"/api/tasks/{legacy_id}")
    assert r.status_code == 404, r.text
    listing = client.get("/api/tasks").json()
    assert all(t["id"] != legacy_id for t in listing)
    # admin 仍可见
    client.post("/api/auth/login", json={"username": "testadmin", "password": "pw123456"})
    r2 = client.get(f"/api/tasks/{legacy_id}")
    assert r2.status_code == 200
    assert _json.loads(_json.dumps(r2.json()))["id"] == legacy_id
