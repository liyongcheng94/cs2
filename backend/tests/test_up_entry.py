"""UP 主投稿入口契约：payload.up_mid → 取最新投稿 → 学习流程复用。"""
import asyncio

import httpx
import pytest


@pytest.mark.anyio
async def test_search_user_videos_parses(monkeypatch):
    """
    Given user.get_videos 桩返回 vlist
    When  search_user_videos(mid, limit=2)
    Then  解析 bvid/title/author
    """
    import app.services.bili as b

    class StubUser:
        def __init__(self, uid, credential=None):
            pass

        async def get_videos(self, pn=1, ps=30, keyword="", order=None):
            return {"list": {"vlist": [
                {"bvid": "BV1u1", "title": "A大烟", "author": "教学UP", "created": 1700000000},
                {"bvid": "BV1u2", "title": "B点闪", "author": "教学UP", "created": 1699990000},
                {"bvid": "BV1u3", "title": "中路火", "author": "教学UP", "created": 1699980000},
            ]}}

    import bilibili_api.user as bu

    monkeypatch.setattr(bu, "User", StubUser)
    out = await b.search_user_videos(12345, "SESS", limit=2)
    assert [o["bvid"] for o in out] == ["BV1u1", "BV1u2"]


def test_bili_learn_up_mid_path(client, monkeypatch):
    client.put("/api/settings", json={"mv.enabled": "1"})
    """
    Given SESSDATA 已配 + 检索/字幕/AI 桩
    When  执行 bili_learn（up_mid）
    Then  学到 UP 最新投稿并推送
    """
    import app.services.bili_learn as bl

    async def fake_up(mid, sess, limit=3):
        return [{"bvid": "BV1UP1", "title": "UP投稿", "author": "UP", "pubdate": 1}]

    async def fake_fetch(bvid, sess):
        return [{"from": 12.5, "text": "字幕内容"}]

    monkeypatch.setattr(bl, "search_user_videos", fake_up)
    monkeypatch.setattr(bl, "fetch_subtitle_timed", fake_fetch)
    monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")
    monkeypatch.setattr(bl, "_new_ai", lambda: None)

    pushed = []

    class StubMV:
        async def push_note(self, title, content, topic_name=None, topic_id=None):
            pushed.append(title)
            return {"uuid": "up-u1"}

        async def update_note(self, uuid, content=None, title=None):
            return {"uuid": uuid}

    monkeypatch.setattr(bl, "_new_mv", lambda: StubMV())

    client.put("/api/settings", json={"bili.sessdata": "SESS"})
    task_id = client.post("/api/tasks", json={"type": "bili_learn", "payload": {"up_mid": 12345}}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success", body["error"]
    assert body["result"]["results"][0]["bvid"] == "BV1UP1"
    assert pushed == ["UP投稿"]


def test_bili_learn_generates_flashcards_for_new_note(client, monkeypatch):
    client.put("/api/settings", json={"mv.enabled": "1"})
    """
    Given 新笔记推送成功 + MindVault 闪卡生成桩
    When  bili_learn 新建总结
    Then  追加调用 /api/flashcards/generate（SRS 由 MindVault 管）
    """
    import json as _json

    import httpx as _httpx

    import app.services.bili_learn as bl
    from app.services.mindvault_client import MindVaultClient

    flash_calls = []

    def handler(request: _httpx.Request) -> _httpx.Response:
        if request.url.path == "/api/topics":
            return _httpx.Response(200, json=[]) if request.method == "GET" else _httpx.Response(201, json={"id": 1, "name": "CS2视频总结"})
        if request.url.path == "/api/mcp":
            body = _json.loads(request.content)
            return _httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": _json.dumps({"item_id": 1, "uuid": "sum-u9", "title": body["params"]["arguments"]["title"]})}], "isError": False}})
        if request.url.path == "/api/flashcards/generate":
            flash_calls.append(_json.loads(request.content))
            return _httpx.Response(200, json={"generated": 3})

    def stub_mv():
        return MindVaultClient(base_url="http://stub", transport=_httpx.MockTransport(handler))

    monkeypatch.setattr(bl, "_new_mv", stub_mv)
    async def fake_search(keyword, sess, page=1):
        return [{"bvid": "BV1FC", "title": "道具教学", "author": "UP", "pubdate": 1}]
    async def fake_fetch(bvid, sess):
        return [{"from": 1.0, "text": "字幕行"}]
    monkeypatch.setattr(bl, "search_videos", fake_search)
    monkeypatch.setattr(bl, "fetch_subtitle_timed", fake_fetch)
    monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")
    monkeypatch.setattr(bl, "_new_ai", lambda: None)

    client.put("/api/settings", json={"bili.sessdata": "SESS"})
    task_id = client.post("/api/tasks", json={"type": "bili_learn", "payload": {"keyword": "CS2"}}).json()["id"]
    run = client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success"
    assert flash_calls and flash_calls[0]["item_uuid"] == "sum-u9"
