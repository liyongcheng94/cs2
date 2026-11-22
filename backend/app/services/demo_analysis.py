"""四维 demo 分析引擎（选型：awpy 3.3.0 统一解析；1.1 起致盲走 blinds 数据集，不再依赖 demoparser2）。

口径约定（评审结论，详见 docs/spike-demo-parsers.md）：
- 距离 = kills 帧 xyz 欧氏 × 0.01905（1 unit ≈ 1.905cm）→ 米，分桶 <5m / 5-15m / 15m+。
- 对枪矩阵（首版）：以击杀事件为对枪结算（user 击杀=胜 / 被杀=负），按 (距离桶, 武器类) 聚合；
  先手/镜像维度留 null（damages 交火对二期）。
- 劣势枪位（近似）：无队友支援（无同队 assister）且 (穿烟/被闪/15m+ 大狙) 之一。
- 经济：round_economy 的 buy_type 分布；有效购买比例留 null（无总资金列，二期）。
- 首杀转化率：user 队伍拿下回合首杀的回合中，最终该回合获胜的比例。
- 道具（1.1）：blinds 数据集敌友拆分（敌方累计/队友失误/自闪排除）；闪光浪费率 = 1 - 有效闪/闪光投掷数；
  blind_median_s 取敌方致盲时长真中位数。
"""
from __future__ import annotations

import statistics
import time
import tracemalloc

from loguru import logger
from polars import col

from ..schemas.analysis import (
    AnalysisMeta,
    BuyDecision,
    DeathDim,
    DeathEvent,
    DuelBucket,
    DuelDim,
    EconomyDim,
    FourDimAnalysis,
    SCHEMA_VERSION,
    ThrowEvent,
    UtilityDim,
)

UNIT_TO_M = 0.01905

WEAPON_CLASSES = {
    "awp": "sniper", "ssg08": "sniper", "scar20": "sniper",
    "ak47": "rifle", "m4a1": "rifle", "m4a1_silencer": "rifle", "m4a4": "rifle",
    "galil": "rifle", "famas": "rifle", "sg556": "rifle", "aug": "rifle",
    "glock": "pistol", "usp_silencer": "pistol", "deagle": "pistol", "p250": "pistol",
    "tec9": "pistol", "fiveseven": "pistol", "cz75a": "pistol", "dual_berettas": "pistol",
    "mac10": "smg", "mp9": "smg", "mp7": "smg", "ump45": "smg", "p90": "smg", "bizon": "smg",
}
AWP_LIKE = {"awp", "ssg08", "scar20"}


def weapon_class(weapon: str | None) -> str:
    return WEAPON_CLASSES.get((weapon or "").lower(), "other")


def distance_bucket(dist_m: float) -> str:
    if dist_m < 5:
        return "0-5m"
    if dist_m < 15:
        return "5-15m"
    return "15m+"


def _xyz_dist(ax, ay, az, vx, vy, vz) -> float | None:
    """欧氏距离（米）；任一坐标缺失（炸弹/世界击杀等）返回 None。"""
    if None in (ax, ay, az, vx, vy, vz):
        return None
    return ((ax - vx) ** 2 + (ay - vy) ** 2 + (az - vz) ** 2) ** 0.5 * UNIT_TO_M


def _round_of_tick(rounds, tick: int) -> int | None:
    for r in rounds.iter_rows(named=True):
        if r["start_tick"] <= tick <= r["official_end_tick"]:
            return int(r["round_num"])
    return None


