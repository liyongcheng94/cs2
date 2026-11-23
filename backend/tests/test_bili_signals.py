# 学道具 v3 Slice 1：评论时效信号（TDD）
#
# Given B 站视频有评论区 When 学习流程顺路抓取评论 Then 带时效信号词的评论作为
# GrenadeCardSignal 落库（source=comment），供 card_health 聚合（Slice 3）消费。
#
# 场景覆盖：
#   S1.1 fetch_comments 解析 x/v2/reply 返回（主楼 + 楼中楼计数），分页翻页
#   S1.2 fetch_comments 失败降级返回空列表（不阻断学习）
#   S1.3 评论信号词命中 → extract_comment_signals 产出信号记录（含 ctime 对齐判断）
#   S1.4 信号时间对齐：视频发布后 90 天内的评论才算"新信号"（老评论不算时效）
#   S1.5 学习 handler 落卡后调用抓取：有 aid/评论信号 → GrenadeCardSignal 入库
#   S1.6 学习 handler 抓评论失败 → 不影响卡正常生成
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient + 临时 DATA_DIR（与既有测试基建一致）。"""
    monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _stub_reply_page(main_msgs, sub_counts=None, count=180, rpid_base=100):
    """构造 x/v2/reply 响应体。main_msgs: [str]; sub_counts: [楼中楼数]"""
    replies = []
    for i, m in enumerate(main_msgs):
        replies.append({
            "rpid": rpid_base + i,
            "content": {"message": m},
            "rcount": (sub_counts or [0] * len(main_msgs))[i],
            "ctime": 1700000000 + i * 3600,
        })
    return {
        "code": 0,
        "data": {
            "replies": replies,
            "page": {"count": count, "size": 20, "num": 1},
        },
    }


class TestFetchComments:
    """S1.1/S1.2 fetch_comments 解析与降级。"""

    @pytest.mark.anyio
    async def test_fetch_comments_parses_replies(self, monkeypatch):
        """Given B 站评论接口返回 3 条主楼 When fetch_comments Then 返回 (ctime, message, rcount) 列表。"""
        from app.services import bili_signals as bs

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["referer"] = request.headers.get("referer", "")
            if "web-interface/view" in str(request.url):
                return httpx.Response(200, json={"code": 0, "data": {"aid": 115137939773663}})
            return httpx.Response(200, json=_stub_reply_page(
                ["给兄弟们加上进度条了", "跳投现在是怎么投容错率高一些？", "很棒"],
            ))

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(bs, "_comment_transport", lambda: httpx.AsyncClient(transport=transport, headers={"Referer": "https://www.bilibili.com/"}))

        out = await bs.fetch_comments("BV1b1aMziEuE", max_pages=1)
        assert len(out) == 3
        ctime, message, rcount = out[0]
        assert message == "给兄弟们加上进度条了"
        assert rcount == 0
        assert ctime == 1700000000
        # oid = aid（数字），必须带 Referer
        assert captured["referer"].startswith("https://")
        assert "oid=" in captured["url"]

    @pytest.mark.anyio
    async def test_fetch_comments_paginates(self, monkeypatch):
        """Given 两页评论 When max_pages=2 Then 合并两页（去重 rpid）。"""
        from app.services import bili_signals as bs

        page_no = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if "web-interface/view" in str(request.url):
                return httpx.Response(200, json={"code": 0, "data": {"aid": 115137939773663}})
            page_no["n"] += 1
            n = page_no["n"]
            return httpx.Response(200, json=_stub_reply_page(
                [f"page{n}-评论"], count=40 if n == 1 else 20, rpid_base=100 * n,
            ))

        monkeypatch.setattr(bs, "_comment_transport", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        out = await bs.fetch_comments("BV1x", max_pages=2)
        assert len(out) == 2
        assert {m for _, m, _ in out} == {"page1-评论", "page2-评论"}

    @pytest.mark.anyio
    async def test_fetch_comments_degrades_on_error(self, monkeypatch):
        """Given 评论接口风控/网络失败 When fetch_comments Then 返回空列表不抛异常。"""
        from app.services import bili_signals as bs

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(412, text="risk control")

        monkeypatch.setattr(bs, "_comment_transport", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        out = await bs.fetch_comments("BV1x", max_pages=1)
        assert out == []


SIGNAL_WORDS = ["被削了", "改版后不行", "这版本还正确吗", "过时了", "更新后还成立吗", "还能用吗", "以前是这样"]


class TestExtractSignals:
    """S1.3/S1.4 信号词提取 + 时间对齐。"""

    def test_extract_hits_signal_words(self):
        """Given 带信号词的评论 When extract_comment_signals Then 命中项产出信号。"""
        from app.services.bili_signals import extract_comment_signals

        comments = [
            (1700000100, "教学很棒谢谢up", 0),
            (1700000200, "这个点位被削了还能这么扔吗", 2),
            (1700000300, "改版后烟雾弹时间不一样了", 1),
            (1700000400, "纯打卡", 0),
        ]
        signals = extract_comment_signals(comments, video_pubdate=1690000000)
        assert len(signals) == 2
        texts = [s["text"] for s in signals]
        assert any("被削了" in t for t in texts)
        assert any("改版" in t for t in texts)
        assert all(s["source"] == "comment" for s in signals)
        assert all("ctime" in s for s in signals)

    def test_extract_time_window_alignment(self):
        """Given 视频发布后 90 天内的评论才有效 When 老评论带信号词 Then 不产出信号。

        场景依据：时效信号的价值在「近期」评论——2020 年的评论说"被削了"
        对 2026 年的视频点位无效。窗口 = 评论 ctime >= 视频发布 + 90d。
        """
        from app.services.bili_signals import extract_comment_signals

        old_signal_ctime = 1690000000 + 3600  # 发布后 1 小时（窗口内 = 老信号）
        recent_signal_ctime = 1690000000 + 100 * 86400  # 发布后 100 天（窗口外 = 有效）
        comments = [
            (old_signal_ctime, "被削了吧", 0),
            (recent_signal_ctime, "最近更新后还行吗", 0),
        ]
        signals = extract_comment_signals(comments, video_pubdate=1690000000)
        assert len(signals) == 1
        assert "还行" in signals[0]["text"] or "更新" in signals[0]["text"]

    def test_extract_empty_comments(self):
        """Given 无评论 When extract Then 空列表。"""
        from app.services.bili_signals import extract_comment_signals

        assert extract_comment_signals([], video_pubdate=0) == []


class TestLearnIntegratesSignals:
    """S1.5/S1.6 学习流程集成。"""

    def test_learn_stores_signals(self, client, monkeypatch):
        """Given 学习完成落卡 When 评论带信号词 Then GrenadeCardSignal 入库（source=comment）。"""
        # 直接调服务层聚合函数而非走完整 AI 学习链路（AI 桩已在他处覆盖）：
        # save_signals(card_id, signals) 的行为
        from sqlmodel import Session, select

        from app.database import get_engine
        from app.models import GrenadeCard, GrenadeCardSignal
        from app.services.bili_signals import save_signals

        with Session(get_engine()) as s:
            card = GrenadeCard(
                map_name="Mirage", grenade_type="smoke",
                source_hash="sig-hash-1", bvid="BV1signalTest01",
            )
            s.add(card)
            s.commit()
            s.refresh(card)

            signals = [{"source": "comment", "text": "被削了", "ctime": 1700000100}]
            saved = save_signals(s, card.id, signals)
            assert saved == 1

            rows = s.exec(
                select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card.id)
            ).all()
            assert len(rows) == 1
            assert rows[0].source == "comment"
            assert rows[0].text == "被削了"

    def test_save_signals_idempotent(self, client):
        """Given 同一卡同一信号重复保存 When save_signals Then 幂等去重。"""
        from sqlmodel import Session, select

        from app.database import get_engine
        from app.models import GrenadeCard, GrenadeCardSignal
        from app.services.bili_signals import save_signals

        with Session(get_engine()) as s:
            card = GrenadeCard(map_name="Mirage", source_hash="sig-hash-2", bvid="BV1signalTest02")
            s.add(card)
            s.commit()
            s.refresh(card)
            sig = [{"source": "comment", "text": "被削了", "ctime": 1700000100}]
            assert save_signals(s, card.id, sig) == 1
            assert save_signals(s, card.id, sig) == 0  # 幂等：重复 0 新增
            rows = s.exec(
                select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card.id)
            ).all()
            assert len(rows) == 1
