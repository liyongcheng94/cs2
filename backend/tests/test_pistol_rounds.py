"""手枪局维度（第 1 & 13 回合，MR12）：阵营归一化 + 胜负判定 + 我方个人数据。

场景：
- 阵营归一化：awpy 内部 terrorist/counter-terrorist、demoparser2 round_end T/CT、
  玩家 team_name TERRORIST/CT 三种写法必须统一（此前 TERRORIST≠T 导致 T 方手枪局全判负）
- 第 1/13 回合识别 + 我方阵营推断（同半场我参与击杀/死亡的 team 众数）
- 个人 K/D 统计 + 分阵营聚合
- 边界：手枪局无我方参与行 → 该回合不计入分阵营聚合（side unknown）
"""

from __future__ import annotations

import polars as pl

from app.services.demo_analysis import analyze_pistol_rounds, normalize_side


def _kills_df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "attacker_steamid": pl.UInt64,
            "victim_steamid": pl.UInt64,
            "attacker_side": pl.String,
            "victim_side": pl.String,
            "total_rounds_played": pl.UInt32,
            "tick": pl.Int64,
        },
    )


def _rounds_df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={"round_num": pl.UInt32, "winner_side": pl.String, "start_tick": pl.Int64, "end_tick": pl.Int64},
    )


ME = 76561198339750836


def _sample_rounds() -> pl.DataFrame:
    return _rounds_df(
        [
            {"round_num": 1, "winner_side": "counter-terrorist", "start_tick": 0, "end_tick": 10000},
            {"round_num": 2, "winner_side": "terrorist", "start_tick": 10000, "end_tick": 20000},
            {"round_num": 13, "winner_side": "terrorist", "start_tick": 60000, "end_tick": 70000},
        ]
    )


def test_normalize_side():
    """Given 三种数据源的阵营写法，When 归一化，Then 统一为 T/CT。"""
    assert normalize_side("terrorist") == "T"
    assert normalize_side("TERRORIST") == "T"
    assert normalize_side("T") == "T"
    assert normalize_side("counter-terrorist") == "CT"
    assert normalize_side("CT") == "CT"
    assert normalize_side(None) is None


def test_pistol_rounds_detection_and_personal_kd():
    """Given 我方 R1 为 T（负）、R13 为 CT（胜），When 解析，Then 两回合胜负与个人 K/D 正确。"""
    kills = _kills_df(
        [
            # R1：我方 T，我 1 杀 1 死，回 合 CT 胜
            {"attacker_steamid": ME, "victim_steamid": 2, "attacker_side": "terrorist", "victim_side": "counter-terrorist", "total_rounds_played": 1, "tick": 3000},
            {"attacker_steamid": 2, "victim_steamid": ME, "attacker_side": "counter-terrorist", "victim_side": "terrorist", "total_rounds_played": 1, "tick": 3000},
            # R2（非手枪局，不统计）
            {"attacker_steamid": ME, "victim_steamid": 3, "attacker_side": "terrorist", "victim_side": "counter-terrorist", "total_rounds_played": 2, "tick": 12000},
            # R13：我方 CT，我 2 杀 0 死，回合 T 胜（我方负）
            {"attacker_steamid": ME, "victim_steamid": 4, "attacker_side": "counter-terrorist", "victim_side": "terrorist", "total_rounds_played": 13, "tick": 68000},
            {"attacker_steamid": ME, "victim_steamid": 5, "attacker_side": "counter-terrorist", "victim_side": "terrorist", "total_rounds_played": 13, "tick": 68000},
            {"attacker_steamid": 4, "victim_steamid": 6, "attacker_side": "terrorist", "victim_side": "counter-terrorist", "total_rounds_played": 13, "tick": 68000},
        ]
    )
    dim = analyze_pistol_rounds(kills, _sample_rounds(), ME)
    assert len(dim.rounds) == 2
    r1, r13 = dim.rounds
    assert (r1.round_no, r1.my_side, r1.won, r1.my_kills, r1.my_deaths) == (1, "T", False, 1, 1)
    assert (r13.round_no, r13.my_side, r13.won, r13.my_kills, r13.my_deaths) == (13, "CT", False, 2, 0)
    assert dim.t_total == 1 and dim.t_won == 0
    assert dim.ct_total == 1 and dim.ct_won == 0
    assert dim.total == 2 and dim.won == 0


def test_side_inferred_from_half_mode():
    """Given 我在某手枪局无击杀无死亡，When 推断阵营，Then 用同半场其余行的众数。"""
    kills = _kills_df(
        [
            # R1 我没有任何参与行；R2-R4 我方 T
            {"attacker_steamid": ME, "victim_steamid": 2, "attacker_side": "terrorist", "victim_side": "counter-terrorist", "total_rounds_played": 2, "tick": 12000},
            {"attacker_steamid": ME, "victim_steamid": 3, "attacker_side": "terrorist", "victim_side": "counter-terrorist", "total_rounds_played": 3, "tick": 15000},
            {"attacker_steamid": 2, "victim_steamid": ME, "attacker_side": "counter-terrorist", "victim_side": "terrorist", "total_rounds_played": 4, "tick": 19000},
        ]
    )
    dim = analyze_pistol_rounds(kills, _sample_rounds(), ME)
    r1 = dim.rounds[0]
    assert r1.my_side == "T"  # 从同半场众数推断
    assert r1.my_kills == 0 and r1.my_deaths == 0
    assert r1.won is False  # R1 winner CT ≠ T


def test_no_participation_whole_half_excluded():
    """Given 我整个上半场 0 参与，When 解析，Then 该手枪局 side=None 不入分阵营聚合。"""
    kills = _kills_df(
        [
            # 只有 R13 我方 CT 的一行（下半场），上半场无任何我的行
            {"attacker_steamid": ME, "victim_steamid": 2, "attacker_side": "counter-terrorist", "victim_side": "terrorist", "total_rounds_played": 13, "tick": 68000},
        ]
    )
    dim = analyze_pistol_rounds(kills, _sample_rounds(), ME)
    r1 = dim.rounds[0]
    assert r1.my_side is None and r1.won is None
    assert dim.t_total == 0 and dim.ct_total == 1  # 只有 R13 入聚合
