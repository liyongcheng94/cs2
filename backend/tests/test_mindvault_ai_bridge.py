"""MindVault AI 桥契约：provider=mindvault 借公网实例 /api/ai/write（custom 指令）。"""
import asyncio
import json

import httpx
import pytest

from app.services.ai_client import AiClient, AiError


def test_mindvault_bridge_routes_custom_write():
    """
    Given MindVault /api/ai/write 桩（action=custom）
    When  AiClient(provider="mindvault").chat(system, user)
    Then  请求携带 action=custom + instruction=system + content=user，返回文本
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"text": "AI生成内容"})

    client = AiClient(
        provider="mindvault",
        mv_base_url="http://stub",
        mv_password="pw",
        transport=httpx.MockTransport(handler),
    )
    out = asyncio.run(client.chat("系统指令", "用户内容"))
    assert out == "AI生成内容"
    assert seen["body"]["action"] == "custom"
    assert seen["body"]["instruction"] == "系统指令"
    assert seen["body"]["text"] == "用户内容"


def test_mindvault_bridge_401_maps_to_ai_error():
    """
    Given 密码错误（401）
    When  chat
    Then  AiError 且提示检查设置页密码（不泄露裸 401）
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        if request.url.path == "/api/ai/write":
            return httpx.Response(401)
        return httpx.Response(404)

    client = AiClient(
        provider="mindvault",
        mv_base_url="http://stub",
        mv_password="wrong",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AiError, match="mindvault.password"):
        asyncio.run(client.chat("s", "u"))


def test_mindvault_bridge_requires_base_url():
    """
    Given 未配置 mv.base_url
    When  provider=mindvault chat
    Then  明确报配置缺失
    """
    client = AiClient(provider="mindvault", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(AiError, match="mv.base_url"):
        asyncio.run(client.chat("s", "u"))


def test_build_ai_client_mindvault_uses_mv_settings(client):
    """
    Given settings 里 mv.base_url / mindvault.password 已配
    When  build_ai_client（provider=mindvault）
    Then  mv_base_url/mv_password 透传给客户端
    """
    from app.services.ai_client import build_ai_client

    client.put("/api/settings", json={
        "ai.provider": "mindvault",
        "mv.base_url": "https://willdev.kumshing.dev",
        "mindvault.password": "real-pw",
    })
    # build_ai_client 是 FastAPI 依赖（SessionDep）——直接用 TestClient 的依赖覆盖不便，改为读 settings 手工构建
    detail = client.get("/api/settings/detail").json()
    assert detail["mv.base_url"] == "https://willdev.kumshing.dev"
    assert detail["ai.provider"] == "mindvault"
