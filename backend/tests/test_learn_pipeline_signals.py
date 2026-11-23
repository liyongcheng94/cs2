"""学道具 v3：学习链路集成——评论信号抓取 + video_pubdate 落卡。

场景（Given/When/Then）：
  I1 Given BV 学习（AI 产卡）When handler 完成 Then GrenadeCard.video_pubdate 已写入（来自 get_info.pubdate）
  I2 Given 新卡落库 When 学习完成 Then 评论信号已抓取：信号词命中的评论 → GrenadeCardSignal(source=comment) 落库
  I3 Given 评论带信号词但发布在视频 90 天窗内 When 学习 Then 不产出信号（窗对齐在链路里同样生效）
  I4 Given 评论接口风控/失败 When 学习 Then 学习主流程不受影响（卡片照常落库，无信号）
"""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlmodel import select

from app.database import session_factory
from app.models import GrenadeCard, GrenadeCardSignal, Task
from app.services import bili_learn as bl

NOW = 1_800_000_000  # 固定"现在"（约 2027-01-15）


def _run(payload: dict):
    task = Task(payload=payload)
    return asyncio.run(bl.bili_learn_handler(task, session_factory))


class FakeAI:
    async def chat(self, system, user):
        return json.dumps({
            "summary_md": "## 点位\nA1 烟。",
            "cards": [{"map": "Mirage", "point": "A1", "grenade_type": "烟雾弹",
                       "stance": "A1", "timing": "开局", "video_ts": "12:30",
                       "content_md": "瞄白车左键满力。"}],
        })


class StubMV:
    async def push_note(self, title, content, topic_name=None, topic_id=None):
        return {"uuid": f"uuid-{title[:6]}"}

    async def update_note(self, uuid, content=None, title=None):
        return {"uuid": uuid}


def _stub_info(monkeypatch, pubdate: int):
    """bvid 路径的 get_info 桩（含 pubdate）。"""

    class StubVideo:
        def __init__(self, bvid, credential=None):
            self.bvid = bvid

        async def get_info(self):
            return {"title": "CS2 Mirage 道具教学", "owner": {"name": "UP"},
                    "pubdate": pubdate}

    from bilibili_api import video as bvm

    monkeypatch.setattr(bvm, "Video", StubVideo)


def _stub_comments(monkeypatch, comments: list[tuple[int, str, int]]):
    async def fake_fetch_comments(bvid, max_pages=2):
        return comments

    import app.services.bili_signals as bs

    monkeypatch.setattr(bs, "fetch_comments", fake_fetch_comments)


class TestLearnPipelineSignals:
    def test_pubdate_written_and_signals_saved(self, client, monkeypatch):
        """
        I1+I2：BV 学习 → 卡带 video_pubdate；评论信号词命中（发布 90 天外）→ 信号落库。
        """
        import app.services.bili_learn as bl2

        pubdate = NOW - 200 * 86400  # 200 天前发布
        _stub_info(monkeypatch, pubdate)

        async def fake_fetch(bvid, sess):
            return [{"from": 12.5, "text": "字幕：A1 烟雾弹教学"}]

        # 一条 100 天后的信号词评论（出窗，有效）+ 一条 10 天后的（窗内，无效）
        _stub_comments(monkeypatch, [
            (pubdate + 100 * 86400, "这个烟现在还能用吗？改版后点位变了吗", 3),
            (pubdate + 10 * 86400, "被削了吧", 0),
        ])

        monkeypatch.setattr(bl2, "_credential_sess", lambda s: "SESS")
        monkeypatch.setattr(bl2, "fetch_subtitle_timed", fake_fetch)
        monkeypatch.setattr(bl2, "_new_ai", lambda: FakeAI())
        monkeypatch.setattr(bl2, "_new_mv", lambda: StubMV())

        out = _run({"bvid": "BV1signals01"})
        assert out["results"][0]["status"] == "ok"

        with session_factory() as s:
            card = s.exec(select(GrenadeCard).where(GrenadeCard.bvid == "BV1signals01")).first()
            assert card is not None
            assert card.video_pubdate == pubdate, "video_pubdate 未落卡"
            sigs = s.exec(select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card.id)).all()
            assert len(sigs) == 1, f"应恰好 1 条窗外语评信号，实际 {len(sigs)}"
            assert sigs[0].source == "comment"
            assert "还能用" in sigs[0].text

    def test_comment_failure_does_not_break_learn(self, client, monkeypatch):
        """I4：评论抓取炸了 → 学习照常成功（卡片/总结都在），无信号。"""
        import app.services.bili_learn as bl2

        pubdate = NOW - 100 * 86400
        _stub_info(monkeypatch, pubdate)

        async def fake_fetch(bvid, sess):
            return [{"from": 12.5, "text": "字幕"}]

        async def boom(bvid, max_pages=2):
            raise RuntimeError("network down")

        import app.services.bili_signals as bs
        monkeypatch.setattr(bs, "fetch_comments", boom)
        monkeypatch.setattr(bl2, "_credential_sess", lambda s: "SESS")
        monkeypatch.setattr(bl2, "fetch_subtitle_timed", fake_fetch)
        monkeypatch.setattr(bl2, "_new_ai", lambda: FakeAI())
        monkeypatch.setattr(bl2, "_new_mv", lambda: StubMV())

        out = _run({"bvid": "BV1signals02"})
        assert out["results"][0]["status"] == "ok"
        with session_factory() as s:
            card = s.exec(select(GrenadeCard).where(GrenadeCard.bvid == "BV1signals02")).first()
            assert card is not None
            sigs = s.exec(select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card.id)).all()
            assert sigs == []
