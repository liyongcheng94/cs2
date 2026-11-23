"""全场道具统计与六维评分契约（并行开发合并保障，测试融合）。"""
from types import SimpleNamespace

import polars as pl

from app.services.demo_analysis import (
    _sid,
    analyze_utility_players,
    compute_server_ratings,
)


def _kills_frame(rows):
    cols = ["attacker_steamid", "attacker_name", "attacker_side", "victim_steamid", "victim_name", "victim_side", "tick"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def _grenades_frame(rows):
    cols = ["entity_id", "thrower_name", "thrower_steamid", "thrower_side", "type", "tick"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def test_sid_normalization():
    """
    Given 整数/字符串/浮点（17 位丢精度）steamid
    When  _sid
    Then  整数与字符串原样保精度；浮点尽力转换；非数字原样返回
    """
    assert _sid(76561199322885056) == "76561199322885056"
    assert _sid("76561199322885056") == "76561199322885056"
    assert _sid(76561199322885056.0).startswith("76561199")  # 浮点尽力（允许尾数漂移）
    assert _sid("abc") == "abc"


def test_analyze_utility_players_counts_and_prices(monkeypatch):
    """
    Given 2 名玩家投掷烟/闪/火/诱饵 + 燃烧伤害 + player_blind 桩（敌/自各 1 次）
    When  analyze_utility_players
    Then  entity 去重计数、spend 按价目累计（decoy 也计价）、敌/自闪区分、枪伤不计入 util_dmg
    """
    sid_a, sid_b = "76561199000000001", "76561199000000002"
    kills = _kills_frame([
        {"attacker_steamid": sid_a, "attacker_name": "甲", "attacker_side": "ct",
         "victim_steamid": sid_b, "victim_name": "乙", "victim_side": "t", "tick": 100},
    ])
    grenades = _grenades_frame([
        {"entity_id": 1, "thrower_name": "甲", "thrower_steamid": 111.0, "thrower_side": "ct", "type": "smoke", "tick": 10},
        {"entity_id": 1, "thrower_name": "甲", "thrower_steamid": 111.0, "thrower_side": "ct", "type": "smoke", "tick": 11},
        {"entity_id": 2, "thrower_name": "甲", "thrower_steamid": 111.0, "thrower_side": "ct", "type": "flash", "tick": 20},
        {"entity_id": 3, "thrower_name": "乙", "thrower_steamid": 222.0, "thrower_side": "t", "type": "molotov", "tick": 30},
        {"entity_id": 4, "thrower_name": "乙", "thrower_steamid": 222.0, "thrower_side": "t", "type": "decoy", "tick": 40},
    ])
    hurts = pl.DataFrame([
        {"attacker_steamid": sid_a, "weapon": "inferno", "dmg_health": 23},
        {"attacker_steamid": sid_a, "weapon": "ak47_txz1", "dmg_health": 100},  # 枪伤不计
    ])

    class StubParser:
        def __init__(self, path):
            pass

        def parse_event(self, name, other=None):
            import pandas as pd

            return pd.DataFrame([
                {"attacker_steamid": sid_a, "user_steamid": sid_b, "blind_duration": 2.0},  # 致盲敌方
                {"attacker_steamid": sid_a, "user_steamid": sid_a, "blind_duration": 1.0},  # 自闪→队友口径
                {"attacker_steamid": sid_a, "user_steamid": sid_b, "blind_duration": 0.05},  # 低于阈值不计
            ])

    monkeypatch.setattr("demoparser2.DemoParser", StubParser)

    out = analyze_utility_players(SimpleNamespace(path="stub.dem"), grenades, hurts, kills)
    by = {u.player_id: u for u in out}
    a, b = by[sid_a], by[sid_b]
    assert a.smoke == 1 and a.flash == 1  # entity 去重生效
    assert b.molotov == 1 and b.he == 0
    assert a.flash_enemies == 1 and a.flash_teammates == 1
    assert a.util_dmg == 23
    assert a.spend == 300 + 200  # smoke+flash
    assert b.spend == 400 + 50  # molotov+decoy


def test_compute_server_ratings_normalized():
    """
    Given v1 全场 2 人数据（能力有差异）+ 道具统计
    When  compute_server_ratings
    Then  六维全部落 0-100；优势者 ≥50、劣势者 ≤50；averages 六项齐全
    """
    u1 = SimpleNamespace(player_id="p1", util_dmg=100, flash_enemies=3, spend=1700)
    u2 = SimpleNamespace(player_id="p2", util_dmg=0, flash_enemies=0, spend=0)
    v1 = [
        {"playerId": "p1", "fireCount": 100, "hitCount": 50, "headShotRatio": 0.5, "tradeFragCount": 2,
         "entryKill": 3, "entryDeath": 1, "vs1": 2, "vs2": 1, "vs3": 0, "vs4": 0, "vs5": 0, "kill": 15, "dmgHealth": 1500},
        {"playerId": "p2", "fireCount": 100, "hitCount": 20, "headShotRatio": 0.2, "tradeFragCount": 0,
         "entryKill": 0, "entryDeath": 3, "vs1": 0, "vs2": 0, "vs3": 0, "vs4": 0, "vs5": 0, "kill": 5, "dmgHealth": 600},
    ]
    out = compute_server_ratings(v1, [u1, u2])
    assert all(0 <= d <= 100 for d in out.players["p1"].values())
    assert all(d >= 50 for d in out.players["p1"].values())  # 全维度占优者
    assert all(d <= 50 for d in out.players["p2"].values())
    assert len(out.averages) == 6


def test_compute_server_ratings_single_player_flat():
    """
    Given 仅 1 人数据（无法归一化）
    When  compute_server_ratings
    Then  全维度 50 分（不崩、不臆造差异）
    """
    u = SimpleNamespace(player_id="p1", util_dmg=0, flash_enemies=0, spend=0)
    v1 = [{"playerId": "p1", "fireCount": 10, "hitCount": 5, "headShotRatio": 0.3}]
    out = compute_server_ratings(v1, [u])
    assert all(d == 50.0 for d in out.players["p1"].values())
