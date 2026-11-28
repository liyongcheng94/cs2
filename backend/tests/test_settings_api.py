import sqlite3

from app.database import get_db_path
from app.services.settings_service import get_value


def _db_value_enc(key: str) -> str | None:
    conn = sqlite3.connect(get_db_path())
    try:
        row = conn.execute(
            "SELECT value_enc FROM setting WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_set_and_get_secret_roundtrip(client):
    """
    Given 设置页提交一个 secret 类型键（如完美平台 token）
    When  PUT /api/settings 再 GET /api/settings
    Then  GET 返回原值；数据库里落的是密文而非明文
    """
    resp = client.put(
        "/api/settings",
        json={"wanmei.access_token": "tok-abc", "mindvault.password": "pw-123"},
    )
    assert resp.status_code == 200

    # 落库为密文
    enc = _db_value_enc("wanmei.access_token")
    assert enc is not None and "tok-abc" not in enc

    # 明文只在服务层可取（API 任何响应均脱敏，2026-11-24 收紧）
    from app.database import session_factory
    from app.services.settings_service import get_value

    with session_factory() as s:
        assert get_value(s, "wanmei.access_token") == "tok-abc"
        assert get_value(s, "mindvault.password") == "pw-123"

    # 列表接口脱敏
    listed = client.get("/api/settings").json()
    assert listed["wanmei.access_token"].startswith("****")
    assert "tok-abc" not in listed["wanmei.access_token"]


def test_non_secret_key_stored_plain(client):
    """
    Given 非 secret 键（如 mv.base_url）
    When  PUT /api/settings
    Then  数据库该值可读原文，GET 返回原值且不脱敏
    """
    client.put("/api/settings", json={"mv.base_url": "http://127.0.0.1:8001"})
    detail = client.get("/api/settings/detail").json()
    assert detail["mv.base_url"] == "http://127.0.0.1:8001"
    listed = client.get("/api/settings").json()
    assert listed["mv.base_url"] == "http://127.0.0.1:8001"


def test_put_masked_secret_does_not_overwrite(client):
    """
    Given 设置页把脱敏回显值（****开头）原样提交（历史 bug：掩码覆盖真实密码）
    When  PUT /api/settings
    Then  secret 值不被覆盖（保持原明文），其余键正常保存
    """
    client.put("/api/settings", json={"mindvault.password": "real-pw-456"})
    # detail 亦脱敏（新契约）：明文只在服务层可取
    assert client.get("/api/settings/detail").json()["mindvault.password"].startswith("****")
    client.put("/api/settings", json={"mindvault.password": "real-pw-456"})
    # detail 亦脱敏（新契约）：明文只在服务层可取
    assert client.get("/api/settings/detail").json()["mindvault.password"].startswith("****")
    resp = client.put("/api/settings", json={"mindvault.password": "****56", "mv.base_url": "http://x:1"})
    assert resp.status_code == 200
    # API 响应掩码；服务层明文未被覆盖
    from app.database import session_factory
    from app.services.settings_service import get_value

    with session_factory() as s:
        assert get_value(s, "mindvault.password") == "real-pw-456"
    assert client.get("/api/settings").json()["mv.base_url"] == "http://x:1"


def test_player_profile_seeded_on_startup(client):
    """
    Given 首次启动（空库）
    When  应用 lifespan 完成
    Then  player_profile 存在 baseline 种子（eDPI/主图/四维等级）
    """
    profile = client.get("/api/profile").json()
    assert profile["key"] == "baseline"
    data = profile["data"]
    assert data["edpi"] >= 1000
    assert data["main_map"] == "Dust2"
    assert data["grades"]["狙击"] == "A"
