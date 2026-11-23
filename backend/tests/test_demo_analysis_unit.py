"""四维分析引擎纯函数单测（合成 polars 帧，不依赖真实 demo）。"""
from types import SimpleNamespace

import polars as pl

from app.services.demo_analysis import (
    _round_of_tick,
    analyze_deaths,
    analyze_duels,
    analyze_utility_players,
    compute_server_ratings,
    analyze_duels_damage,
    analyze_economy,
    analyze_utility,
    collect_utility_spots,
    distance_bucket,
    weapon_class,
)

DEMO_PATH = None  # 运行时惰性解析（部分用例需要真实 demo）


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
    # 完美平台皮肤后缀 _txzNN（实测 ak47_txz02 全进 other 的根因）
    assert weapon_class("ak47_txz02") == "rifle"
    assert weapon_class("awp_txz02") == "sniper"
    assert weapon_class("usp_silencer_txz02") == "pistol"
    assert weapon_class("mac10_txz02") == "smg"
    assert weapon_class("nova_txz02") == "shotgun"
    assert weapon_class("mag7") == "shotgun"


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


def test_utility_players_full_pipeline():
    """
    Given 真实 demo（客户端缓存解压产物）
    When  analyze_utility_players
    Then  10 人各有烟/闪/火/雷计数、花费估算、致盲敌我分布合理
    """
    import pytest

    from pathlib import Path

    demo = Path(__file__).resolve().parents[2] / "data" / "demos" / "9215177922805569036_0.dem"
    if not demo.exists():
        pytest.skip("本地无真实 demo")

    from awpy import Demo

    d = Demo(path=str(demo))
    players = analyze_utility_players(d, d.grenades, d.damages, d.kills)
    assert len(players) == 10
    assert sum(p.spend for p in players) > 10000
    me = next((p for p in players if p.player_id == "76561198339750836"), None)
    assert me is not None
    assert me.smoke + me.flash + me.molotov + me.he > 0
    assert me.flash_enemies + me.flash_teammates > 0


def test_compute_server_ratings_shape():
    """
    Given v1 全场 5 人合成数据
    When  compute_server_ratings
    Then  每人六维 0-100、场均值 6 维
    """
    players = [
        {"playerId": str(1000 + i), "kill": 10 + i, "death": 15 - i, "dmgHealth": 800 + i * 50,
         "headShotRatio": 0.2 + i * 0.03, "fireCount": 50, "hitCount": 10 + i,
         "tradeFragCount": i, "entryKill": i % 3, "entryDeath": (3 - i) % 3,
         "vs1": 1, "vs2": 0, "vs3": 0, "vs4": 0, "vs5": 0}
        for i in range(5)
    ]
    ratings = compute_server_ratings(players, [])
    assert len(ratings.players) == 5
    for pid, dims in ratings.players.items():
        for dim, v in dims.items():
            assert 0 <= v <= 100, (pid, dim, v)
    assert len(ratings.averages) == 6
