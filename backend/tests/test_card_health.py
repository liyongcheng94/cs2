# 学道具 v3 Slice 2+3：卡过期上报 + card_health 三信号聚合（TDD）
#
# Given 用户是时效最强信号源 When 点「过期」上报 Then 卡 health 直接降级 stale 并记录信号
# Given 评论信号/补丁对照 When 聚合 Then alive/aging/stale 按优先级：report > comment > patch
# Given Steam News 有 grenade 更新 When 视频早于补丁 Then 卡 aging 提示
#
# 场景覆盖：
#   S2.1 POST stale-report → health=stale + GrenadeCardSignal(source=report) 入库
#   S2.2 不存在的卡 → 404；重复上报幂等（不重复记信号，返回当前状态）
#   S2.3 聚合：无任何信号 → alive（默认）
#   S2.4 聚合：有 report 信号 → stale（最高优先级）
#   S2.5 聚合：近 90 天评论信号 ≥1 → aging
#   S2.6 聚合：视频发布早于含 grenade 词的 Steam 补丁 → aging（patch 信号）
#   S2.7 聚合优先级：report 覆盖 comment/patch（stale 不被降级回 aging）
#   S2.8 聚合入口 API：POST /bili/grenades/{id}/refresh-health → 返回新 health
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models import GrenadeCard, GrenadeCardSignal


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _mk_card(bvid: str) -> int:
    with Session(__import__("app.database", fromlist=["get_engine"]).get_engine()) as s:
        card = GrenadeCard(map_name="Mirage", grenade_type="smoke", source_hash=f"hash-{bvid}", bvid=bvid)
        s.add(card)
        s.commit()
        s.refresh(card)
        return card.id


class TestStaleReport:
    """S2.1/S2.2 用户上报过期。"""

    def test_stale_report_downgrades_to_stale(self, client):
        card_id = _mk_card("BV1report0001")
        resp = client.post(f"/api/bili/grenades/{card_id}/stale-report", json={"note": "这个点位现在扔不了"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["health"] == "stale"
        # 信号入库
        with Session(__import__("app.database", fromlist=["get_engine"]).get_engine()) as s:
            sigs = s.exec(select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card_id)).all()
            assert len(sigs) == 1
            assert sigs[0].source == "report"
            assert "扔不了" in sigs[0].text

    def test_stale_report_404_and_idempotent(self, client):
        assert client.post("/api/bili/grenades/999/stale-report", json={}).status_code == 404
        card_id = _mk_card("BV1report0002")
        r1 = client.post(f"/api/bili/grenades/{card_id}/stale-report", json={"note": "x"})
        r2 = client.post(f"/api/bili/grenades/{card_id}/stale-report", json={"note": "x"})
        assert r1.status_code == 200 and r2.status_code == 200
        # 幂等：信号只记一条
        with Session(__import__("app.database", fromlist=["get_engine"]).get_engine()) as s:
            sigs = s.exec(select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card_id)).all()
            assert len(sigs) == 1


def _add_signal(card_id: int, source: str, ctime: int | None = None):
    with Session(__import__("app.database", fromlist=["get_engine"]).get_engine()) as s:
        s.add(GrenadeCardSignal(card_id=card_id, source=source, text="信号", ctime=ctime))
        s.commit()


class TestHealthAggregate:
    """S2.3-S2.8 三信号聚合。"""

    def _aggregate(self, card_id: int, client) -> dict:
        return client.post(f"/api/bili/grenades/{card_id}/refresh-health").json()

    def test_no_signals_alive(self, client):
        card_id = _mk_card("BV1health001")
        assert self._aggregate(card_id, client)["health"] == "alive"

    def test_report_signal_stale(self, client):
        card_id = _mk_card("BV1health002")
        _add_signal(card_id, "report")
        assert self._aggregate(card_id, client)["health"] == "stale"

    def test_recent_comment_aging(self, client):
        card_id = _mk_card("BV1health003")
        _add_signal(card_id, "comment", ctime=int(time.time()) - 86400 * 10)  # 10 天前
        assert self._aggregate(card_id, client)["health"] == "aging"

    def test_old_comment_ignored(self, client):
        """Given 评论信号是 400 天前的 When 聚合 Then 仍 alive（时效窗内才算）。"""
        card_id = _mk_card("BV1health004")
        _add_signal(card_id, "comment", ctime=int(time.time()) - 86400 * 400)
        assert self._aggregate(card_id, client)["health"] == "alive"

    def test_patch_signal_aging(self, client, monkeypatch):
        """Given 视频发布早于含 grenade 词的 Steam 更新 When 聚合 Then aging。"""
        card_id = _mk_card("BV1health005")
        with Session(__import__("app.database", fromlist=["get_engine"]).get_engine()) as s:
            card = s.get(GrenadeCard, card_id)
            card.video_pubdate = 1600000000  # 2020-09（早于补丁）
            s.add(card)
            s.commit()
        # Steam news 桩：一条最近的 grenade 更新
        from app.services import bili_health

        monkeypatch.setattr(
            bili_health, "fetch_grenade_patch_dates",
            lambda: [1700000000],  # 2023-11 的补丁
        )
        assert self._aggregate(card_id, client)["health"] == "aging"

    def test_report_overrides_comment(self, client):
        """Given report + comment 同时存在 When 聚合 Then stale（report 优先级最高）。"""
        card_id = _mk_card("BV1health006")
        _add_signal(card_id, "report")
        _add_signal(card_id, "comment", ctime=int(time.time()) - 100)
        assert self._aggregate(card_id, client)["health"] == "stale"
