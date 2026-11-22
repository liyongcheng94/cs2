"""AI 教练对话契约：多轮会话持久化 + 上下文注入（画像/最近复盘）+ MindVault AI 桥。"""
import json

import httpx
import pytest


@pytest.fixture()
def stub_ai_bridge(client, monkeypatch):
    """AI 桩：build_ai_client 返回 MockTransport 版 AiClient（记录 instruction/content）。"""
    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"text": "教练回复"})

    def fake_build(session):
        return AiClient(provider="mindvault", mv_base_url="http://stub", mv_password="pw",
                        transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cc, "build_ai_client", fake_build)
    return seen


def _seed_session_with_history(client):
    """建会话并注入一轮历史（直接走 API）。"""
    s = client.post("/api/chat/sessions").json()
    return s["id"]


def test_chat_creates_session_and_persists(client, stub_ai_bridge):
    """
    Given 新会话
    When  POST /api/chat {"content": "我这周道具怎么练"}
    Then  助手回复入库；会话标题取首句；GET messages 返回 user+assistant 两轮
    """
    sid = _seed_session_with_history(client)
    resp = client.post("/api/chat", json={"session_id": sid, "content": "我这周道具怎么练"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "教练回复"

    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "我这周道具怎么练"

    sess = client.get("/api/chat/sessions").json()
    mine = next(x for x in sess if x["id"] == sid)
    assert mine["title"] != "新对话"  # 首句自动作标题


def test_chat_second_round_carries_history(client, stub_ai_bridge):
    """
    Given 已有一轮对话
    When  第二轮提问
    Then  AI 桥收到的 instruction/content 含完整历史（多轮上下文）
    """
    sid = _seed_session_with_history(client)
    client.post("/api/chat", json={"session_id": sid, "content": "第一问"})
    client.post("/api/chat", json={"session_id": sid, "content": "第二问"})
    assert len(stub_ai_bridge) == 2
    # 第二轮的 content 应包含历史（user/assistant 标记）
    assert "第一问" in stub_ai_bridge[1]["text"]


def test_chat_injects_context(client, stub_ai_bridge):
    """
    Given 玩家画像与最近复盘存在
    When  chat
    Then  instruction 注入画像（eDPI/主图/等级）与最近复盘标题
    """
    from sqlmodel import select

    from app.database import session_factory
    from app.models import Report

    with session_factory() as s:
        s.add(Report(match_id="PVP@CTX", prompt_version="v1", source_hash="ctx-hash",
                     title="复盘 · PVP@CTX", content_md="失误：近战急停"))
        s.commit()

    sid = _seed_session_with_history(client)
    client.post("/api/chat", json={"session_id": sid, "content": "我最近最该练什么"})
    instruction = stub_ai_bridge[0]["instruction"]
    assert "eDPI" in instruction and "Dust2" in instruction
    assert "复盘 · PVP@CTX" in instruction


def test_chat_session_list_and_delete(client, monkeypatch):
    """
    Given 两个会话
    When  DELETE 其中一个
    Then  列表剩一个且其消息级联删除
    """
    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    monkeypatch.setattr(cc, "build_ai_client", lambda session: AiClient(
        provider="mindvault", mv_base_url="http://stub", mv_password="pw",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "ok"}))))
    s1 = client.post("/api/chat/sessions").json()["id"]
    s2 = client.post("/api/chat/sessions").json()["id"]
    client.post("/api/chat", json={"session_id": s1, "content": "hi"})
    client.delete(f"/api/chat/sessions/{s1}")
    sess = client.get("/api/chat/sessions").json()
    assert [x["id"] for x in sess] == [s2]
    msgs = client.get(f"/api/chat/sessions/{s1}/messages").json()
    assert msgs == []


def test_chat_ai_unavailable_surfaces_error(client, monkeypatch):
    """
    Given AI 桥失败（密码错/网络）
    When  POST /api/chat
    Then  502 且 error 含人话原因（不存 assistant 假回复）
    """
    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "mv_session=t; Path=/"})
        return httpx.Response(401)

    monkeypatch.setattr(cc, "build_ai_client", lambda session: AiClient(
        provider="mindvault", mv_base_url="http://stub", mv_password="bad",
        transport=httpx.MockTransport(handler)))
    sid = _seed_session_with_history(client)
    resp = client.post("/api/chat", json={"session_id": sid, "content": "hi"})
    assert resp.status_code == 502
    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user"]  # 只有用户消息，无假回复