def _item_events_frame(rows):
    cols = ["tick", "action", "steamid", "item", "cost"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


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


def test_analyze_deaths_world_kill_no_coords():
    """
    Given 炸弹/世界伤害击杀（attacker 无名字无坐标，weapon=planted_c4）
    When  analyze_deaths
    Then  不崩溃：distance_m=None、不入距离桶、劣势枪位仅按穿烟/被闪近似（False）
    """
    sid = 111
    kills = _kills_frame([
        {"attacker_steamid": None, "victim_steamid": sid, "attacker_side": None, "weapon": "planted_c4",
         "tick": 100, "attacker_x": None, "attacker_y": None, "attacker_z": None,
         "victim_x": 100, "victim_y": 50, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
        {"attacker_steamid": 222, "victim_steamid": sid, "attacker_side": "t", "weapon": "ak47", "tick": 300,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 200, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
    ])
    dim, events = analyze_deaths(kills, _rounds_frame(), sid)
    assert len(events) == 2
    world = events[0]
    assert world.distance_m is None and world.killer_weapon == "planted_c4"
    assert world.disadvantaged_position is False
    assert all(b.distance for b in dim.buckets)  # 距离桶只含可定位死亡
    assert [b.distance for b in dim.buckets] == ["0-5m"]


def test_analyze_duels_skips_unlocatable_kills():
    """
    Given 对枪事件含无坐标行（炸弹击杀）
    When  analyze_duels
    Then  该行不进对枪矩阵，其余正常聚合
    """
    sid = 111
    kills = _kills_frame([
        {"attacker_steamid": None, "victim_steamid": sid, "attacker_side": None, "weapon": "planted_c4",
         "tick": 100, "attacker_x": None, "attacker_y": None, "attacker_z": None,
         "victim_x": 100, "victim_y": 50, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
        {"attacker_steamid": sid, "victim_steamid": 222, "attacker_side": "ct", "weapon": "m4a1", "tick": 200,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 200, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
    ])
    dim = analyze_duels(kills, sid)
    assert [(b.distance, b.weapon) for b in dim.by_weapon_distance] == [("0-5m", "rifle")]


def test_analyze_utility_usage_bought_vs_thrown():
    """
    Given user 购买 smokegrenade×3 / flashbang×2（item_events purchase），实际投掷 smoke×2 / flash×1 / he×1（捡漏）
    When  analyze_utility
    Then  usage 按 purchase item→grenade type 映射：smoke {bought:3, thrown:2, waste_rate:0.333}、
          flashbang {bought:2, thrown:1, waste_rate:0.5}、he {bought:0, thrown:1, waste_rate:0.0}（捡漏不亏）
    """
    sid = 111
    other = 999
    demo = SimpleNamespace(
        item_events=_item_events_frame([
            {"tick": 10, "action": "purchase", "steamid": sid, "item": "smokegrenade", "cost": 300},
            {"tick": 11, "action": "purchase", "steamid": sid, "item": "smokegrenade", "cost": 300},
            {"tick": 12, "action": "purchase", "steamid": sid, "item": "smokegrenade", "cost": 300},
            {"tick": 13, "action": "purchase", "steamid": sid, "item": "flashbang", "cost": 200},
            {"tick": 14, "action": "purchase", "steamid": sid, "item": "flashbang", "cost": 200},
            {"tick": 15, "action": "purchase", "steamid": other, "item": "smokegrenade", "cost": 300},
            {"tick": 16, "action": "purchase", "steamid": sid, "item": "ak47", "cost": 2700},  # 枪械不入 usage
        ]),
        blinds=_blinds_frame([]),
    )
    grenades = _grenades_frame([
        {"entity_id": 1, "thrower_steamid": sid, "type": "smoke", "tick": 100, "x": 0, "y": 0, "z": 0},
        {"entity_id": 2, "thrower_steamid": sid, "type": "smoke", "tick": 200, "x": 0, "y": 0, "z": 0},
        {"entity_id": 3, "thrower_steamid": sid, "type": "flashbang", "tick": 300, "x": 0, "y": 0, "z": 0},
        {"entity_id": 4, "thrower_steamid": sid, "type": "he", "tick": 400, "x": 0, "y": 0, "z": 0},
        # 他人投掷不计入
        {"entity_id": 5, "thrower_steamid": other, "type": "smoke", "tick": 500, "x": 0, "y": 0, "z": 0},
    ])
    dim = analyze_utility(demo, grenades, sid)
    usage = {u.grenade_type: u for u in dim.usage}
    assert usage["smoke"].bought == 3 and usage["smoke"].thrown == 2
    assert usage["smoke"].waste_rate == 0.333
    assert usage["flashbang"].bought == 2 and usage["flashbang"].thrown == 1
    assert usage["flashbang"].waste_rate == 0.5
    assert usage["he"].bought == 0 and usage["he"].thrown == 1
    assert usage["he"].waste_rate == 0.0
    assert "rifle" not in {u.grenade_type for u in dim.usage}


def test_schema_version_bumped_to_1_1():
    """Given schema 迭代（blinds 拆分）When 导入 Then SCHEMA_VERSION=1.1 且 FourDimAnalysis 默认携带。"""
    from app.schemas.analysis import SCHEMA_VERSION, FourDimAnalysis

    assert SCHEMA_VERSION == "1.1"
    assert FourDimAnalysis(match_id="m").schema_version == "1.1"


def test_analyze_economy_win_pattern():
    """
    Given user(ct) 5 回合经济：eco 胜1负1、full 胜2负1
    When  analyze_economy
    Then  eco_win_rate=0.5（抗压能力）、full_buy_lose_rate=0.333（资源转化），
          effective_buy_ratio 仍 None（无总资金列）
    """
    sid = 111
    rounds = pl.DataFrame([
        {"round_num": 1, "start_tick": 0, "official_end_tick": 1000, "winner_side": "t"},
        {"round_num": 2, "start_tick": 1001, "official_end_tick": 2000, "winner_side": "ct"},
        {"round_num": 3, "start_tick": 2001, "official_end_tick": 3000, "winner_side": "t"},
        {"round_num": 4, "start_tick": 3001, "official_end_tick": 4000, "winner_side": "ct"},
        {"round_num": 5, "start_tick": 4001, "official_end_tick": 5000, "winner_side": "ct"},
    ])
    demo = SimpleNamespace(round_economy=pl.DataFrame([
        {"round_num": 1, "side": "ct", "equipment_value": 1200, "buy_type": "eco", "n_players": 5},
        {"round_num": 2, "side": "ct", "equipment_value": 1800, "buy_type": "eco", "n_players": 5},
        {"round_num": 3, "side": "ct", "equipment_value": 42000, "buy_type": "full", "n_players": 5},
        {"round_num": 4, "side": "ct", "equipment_value": 45000, "buy_type": "full", "n_players": 5},
        {"round_num": 5, "side": "ct", "equipment_value": 41000, "buy_type": "full", "n_players": 5},
        {"round_num": 1, "side": "t", "equipment_value": 40000, "buy_type": "full", "n_players": 5},
    ]))
    kills = _kills_frame([])
    dim = analyze_economy(demo, kills, rounds, sid, "ct")
    assert dim.eco_win_rate == 0.5
    assert dim.full_buy_lose_rate == 0.333
    assert dim.effective_buy_ratio is None
    assert len(dim.buy_decisions) == 5  # 只统计 user 侧


def _damages_frame(rows):
    cols = ["attacker_steamid", "victim_steamid", "weapon", "tick"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def test_analyze_duels_damage_first_strike_and_mirror():
    """
    Given 三段交火（击杀事件切窗）：
      W1 镜像 m4a1：user 先手 → user 击杀（胜）
      W2 非镜像 ak47vs awp：对方先手 → 对方击杀（负）
      W3 镜像 m4a1：user 先手 → 无击杀结算（不计分母）
    When  analyze_duels_damage
    Then  first_strike_win_rate=1.0（仅 W1 计）、mirror_win_rate=1.0（仅 W1 计，W3 无结局剔除）
    """
    sid, foe = 111, 222
    damages = _damages_frame([
        # W1: user 先手，双方互伤，user 击杀
        {"attacker_steamid": sid, "victim_steamid": foe, "weapon": "m4a1", "tick": 100},
        {"attacker_steamid": foe, "victim_steamid": sid, "weapon": "m4a1", "tick": 110},
        # W2: 对方先手，user 换血，对方击杀
        {"attacker_steamid": foe, "victim_steamid": sid, "weapon": "awp", "tick": 200},
        {"attacker_steamid": sid, "victim_steamid": foe, "weapon": "ak47", "tick": 210},
        # W3: user 先手互伤，无击杀（贴脸脱战）
        {"attacker_steamid": sid, "victim_steamid": foe, "weapon": "m4a1", "tick": 300},
        {"attacker_steamid": foe, "victim_steamid": sid, "weapon": "m4a1", "tick": 310},
    ])
    kills = _kills_frame([
        {"attacker_steamid": sid, "victim_steamid": foe, "attacker_side": "ct", "weapon": "m4a1", "tick": 120,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 100, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
        {"attacker_steamid": foe, "victim_steamid": sid, "attacker_side": "t", "weapon": "awp", "tick": 220,
         "attacker_x": 0, "attacker_y": 0, "attacker_z": 0, "victim_x": 0, "victim_y": 0, "victim_z": 0,
         "assister_steamid": None, "victim_traded": False, "thrusmoke": False, "attackerblind": False},
    ])
    fs, mirror = analyze_duels_damage(damages, kills, sid)
    assert fs == 1.0
    assert mirror == 1.0


def test_analyze_duels_damage_empty():
    """Given 无伤害事件 When analyze_duels_damage Then 双指标 None（不臆造 0）。"""
    fs, mirror = analyze_duels_damage(_damages_frame([]), _kills_frame([]), 111)
    assert fs is None and mirror is None


def _spots_frame(rows, cols):
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def test_collect_utility_spots_filters_by_side():
    """
    Given user(ct) 2 烟 1 火 + 对方 1 烟，blinds 含 user 闪敌/被闪各 1
    When  collect_utility_spots
    Then  仅保留 user 侧烟/火（kind 正确、坐标透传），blinds 输出被闪者位置（我闪的+我被闪的）
    """
    sid = 111
    demo = SimpleNamespace(
        smokes=_spots_frame([
            {"start_tick": 100, "end_tick": 1800, "thrower_steamid": sid, "thrower_side": "ct", "x": 100.0, "y": 200.0, "z": 0},
            {"start_tick": 200, "end_tick": 1900, "thrower_steamid": 999, "thrower_side": "t", "x": 0.0, "y": 0.0, "z": 0},
            {"start_tick": 300, "end_tick": 2000, "thrower_steamid": 555, "thrower_side": "ct", "x": 300.0, "y": 400.0, "z": 0},
        ], ["start_tick", "end_tick", "thrower_steamid", "thrower_side", "x", "y", "z"]),
        fires=_spots_frame([
            {"start_tick": 400, "end_tick": 700, "thrower_steamid": sid, "thrower_side": "ct", "type": "molotov", "x": 500.0, "y": 600.0, "z": 0},
        ], ["start_tick", "end_tick", "thrower_steamid", "thrower_side", "type", "x", "y", "z"]),
        blinds=_spots_frame([
            {"attacker_steamid": sid, "victim_steamid": 222, "attacker_side": "ct", "victim_side": "t", "duration": 2.0, "victim_x": 700.0, "victim_y": 800.0},
            {"attacker_steamid": 222, "victim_steamid": sid, "attacker_side": "t", "victim_side": "ct", "duration": 1.0, "victim_x": 900.0, "victim_y": 1000.0},
        ], ["attacker_steamid", "victim_steamid", "attacker_side", "victim_side", "duration", "victim_x", "victim_y"]),
    )
    spots = collect_utility_spots(demo, sid, "ct")
    smokes = [s for s in spots if s.kind == "smoke"]
    fires = [s for s in spots if s.kind == "fire"]
    blinds = [s for s in spots if s.kind == "blind"]
    assert len(smokes) == 2 and {s.x for s in smokes} == {100.0, 300.0}
    assert len(fires) == 1 and fires[0].x == 500.0
    assert len(blinds) == 2 and {b.y for b in blinds} == {800.0, 1000.0}
