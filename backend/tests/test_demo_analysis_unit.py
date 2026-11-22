"""四维分析引擎纯函数单测（合成 polars 帧，不依赖真实 demo）。"""
from types import SimpleNamespace

import polars as pl

from app.services.demo_analysis import (
    _round_of_tick,
    analyze_deaths,
    analyze_duels,
    analyze_utility,
    distance_bucket,
    weapon_class,
)


def _kills_frame(rows):
    cols = ["attacker_steamid", "victim_steamid", "attacker_side", "weapon", "tick",
            "attacker_x", "attacker_y", "attacker_z", "victim_x", "victim_y", "victim_z",
            "assister_steamid", "victim_traded", "thrusmoke", "attackerblind"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def _rounds_frame():
    return pl.DataFrame([
        {"round_num": 1, "start_tick": 0, "official_end_tick": 1000, "winner_side": "ct"},
        {"round_num": 2, "start_tick": 1001, "official_end_tick": 2000, "winner_side": "t"},
    ])


def test_weapon_class_mapping():
    """
    Given CS2 武器名
    When  weapon_class
    Then  归入 sniper/rifle/pistol/smg/other
    """
    assert weapon_class("AWP") == "sniper"
    assert weapon_class("ak47") == "rifle"
    assert weapon_class("glock") == "pistol"
    assert weapon_class("mac10") == "smg"
    assert weapon_class("knife_t") == "other"
    assert weapon_class(None) == "other"


def test_distance_bucket():
    """Given 距离米数 When 分桶 Then <5/5-15/15+ 三桶。"""
    assert distance_bucket(3) == "0-5m"
    assert distance_bucket(5.0) == "5-15m"
    assert distance_bucket(14.9) == "5-15m"
    assert distance_bucket(15) == "15m+"


def test_round_of_tick():
    """Given tick 落在回合区间 When _round_of_tick Then 返回对应回合号。"""
    rounds = _rounds_frame()
    assert _round_of_tick(rounds, 500) == 1
    assert _round_of_tick(rounds, 1500) == 2
    assert _round_of_tick(rounds, 3000) is None


def test_analyze_duels_buckets_and_winrate():
    """
    Given user 三次击杀（近/中/远）与一次被杀
    When  analyze_duels
    Then  按距离桶×武器类聚合胜率正确
    """
    sid = 111
    enemy = 222
    kills = _kills_frame([
        # 近战 AK 击杀（~4m）
        {"attacker_steamid": sid, "victim_steamid": enemy, "attacker_side": "ct", "weapon": "m4a1", "tick": 100,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 200, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
        # 近战 AWP 被杀（~4m）
        {"attacker_steamid": enemy, "victim_steamid": sid, "attacker_side": "t", "weapon": "awp", "tick": 200,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 200, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
        # 远距离 AWP 击杀（~30m）
        {"attacker_steamid": sid, "victim_steamid": enemy, "attacker_side": "ct", "weapon": "awp", "tick": 300,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 1600, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
    ])
    dim = analyze_duels(kills, sid)
    by_key = {(b.distance, b.weapon): b for b in dim.by_weapon_distance}
    # 200 units × 0.01905 ≈ 3.81m → 0-5m
    near_rifle = by_key[("0-5m", "rifle")]
    assert near_rifle.kills == 1 and near_rifle.deaths == 0
    # AWP 近战被杀 → 0-5m sniper 0/1
    near_sniper = by_key[("0-5m", "sniper")]
    assert near_sniper.deaths == 1 and near_sniper.win_rate == 0.0
    # 1600 units ≈ 30.5m → 15m+ sniper 1/0
    far = by_key[("15m+", "sniper")]
    assert far.kills == 1 and far.win_rate == 1.0


def test_analyze_deaths_disadvantaged_approximation():
    """
    Given 被大狙远距击杀且无支援无补枪
    When  analyze_deaths
    Then  disadvantaged_position=True 且劣势率 = 1/1
    """
    sid = 111
    enemy = 222
    kills = _kills_frame([
        {"attacker_steamid": enemy, "victim_steamid": sid, "attacker_side": "t", "weapon": "awp", "tick": 100,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 1600, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
    ])
    rounds = _rounds_frame()
    dim, events = analyze_deaths(kills, rounds, sid)
    assert len(events) == 1
    assert events[0].disadvantaged_position is True
    assert events[0].distance_m is not None and events[0].distance_m > 15
    assert dim.disadvantaged_rate == 1.0


def _blinds_frame(rows):
    cols = ["attacker_steamid", "victim_steamid", "attacker_side", "victim_side", "duration"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def _grenades_frame(rows):
    cols = ["entity_id", "thrower_steamid", "thrower_side", "type", "tick", "x", "y", "z"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def test_analyze_utility_blind_split_enemy_team():
    """
    Given user 造成 4 次致盲：敌方 2 次（2.5s / 0.8s）、队友 1 次（1.2s）、自己 1 次（0.6s）
    When  analyze_utility（awpy blinds 口径）
    Then  enemy_blind_s=3.3、team_blind_s=1.2，自闪不计入任一侧，
          blind_median_s=敌方两次的中位数 1.65，闪光盘口径=有效闪 1/投掷 1 → waste 0.0
    """
    sid = 111
    mate = 333
    demo = SimpleNamespace(blinds=_blinds_frame([
        {"attacker_steamid": sid, "victim_steamid": 222, "attacker_side": "ct", "victim_side": "t", "duration": 2.5},
        {"attacker_steamid": sid, "victim_steamid": 444, "attacker_side": "ct", "victim_side": "t", "duration": 0.8},
        {"attacker_steamid": sid, "victim_steamid": mate, "attacker_side": "ct", "victim_side": "ct", "duration": 1.2},
        {"attacker_steamid": sid, "victim_steamid": sid, "attacker_side": "ct", "victim_side": "ct", "duration": 0.6},
    ]))
    grenades = _grenades_frame([
        {"entity_id": 1, "thrower_steamid": sid, "thrower_side": "ct", "type": "flashbang", "tick": 100,
         "x": 0, "y": 0, "z": 0},
    ])
    dim = analyze_utility(demo, grenades, sid)
    assert dim.enemy_blind_s == 3.3
    assert dim.team_blind_s == 1.2
    assert dim.blind_median_s == 1.65
    assert dim.waste_rate == 0.0  # 1 闪 1 有效（2.5s>0.5s）
    assert [t.grenade_type for t in dim.throws] == ["flashbang"]


def test_analyze_utility_tiny_blinds_ignored_and_empty():
    """
    Given 致盲事件仅 1 次队友 0.05s（低于 0.1s 阈值）且无投掷记录
    When  analyze_utility
    Then  enemy_blind_s=0.0、team_blind_s=0.0，blind_median_s/waste_rate 均 None（无可统计样本）
    """
    sid = 111
    demo = SimpleNamespace(blinds=_blinds_frame([
        {"attacker_steamid": sid, "victim_steamid": 333, "attacker_side": "ct", "victim_side": "ct", "duration": 0.05},
    ]))
    grenades = _grenades_frame([])
    dim = analyze_utility(demo, grenades, sid)
    assert dim.enemy_blind_s == 0.0
    assert dim.team_blind_s == 0.0
    assert dim.blind_median_s is None
    assert dim.waste_rate is None


def test_schema_version_bumped_to_1_1():
    """Given schema 迭代（blinds 拆分）When 导入 Then SCHEMA_VERSION=1.1 且 FourDimAnalysis 默认携带。"""
    from app.schemas.analysis import SCHEMA_VERSION, FourDimAnalysis

    assert SCHEMA_VERSION == "1.1"
    assert FourDimAnalysis(match_id="m").schema_version == "1.1"
