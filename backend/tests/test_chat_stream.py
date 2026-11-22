"""对话流式契约：SSE 增量输出 + 历史持久化 + mindvault 非流式单段回退。"""
import json

import httpx
import pytest

from app.services.ai_client import AiClient

SSE_BODY = '\n'.join([
    'data: {"choices":[{"delta":{"content":"近战"}}]}',
    'data: {"choices":[{"delta":{"content":"急停"}}]}',
    'data: [DONE]',
    '',
])


@pytest.mark.anyio
async def test_chat_stream_yields_deltas(monkeypatch):
    """
    Given DeepSeek SSE 桩
    When  chat_stream
    Then  逐段 yield 增量文本
    """
    import app.services.ai_client as ac

    def handler(url: str, json_body=None, **kw) -> httpx.Response:
        assert json_body["stream"] is True
        return httpx.Response(200, content=SSE_BODY, headers={"content-type": "text/event-stream"})

    def fake_stream(self, method, url, **kw):
        return _StubStream(handler(url, json_body=kw.get("json"), **kw))

    monkeypatch.setattr(ac.httpx.AsyncClient, "stream", fake_stream)

    client = AiClient(provider="deepseek", api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    deltas = [d async for d in client.chat_stream("s", "u")]
    assert deltas == ["近战", "急停"]


class _StubStream:
    def __init__(self, response):
        self._resp = response

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for line in self._resp.text.split("\n"):
            yield line


def test_chat_stream_endpoint_sse_and_persist(client, monkeypatch):
    """
    Given AI 桩（单段模式）
    When  POST /api/chat/stream（SSE）
    Then  响应含 delta 与 done 事件；assistant 消息持久化
    """
    import app.services.chat_coach as cc
    from app.services.ai_client import AiClient

    class StubAI(AiClient):
        def __init__(self):
            super().__init__(provider="mindvault", mv_base_url="http://stub")

        async def chat_stream(self, system, user):
            yield "流式回复"

    monkeypatch.setattr(cc, "build_ai_client", lambda session: StubAI())
    sid = client.post("/api/chat/sessions").json()["id"]

    with client.stream("POST", "/api/chat/stream", json={"session_id": sid, "content": "问一句"}) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    deltas = [e["delta"] for e in events if "delta" in e]
    assert deltas == ["流式回复"]
    assert any(e.get("done") for e in events)

    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "流式回复"