def analyze_deaths(kills, rounds, steam_id: int):
    """死亡还原：user 每次死亡的事件还原 + 距离分桶 + 劣势枪位近似。"""
    events: list[DeathEvent] = []
    my = kills.filter(col("victim_steamid") == steam_id)
    if my.height == 0:
        return DeathDim(), []
    rounds_list = rounds.to_dicts()
    first_kill_tick: dict[int, int] = {}
    for r in kills.to_dicts():
        rn = _round_of_tick(rounds, int(r["tick"]))
        if rn is not None and (rn not in first_kill_tick or int(r["tick"]) < first_kill_tick[rn]):
            first_kill_tick[rn] = int(r["tick"])

    for r in my.to_dicts():
        dist_m = _xyz_dist(r.get("attacker_x"), r.get("attacker_y"), r.get("attacker_z"),
                           r.get("victim_x"), r.get("victim_y"), r.get("victim_z"))
        rn = _round_of_tick(rounds, int(r["tick"]))
        no_support = r.get("assister_steamid") is None and not bool(r.get("victim_traded"))
        disadvantaged = bool(no_support) and (
            bool(r.get("thrusmoke")) or bool(r.get("attackerblind"))
            or (r.get("weapon") in AWP_LIKE and dist_m is not None and dist_m > 15)
        )
        events.append(DeathEvent(
            round_no=rn,
            tick=int(r["tick"]),
            killer_weapon=r.get("weapon"),
            distance_m=round(dist_m, 1) if dist_m is not None else None,
            first_duel=(first_kill_tick.get(rn) == int(r["tick"])),
            teammate_support=not no_support,
            disadvantaged_position=bool(disadvantaged),
            victim_x=r.get("victim_x"), victim_y=r.get("victim_y"),
            killer_x=r.get("attacker_x"), killer_y=r.get("attacker_y"),
        ))
    buckets: dict[str, dict] = {}
    for e in events:
        if e.distance_m is None:  # 炸弹/世界击杀无坐标，不入距离桶
            continue
        b = distance_bucket(e.distance_m)
        buckets.setdefault(b, {"deaths": 0})
        buckets[b]["deaths"] += 1
    disadvantaged_rate = (
        sum(1 for e in events if e.disadvantaged_position) / len(events) if events else None
    )
    dim = DeathDim(
        events=events,
        buckets=[DuelBucket(distance=k, weapon="all", deaths=v["deaths"]) for k, v in sorted(buckets.items())],
        disadvantaged_rate=round(disadvantaged_rate, 3) if disadvantaged_rate is not None else None,
    )
    return dim, events


def analyze_duels(kills, steam_id: int) -> DuelDim:
    """对枪矩阵（首版击杀口径）：user 参与 (attacker 或 victim) 的击杀按 (距离桶, 武器类) 聚合。"""
    involved = kills.filter((col("attacker_steamid") == steam_id) | (col("victim_steamid") == steam_id))
    agg: dict[tuple[str, str], dict] = {}
    for r in involved.to_dicts():
        dist_m = _xyz_dist(r.get("attacker_x"), r.get("attacker_y"), r.get("attacker_z"),
                           r.get("victim_x"), r.get("victim_y"), r.get("victim_z"))
        if dist_m is None:  # 炸弹/世界击杀不可定位，不入对枪矩阵
            continue
        wclass = weapon_class(r.get("weapon"))
        bucket = distance_bucket(dist_m)
        key = (bucket, wclass)
        cell = agg.setdefault(key, {"kills": 0, "deaths": 0})
        if r.get("attacker_steamid") == steam_id:
            cell["kills"] += 1
        else:
            cell["deaths"] += 1
    by_wd = [
        DuelBucket(distance=b, weapon=w, kills=v["kills"], deaths=v["deaths"],
                   win_rate=round(v["kills"] / (v["kills"] + v["deaths"]), 3) if (v["kills"] + v["deaths"]) else None)
        for (b, w), v in sorted(agg.items())
    ]
    return DuelDim(by_weapon_distance=by_wd)


def analyze_economy(demo, kills, rounds, steam_id: int, user_side: str | None) -> EconomyDim:
    """经济：回合 buy_type 分布 + 首杀转化率（首版：有效购买比例留 null）。"""
    economy = demo.round_economy
    buys: list[BuyDecision] = []
    if user_side:
        mine = economy.filter(col("side") == user_side).to_dicts()
        for r in mine:
            buys.append(BuyDecision(
                round_no=int(r["round_num"]),
                buy=r.get("buy_type"),
                equip_value=int(r.get("equipment_value") or 0),
                effective=None,  # 有效购买口径二期（需总资金列）
            ))
    # 首杀转化：回合首个击杀的 attacker 阵营 == user_side → 该回合 winner_side 是否 == user_side
    first_kills: dict[int, tuple[int, str]] = {}
    for r in kills.to_dicts():
        rn = _round_of_tick(rounds, int(r["tick"]))
        if rn is not None and (rn not in first_kills or int(r["tick"]) < first_kills[rn][0]):
            first_kills[rn] = (int(r["tick"]), r.get("attacker_side"))
    rounds_list = rounds.to_dicts()
    win_map = {int(r["round_num"]): r.get("winner_side") for r in rounds_list}
    first_by_user = [rn for rn, (_, side) in first_kills.items() if user_side and side == user_side]
    conversion = (
        sum(1 for rn in first_by_user if win_map.get(rn) == user_side) / len(first_by_user)
        if first_by_user else None
    )
    return EconomyDim(
        buy_decisions=buys,
        effective_buy_ratio=None,
        first_kill_conversion=round(conversion, 3) if conversion is not None else None,
    )


