"""学道具重设计（2026-11-23 grill-me 共识）：VideoSummary 本地存储 + 封面元数据。

场景：
1. 学习完成时总结全文落本地 VideoSummary 表（CS2HQ 自站可看，不依赖 MV 在线）。
2. /bili/videos 返回 summary_md 与封面（从 BiliVideo.raw 取），前端卡片墙直接渲染。
3. fetch_video_meta 抓封面/时长，学习路径顺手写 raw（零额外请求）。
4. 重学同 BV → VideoSummary 幂等更新（按 bvid 唯一）。
"""
import asyncio
import hashlib
import json

import pytest

from app.database import session_factory
from app.models import BiliVideo, VideoSummary
from app.services import bili_learn as bl


def _run(payload: dict):
    task = Task(payload=payload)
    return asyncio.run(bl.bili_learn_handler(task, session_factory))


from app.models import Task  # noqa: E402


class TestVideoSummaryTable:
    def test_learning_writes_summary_locally(self, client, monkeypatch):
        """
        Given BV 视频字幕可取、AI 返回结构化总结（含 summary_md 与 1 张道具卡）
        When  执行 bili_learn
        Then  本地 VideoSummary 出现该 bvid 的总结行（summary_md 全文一致）
        """
        import app.services.bili_learn as bl2

        async def fake_fetch(bvid, sess):
            return "字幕内容：Mirage A点烟雾弹教学"

        class FakeAI:
            async def chat(self, system, user):
                return json.dumps({
                    "summary_md": "## 点位与站位\n站在 A1 瞄白车边缘。",
                    "cards": [{"map": "Mirage", "point": "A1", "grenade_type": "烟雾弹",
                               "stance": "A1 火点", "timing": "开局", "video_ts": "",
                               "content_md": "瞄白车边缘左键满力。"}],
                })

        monkeypatch.setattr(bl2, "_credential_sess", lambda s: "SESS")
        monkeypatch.setattr(bl2, "fetch_subtitle", fake_fetch)
        monkeypatch.setattr(bl2, "_new_ai", lambda: FakeAI())
        monkeypatch.setattr(bl2, "_new_mv", lambda: _StubMV())

        out = _run({"bvid": "BV1SummaryAA"})
        assert out["results"][0]["status"] == "ok"

        with session_factory() as s:
            row = s.exec(_select_summary("BV1SummaryAA")).first()
            assert row is not None, "总结未落本地 VideoSummary"
            assert "点位与站位" in row.summary_md

    def test_relearn_updates_summary_idempotent(self, client, monkeypatch):
        """
        Given 同一 BV 已有 VideoSummary
        When  重学（AI 总结变化）
        Then  VideoSummary 按 bvid 更新，不产生第二行
        """
        import app.services.bili_learn as bl2

        class FakeAI:
            def __init__(self, tag):
                self.tag = tag

            async def chat(self, system, user):
                return json.dumps({"summary_md": f"## 版本{self.tag}", "cards": []})

        monkeypatch.setattr(bl2, "_credential_sess", lambda s: "SESS")
        monkeypatch.setattr(bl2, "fetch_subtitle", lambda bv, sess: asyncio.sleep(0, result="字幕"))
        monkeypatch.setattr(bl2, "_new_mv", lambda: _StubMV())

        monkeypatch.setattr(bl2, "_new_ai", lambda: FakeAI("v1"))
        _run({"bvid": "BV1SummaryBB"})
        monkeypatch.setattr(bl2, "_new_ai", lambda: FakeAI("v2"))
        _run({"bvid": "BV1SummaryBB"})

        with session_factory() as s:
            rows = s.exec(_select_summary("BV1SummaryBB")).all()
            assert len(rows) == 1, f"重学产生重复行: {len(rows)}"
            assert "版本v2" in rows[0].summary_md


class _StubMV:
    async def push_note(self, title, content, topic_name=None):
        return {"uuid": "stub-uuid-1"}

    async def update_note(self, uuid, content=None, title=None):
        return {"uuid": uuid}


def _select_summary(bvid: str):
    from sqlmodel import select
    return select(VideoSummary).where(VideoSummary.bvid == bvid)


class TestVideosApiShape:
    def test_bili_videos_returns_summary_and_cover(self, client):
        """
        Given 本地有 VideoSummary 与 raw.cover
        When  GET /api/bili/videos
        Then  响应含 summary_md、cover、duration（前端卡片墙直接渲染）
        """
        from sqlmodel import Session

        with session_factory() as s:
            s.add(BiliVideo(bvid="BV1ApicoverX", title="封面测试视频", owner="UP",
                            subtitle_status="subtitle",
                            raw={"cover": "http://i1.hdslb.com/bfs/x.jpg", "duration": 648}))
            s.add(VideoSummary(bvid="BV1ApicoverX", summary_md="## 总结正文"))
            s.commit()

        rows = [v for v in client.get("/api/bili/videos").json() if v["bvid"] == "BV1ApicoverX"]
        assert rows, "videos 列表缺行"
        r = rows[0]
        assert r["summary_md"] == "## 总结正文"
        assert r["cover"] == "http://i1.hdslb.com/bfs/x.jpg"
        assert r["duration"] == 648
