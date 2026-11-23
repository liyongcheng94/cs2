"""字幕时间轴场景（grill-me + deepen v2 Phase 1.1）：

Given B站字幕 JSON 每行 {from, to, content}
When 学习该视频
Then handler 用 fetch_subtitle_timed 拿到 [{from, text}]，
     拼成 "[12.5s] 文本" 喂 AI，AI 输出的 video_ts 为字幕对应秒数（如 "43.2"）
且 prompt 明确禁止估算秒数。
"""
import asyncio
import json

import httpx
import pytest
from sqlmodel import select

from app.database import session_factory
from app.models import BiliVideo, GrenadeCard, Task
from app.services import bili as bili_mod
from app.services import bili_learn as bl
from app.services.bili import format_timed_subtitle


def _run(payload: dict):
    return asyncio.run(bl.bili_learn_handler(Task(payload=payload), session_factory))


class _StubMV:
    async def push_note(self, title, content, topic_name=None):
        return {"uuid": "stub-uuid-1"}

    async def update_note(self, uuid, content=None, title=None):
        return {"uuid": uuid}


class TestFormatTimedSubtitle:
    """[秒] 前缀格式化——喂 AI 的中间格式，机械可断言。"""

    def test_lines_prefixed_with_seconds(self):
        timed = [{"from": 12.5, "text": "VIP烟开局就丢"}, {"from": 43.2, "text": "拱门火贴B小丢"}]
        out = format_timed_subtitle(timed)
        assert "[12.5s] VIP烟开局就丢" in out
        assert "[43.2s] 拱门火贴B小丢" in out

    def test_empty_returns_empty(self):
        assert format_timed_subtitle([]) == ""

    def test_float_seconds_keep_decimal(self):
        out = format_timed_subtitle([{"from": 3.0, "text": "x"}])
        assert "[3.0s] x" in out


class TestFetchSubtitleTimed:
    """fetch_subtitle_timed：从字幕 JSON body 提取 {from, text}。"""

    @pytest.mark.anyio
    async def test_parses_body_rows(self, monkeypatch):
        body = {
            "subtitles": [{"lan": "zh-CN", "subtitle_url": "//example.com/sub.json"}]
        }
        sub_body = {
            "body": [
                {"from": 1.2, "to": 3.4, "content": "第一句"},
                {"from": 5.6, "to": 7.8, "content": "第二句"},
            ]
        }

        class FakeVideo:
            def __init__(self, *a, **k):
                pass

            async def get_info(self):
                return {"cid": 1}

            async def get_subtitle(self, cid):
                return body

        monkeypatch.setattr(bili_mod, "_video_factory", lambda bvid, cred: FakeVideo())

        def fake_http_get(url, **k):
            return httpx.Response(200, json=sub_body, request=httpx.Request("GET", url))

        monkeypatch.setattr(bili_mod.httpx, "get", fake_http_get)

        out = await bili_mod.fetch_subtitle_timed("BV1fakefake01", sessdata="SESS")
        assert out == [
            {"from": 1.2, "text": "第一句"},
            {"from": 5.6, "text": "第二句"},
        ]

    @pytest.mark.anyio
    async def test_no_subtitle_returns_none(self, monkeypatch):
        class FakeVideo:
            def __init__(self, *a, **k):
                pass

            async def get_info(self):
                return {"cid": 1}

            async def get_subtitle(self, cid):
                return {"subtitles": []}

        monkeypatch.setattr(bili_mod, "_video_factory", lambda bvid, cred: FakeVideo())
        out = await bili_mod.fetch_subtitle_timed("BV1fakefake01", sessdata="")
        assert out is None


class TestHandlerUsesTimeline:
    """学习 handler 拿到 timed 字幕后拼 [秒] 前缀喂 AI；卡 video_ts 透传 AI 值。"""

    def test_prompt_receives_timed_lines_and_card_ts_persisted(self, client, monkeypatch):
        captured: dict = {}

        async def fake_timed(bvid, sessdata):
            return [
                {"from": 12.5, "text": "VIP烟开局就丢"},
                {"from": 43.2, "text": "拱门火贴B小丢"},
            ]

        class FakeAI:
            async def chat(self, system, user):
                captured["system"] = system
                captured["user"] = user
                return json.dumps(
                    {
                        "summary_md": "## 总结",
                        "cards": [
                            {
                                "map": "Mirage",
                                "point": "拱门",
                                "grenade_type": "燃烧弹",
                                "stance": "B小",
                                "timing": "开局",
                                "video_ts": "43.2",
                                "content_md": "贴B小丢",
                                "zone": "中路",
                            }
                        ],
                    }
                )

        async def fake_meta(bvid, sessdata):
            return {"cover": "http://c", "duration": 648, "owner_mid": 1}

        monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")
        monkeypatch.setattr(bl, "fetch_subtitle_timed", fake_timed)
        monkeypatch.setattr(bl, "fetch_video_meta", fake_meta)
        monkeypatch.setattr(bl, "_new_ai", lambda: FakeAI())
        monkeypatch.setattr(bl, "_new_mv", lambda: _StubMV())

        out = _run({"bvid": "BV1timeline012"})
        assert out["results"][0]["status"] == "ok"

        # AI 收到的字幕带 [秒] 前缀（时间轴信息未在源头被扔掉）
        assert "[12.5s] VIP烟开局就丢" in captured["user"], "handler 未把 timed 字幕喂给 AI"
        assert "[43.2s] 拱门火贴B小丢" in captured["user"]

        # prompt 强制秒数且禁估算
        assert "禁止估算" in captured["system"] or "不得估算" in captured["system"]

        # 卡片 video_ts 透传落库（resolve_bvid 只取 BV+10 位，BV1timeline012 → BV1timeline0）
        with session_factory() as s:
            row = s.exec(
                select(GrenadeCard).where(GrenadeCard.bvid == "BV1timeline0")
            ).first()
            assert row is not None
            assert row.video_ts == "43.2"
