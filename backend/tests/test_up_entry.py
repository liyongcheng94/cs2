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
    """
    Given SESSDATA 已配 + 检索/字幕/AI 桩
    When  执行 bili_learn（up_mid）
    Then  学到 UP 最新投稿并推送
    """
    import app.services.bili_learn as bl

    async def fake_up(mid, sess, limit=3):
        return [{"bvid": "BV1UP1", "title": "UP投稿", "author": "UP", "pubdate": 1}]

    async def fake_fetch(bvid, sess):
        return "字幕内容"

    monkeypatch.setattr(bl, "search_user_videos", fake_up)
    monkeypatch.setattr(bl, "fetch_subtitle", fake_fetch)
    monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")
    monkeypatch.setattr(bl, "_new_ai", lambda: None)

    pushed = []

    async def fake_push(title, md, source_hash):
        pushed.append(title)
        return {"created": True, "uuid": "up-u1"}

    monkeypatch.setattr(bl, "_push_summary", fake_push)

    client.put("/api/settings", json={"bili.sessdata": "SESS"})
    task_id = client.post("/api/tasks", json={"type": "bili_learn", "payload": {"up_mid": 12345}}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success", body["error"]
    assert body["result"]["results"][0]["bvid"] == "BV1UP1"
    assert pushed == ["UP投稿"]
