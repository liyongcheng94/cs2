"""学道具 v3 Slice 4：教练联动 + 前端时效角标（TDD）。

场景（Given/When/Then）：
  S4.1 Given 卡 health=stale When _build_instruction Then 教练道具卡索引不含该卡（过期点位不教）
  S4.2 Given 卡 health=aging When _build_instruction Then 卡仍在索引但带「时效存疑」标注（降权提示）
  S4.3 Given 部分卡 stale/aging/alive 混合 When 索引 Then stale 不出现、aging 出现且带标注、alive 正常
前端（vitest，frontend/src/components/LearnPage.test.tsx 补场景）：
  S4.4 Given 卡 health=stale When 渲染卡 Then 红色角标（Tag color=red「过期」）
  S4.5 Given 卡 health=aging When 渲染 Then 黄色角标（color=gold「存疑」）
  S4.6 Given 卡 health=alive When 渲染 Then 无角标
"""
from __future__ import annotations

import pytest
from sqlmodel import Session

from app.database import get_engine
from app.models import GrenadeCard
from app.services.chat_coach import _build_instruction


def _mk_card(bvid: str, *, health: str = "alive", favorited: bool = False) -> int:
    with Session(get_engine()) as s:
        card = GrenadeCard(
            map_name="Mirage", grenade_type="smoke", source_hash=f"hash-{bvid}",
            bvid=bvid, favorited=favorited,
        )
        s.add(card)
        s.commit()
        s.refresh(card)
        card.health = health
        s.add(card)
        s.commit()
        return card.id


class TestCoachHealthFilter:
    def test_stale_card_excluded(self, client):
        stale_id = _mk_card("BV1s4stale001", health="stale")
        alive_id = _mk_card("BV1s4alive001")
        inst = _build_instruction()
        assert "BV1s4stale001" not in inst
        assert "BV1s4alive001" in inst

    def test_aging_card_marked(self, client):
        _mk_card("BV1s4aging001", health="aging")
        inst = _build_instruction()
        assert "BV1s4aging001" in inst
        # aging 卡必须带时效存疑标注（教练知道此点位可能已变）
        assert "时效存疑" in inst

    def test_mixed_cards_filtered_and_marked(self, client):
        _mk_card("BV1s4mixstale", health="stale")
        _mk_card("BV1s4mixaging", health="aging")
        _mk_card("BV1s4mixalive", health="alive", favorited=True)
        inst = _build_instruction()
        assert "BV1s4mixstale" not in inst
        assert "BV1s4mixaging" in inst
        assert "BV1s4mixalive" in inst
