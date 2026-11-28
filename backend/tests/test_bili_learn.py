"""B站学习任务编排契约：BV 入口信息回填 / AI 总结道具卡入库 / 推送幂等更新 / 无字幕与垃圾输出降级。"""
import asyncio
import json

import pytest
from sqlmodel import select

from app.database import session_factory
from app.models import BiliVideo, GrenadeCard, Task
from app.services.bili_learn import bili_learn_handler, _ai_summarize


class StubAI:
    provider = "deepseek"

    def __init__(self, reply: str):
        self.reply = reply

    async def chat(self, system, user):
        return self.reply


AI_JSON = json.dumps({
    "summary_md": "# A大烟\n\n- 站位：A大死角",
    "cards": [{"map": "de_dust2", "point": "A大", "grenade_type": "smoke", "stance": "站",
               "timing": "开局", "video_ts": "00:12", "content_md": "瞄房顶右边缘"}],
}, ensure_ascii=False)


class StubMV:
    def __init__(self):
        self.pushed: list[str] = []
        self.updated: list[str] = []

    async def push_note(self, title, content, topic_name=None, topic_id=None):
        self.pushed.append(title)
        return {"uuid": f"mv-{len(self.pushed)}"}

    async def update_note(self, uuid, content=None, title=None):
        self.updated.append(uuid)
        return {"uuid": uuid}


def _install_stubs(monkeypatch, ai_reply: str | None, subtitle: str | None, mv: StubMV):
    import app.services.bili_learn as bl

    class StubVideo:
        def __init__(self, bvid, credential=None):
            pass

        async def get_info(self):
            return {"title": "A大道具教学", "owner": {"name": "教学UP"}}

    import bilibili_api.video as bv_mod

    monkeypatch.setattr(bv_mod, "Video", StubVideo)
    monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")

    async def fake_fetch(bvid, sess):
        if subtitle is None:
            return None
        return [{"from": 12.5, "text": subtitle}]

    monkeypatch.setattr(bl, "fetch_subtitle_timed", fake_fetch)
    monkeypatch.setattr(bl, "time", type("T", (), {"sleep": staticmethod(lambda s: None), "time": staticmethod(lambda: 0.0)}))
    monkeypatch.setattr(bl, "_new_ai", (lambda: StubAI(ai_reply)) if ai_reply is not None else (lambda: None))
    monkeypatch.setattr(bl, "_new_mv", lambda: mv)


def _run(payload: dict):
    task = Task(id=1, type="bili_learn", payload=payload)
    return asyncio.run(bili_learn_handler(task, session_factory))


def test_bili_learn_bvid_full_ai_path(client, monkeypatch):
    client.put("/api/settings", json={"mv.enabled": "1"})
    """
    Given BV 入口 + 字幕桩 + AI 桩（合法 JSON 双段输出）+ MindVault 桩
    When  执行 bili_learn
    Then  视频信息回填（title/owner）、道具卡入库（source_hash 幂等键）、总结推送并回写 mv_uuid
    """
    _install_stubs(monkeypatch, AI_JSON, "字幕正文", StubMV())
    out = _run({"bvid": "BV1GJ411x7h7"})
    assert out["count"] == 1
    r = out["results"][0]
    assert r["status"] == "ok" and r["cards"] == 1 and r["pushed"] is True

    with session_factory() as s:
        row = s.exec(select(BiliVideo).where(BiliVideo.bvid == "BV1GJ411x7h7")).one()
        assert row.title == "A大道具教学" and row.owner == "教学UP"
        assert row.subtitle_status == "subtitle" and row.mv_uuid == "mv-1"
        cards = s.exec(select(GrenadeCard).where(GrenadeCard.bvid == "BV1GJ411x7h7")).all()
        assert len(cards) == 1 and cards[0].map_name == "de_dust2"


def test_bili_learn_repeat_keeps_single_card(client, monkeypatch):
    """
    Given 同一 BV 重复学习（source_hash 相同）
    When  再跑一次 handler
    Then  道具卡不重复入库（幂等），推送走 update（created=False）
    """
    _install_stubs(monkeypatch, AI_JSON, "字幕正文", StubMV())
    _run({"bvid": "BV1GJ411x7h7"})
    mv = StubMV()
    _install_stubs(monkeypatch, AI_JSON, "字幕正文", mv)
    out = _run({"bvid": "BV1GJ411x7h7"})
    assert out["results"][0]["pushed"] is False
    with session_factory() as s:
        cards = s.exec(select(GrenadeCard).where(GrenadeCard.bvid == "BV1GJ411x7h7")).all()
        assert len(cards) == 1


def test_bili_learn_no_subtitle_marks_skipped(client, monkeypatch):
    """
    Given 字幕桩返回 None（视频无字幕轨）
    When  执行 bili_learn
    Then  状态标 no_subtitle 跳过，不入道具卡
    """
    _install_stubs(monkeypatch, None, None, StubMV())
    out = _run({"bvid": "BV1GJ411x7h7"})
    assert out["results"][0]["status"] == "no_subtitle"
    with session_factory() as s:
        row = s.exec(select(BiliVideo).where(BiliVideo.bvid == "BV1GJ411x7h7")).one()
        assert row.subtitle_status == "no_subtitle"


def test_bili_learn_empty_payload_raises(client, monkeypatch):
    """
    Given payload 缺 bvid/up_mid/keyword
    When  执行 bili_learn
    Then  抛 ValueError 提示入参要求
    """
    _install_stubs(monkeypatch, None, None, StubMV())
    with pytest.raises(ValueError, match="bvid"):
        _run({})


def test_bili_learn_without_ai_degrades_to_raw_subtitle(client, monkeypatch):
    """
    Given 未配置 AI（_new_ai → None）且有字幕
    When  执行 bili_learn
    Then  降级：字幕原文入库为总结（不丢数据），无道具卡
    """
    _install_stubs(monkeypatch, None, "字幕正文原文", StubMV())
    out = _run({"bvid": "BV1GJ411x7h7"})
    assert out["results"][0]["status"] == "ok" and out["results"][0]["cards"] == 0


@pytest.mark.anyio
async def test_ai_summarize_degrades_on_garbage_output(client):
    """
    Given AI 返回非 JSON 文本（护栏失效场景）
    When  _ai_summarize
    Then  降级为"原文标注总结 + 空卡"，绝不抛异常崩任务（当前实现会 AttributeError——RED）
    """
    out_summary, cards = await _ai_summarize(StubAI("抱歉，我无法按格式输出。"), "标题", "字幕")
    assert isinstance(cards, list)
    assert "字幕" in out_summary or out_summary != ""