def analyze_utility(demo, grenades, steam_id: int) -> UtilityDim:
    """道具：投掷清单（按 entity_id 去重——grenades 帧是逐 tick 轨迹，非事件）+ awpy blinds 敌友拆分 + 闪光浪费率。

    1.1 口径：blinds 数据集 attacker=投掷者、victim=被致盲者。
    - victim_side != attacker_side → 敌方致盲（有效），累计 enemy_blind_s；
    - victim_side == attacker_side 且 victim != attacker → 队友致盲（失误），累计 team_blind_s；
    - 自闪（victim == attacker）不计入任一侧；duration <= 0.1s 视为擦过不计入。
    - blind_median_s 取敌方致盲时长的真中位数（偶数个取中间两数均值）。
    """
    my = (
        grenades.filter(col("thrower_steamid") == steam_id)
        .unique(subset=["entity_id"])
        .to_dicts()
    )
    throws = [ThrowEvent(round_no=None, grenade_type=r.get("type"), effective=None) for r in my]

    enemy_durs: list[float] = []
    enemy_blind_s = 0.0
    team_blind_s = 0.0
    blinds = getattr(demo, "blinds", None)
    if blinds is not None and blinds.height:
        for r in blinds.filter(col("attacker_steamid") == steam_id).to_dicts():
            dur = float(r.get("duration") or 0)
            if dur <= 0.1 or r.get("victim_steamid") == steam_id:
                continue
            if r.get("victim_side") == r.get("attacker_side"):
                team_blind_s += dur
            else:
                enemy_blind_s += dur
                enemy_durs.append(dur)

    flash_thrown = sum(1 for t in throws if (t.grenade_type or "").lower() in ("flashbang", "flash"))
    flash_effective = len([d for d in enemy_durs if d > 0.5]) if flash_thrown else 0
    blind_median = statistics.median(enemy_durs) if enemy_durs else None
    waste_rate = (
        round(max(0, flash_thrown - flash_effective) / flash_thrown, 3)
        if flash_thrown else None
    )
    return UtilityDim(
        throws=throws,
        blind_median_s=round(blind_median, 2) if blind_median is not None else None,
        waste_rate=waste_rate,
        enemy_blind_s=round(enemy_blind_s, 2),
        team_blind_s=round(team_blind_s, 2),
    )


def run_analysis(dem_path, match_id: str, steam_id: str) -> tuple[FourDimAnalysis, dict]:
    """主入口（demo_analyze 编排调用）：awpy 解析 → 四维 → schema JSON。线程池中执行。"""
    import tracemalloc as _tm

    from awpy import Demo

    _tm.start()
    t0 = time.perf_counter()
    try:
        demo = Demo(path=str(dem_path))
        kills, rounds = demo.kills, demo.rounds
        grenades, economy = demo.grenades, demo.round_economy
        sid = int(steam_id)

        my_rows = kills.filter((col("attacker_steamid") == sid) | (col("victim_steamid") == sid))
        user_side = my_rows.select("attacker_side").drop_nulls().row(0, named=True)["attacker_side"] if my_rows.height else None

        deaths_dim, _events = analyze_deaths(kills, rounds, sid)
        duels_dim = analyze_duels(kills, sid)
        economy_dim = analyze_economy(demo, kills, rounds, sid, user_side)
        utility_dim = analyze_utility(demo, grenades, sid)

        analysis = FourDimAnalysis(
            match_id=match_id,
            deaths=deaths_dim,
            economy=economy_dim,
            utility=utility_dim,
            duels=duels_dim,
            meta=AnalysisMeta(parser="awpy 3.3.0"),
        )
    finally:
        cost = time.perf_counter() - t0
        _, peak = _tm.get_traced_memory()
        _tm.stop()
    meta = {"parser": "awpy 3.3.0", "cost_s": round(cost, 1), "peak_mem_mb": round(peak / 1e6)}
    logger.info(f"[demo解析] matchId={match_id} 耗时={meta['cost_s']}s 峰值内存={meta['peak_mem_mb']}MB")
    return analysis, meta
