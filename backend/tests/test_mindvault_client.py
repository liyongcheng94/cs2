"""MindVaultClient 契约测试：全部走 httpx.MockTransport，不依赖真实 MindVault。"""
import json

import httpx
import pytest

from app.services.mindvault_client import MindVaultClient, MindVaultError


def _stub_mindvault(handler):
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_push_note_calls_mcp_create_note():
    """
    Given MindVault 桩返回 create_note 成功结果
    When  push_note(title, content, topic_name)
    Then  先 ensure_topic 再 MCP tools/call create_note，返回 uuid
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/topics":
            return httpx.Response(200, json=[{"id": 1, "name": "其他", "children": []}])
        if request.url.path == "/api/topics" and request.method == "POST":
            return httpx.Response(201, json={"id": 9, "name": "CS2复盘"})
        if request.url.path == "/api/mcp":
            body = json.loads(request.content)
            assert body["method"] == "tools/call"
            assert body["params"]["name"] == "create_note"
            args = body["params"]["arguments"]
            assert args["title"].startswith("[MOCK]")
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
                                    {"item_id": 77, "uuid": "u-77", "title": args["title"]}
                                ),
                            }
                        ],
                        "isError": False,
                    },
                },
            )
        return httpx.Response(404)

    client = MindVaultClient(base_url="http://stub", transport=_stub_mindvault(handler))
    out = await client.push_note("[MOCK] t", "content", topic_name="CS2复盘")
    assert out["uuid"] == "u-77"
    assert out["topic_id"] == 9
    assert ("POST", "/api/topics") in calls
    assert ("POST", "/api/mcp") in calls


@pytest.mark.anyio
async def test_ensure_topic_reuses_existing():
    """
    Given MindVault 主题树已存在 "CS2复盘"
    When  ensure_topic("CS2复盘")
    Then  直接返回其 id，不再创建
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/topics"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 2,
                    "name": "CS2复盘",
                    "children": [{"id": 3, "name": "子", "children": []}],
                }
            ],
        )

    client = MindVaultClient(base_url="http://stub", transport=_stub_mindvault(handler))
    assert await client.ensure_topic("CS2复盘") == 2


@pytest.mark.anyio
async def test_update_note_puts_content():
    """
    Given 已有 MindVault 条目 uuid
    When  update_note(uuid, content)
    Then  走 REST PUT /api/items/{uuid} 携带新 content
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"uuid": "u-1", "title": "t"})

    client = MindVaultClient(base_url="http://stub", transport=_stub_mindvault(handler))
    await client.update_note("u-1", content="v2 content")
    assert seen["body"]["content"] == "v2 content"


@pytest.mark.anyio
async def test_password_login_and_401_retry():
    """
    Given 配置了访问密码
    When  首个请求返回 401
    Then  自动重登一次后成功（仅一次，防循环）
    """
    state = {"logins": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            state["logins"] += 1
            return httpx.Response(
                200, json={"ok": True}, headers={"set-cookie": "mv_session=tok-1; Path=/"}
            )
        if request.url.path == "/api/health":
            if request.headers.get("authorization") == "Bearer tok-1":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(401)
        return httpx.Response(404)

    client = MindVaultClient(
        base_url="http://stub", password="pw", transport=_stub_mindvault(handler)
    )
    resp = await client.request("GET", "/api/health")
    assert resp.status_code == 200
    assert state["logins"] == 2  # 初次登录 + 401 后重登一次


@pytest.mark.anyio
async def test_unreachable_raises_mindvault_error():
    """
    Given MindVault 未启动
    When  push_note
    Then  抛 MindVaultError（调用方降级为本地保存，不阻塞主流程）
    """
    client = MindVaultClient(base_url="http://127.0.0.1:1", transport=None)
    with pytest.raises(MindVaultError):
        await client.push_note("[MOCK] t", "c", topic_name="CS2复盘")
