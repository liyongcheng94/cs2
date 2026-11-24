"""GREEN 前置 RED：真实 demo 里 official_end_tick 可能为 None（awpy 3.3.0 rounds 数据集
个别回合缺该列，实测 9206592914164159628 场 round 24）。_round_of_tick 必须容错。"""
from __future__ import annotations

import polars as pl

from app.services.demo_analysis import _round_of_tick


def _rounds(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def test_round_of_tick_tolerates_none_official_end():
    """
    Given 某回合 official_end_tick 为 None（真实 demo 缺该列）
    When  _round_of_tick 查该区间内/外 tick
    Then  区间内按 end_tick 兜底仍命中，None 区间外不命中也不抛 TypeError
    """
    rounds = _rounds(
        [
            {"round_num": 1, "start_tick": 0, "end_tick": 1000, "official_end_tick": 1000, "winner": 2},
            {"round_num": 2, "start_tick": 1001, "end_tick": 2000, "official_end_tick": None, "winner": 3},
        ]
    )
    assert _round_of_tick(rounds, 500) == 1
    assert _round_of_tick(rounds, 1500) == 2  # official_end_tick None → 用 end_tick 兜底
    assert _round_of_tick(rounds, 2500) is None
