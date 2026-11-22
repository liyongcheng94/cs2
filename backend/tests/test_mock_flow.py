"""Mock 全链路：假数据 → 复盘 → MindVault 推送（桩）。"""
import json

import httpx
import pytest


@pytest.fixture()
def stub_mv_override(client, monkeypatch):
    """把 mock-flow 依赖的 MindVaultClient 覆盖为桩（默认成功）。"""
    from app.api.deps import get_mv_client
    from app.services.mindvault_client import MindVaultClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/topics" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/topics":
            return httpx.Response(201, json={"id": 5, "name": "CS2复盘"})
        if request.url.path == "/api/mcp":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "item_id": 1,
                                        "uuid": "mv-uuid-1",
                                        "title": body["params"]["arguments"]["title"],
                                    }
                                ),
                            }
                        ],
                        "isError": False,
                    },
                },
            )
        return httpx.Response(404)

    stub = MindVaultClient(
        base_url="http://stub", transport=httpx.MockTransport(handler)
    )
    client.app.dependency_overrides[get_mv_client] = lambda: stub
    yield stub
    client.app.dependency_overrides.pop(get_mv_client, None)


def test_mock_flow_full_chain(client, stub_mv_override):
    """
    Given MindVault 桩可用
    When  POST /api/test/mock-flow
    Then  pushed=true、生成假对局/四维分析/复盘各一条、复盘记录 mv_uuid
    """
    resp = client.post("/api/test/mock-flow")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pushed"] is True
    assert body["mv_uuid"] == "mv-uuid-1"
    assert body["topic"] == "CS2复盘"

    # 对局列表出现假数据
    matches = client.get("/api/matches").json()
    assert len(matches) == 1
    assert matches[0]["match_id"].startswith("PVP@MOCK-")
    assert matches[0]["demo_status"] == "analyzed"

    # 四维分析已按 schema 落库
    detail = client.get(f"/api/matches/{matches[0]['id']}").json()
    assert detail["analysis"]["schema_version"] == "1.1"
    assert detail["analysis"]["duels"]["by_weapon_distance"][0]["distance"] == "0-5m"

    # 幂等：重复跑 mock-flow 生成新 match（时间戳不同）但推送内容独立
    resp2 = client.post("/api/test/mock-flow").json()
    assert resp2["pushed"] is True


def test_mock_flow_degrades_when_mindvault_down(client, monkeypatch):
    """
    Given MindVault 不可达
    When  POST /api/test/mock-flow
    Then  pushed=false 且给出原因；假数据仍落本地库（不阻塞主流程）
    """
    from app.api.deps import get_mv_client
    from app.services.mindvault_client import MindVaultClient

    dead = MindVaultClient(base_url="http://127.0.0.1:1", transport=None)
    client.app.dependency_overrides[get_mv_client] = lambda: dead
    try:
        resp = client.post("/api/test/mock-flow")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pushed"] is False
        assert body["reason"]
        matches = client.get("/api/matches").json()
        assert len(matches) == 1
    finally:
        client.app.dependency_overrides.pop(get_mv_client, None)
