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

import re
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
    GrenadeUsage,
    SCHEMA_VERSION,
    ThrowEvent,
    UtilityDim,
    UtilityPlayer,
    ServerRatings,
    UtilitySpot,
)
from .highlight import detect_highlights

UNIT_TO_M = 0.01905
TICK_RATE = 64  # CS2 标准 64 tick（blind 散点 start_tick 复用为致盲时长帧数展示）

WEAPON_CLASSES = {
    "awp": "sniper", "ssg08": "sniper", "scar20": "sniper",
    "ak47": "rifle", "m4a1": "rifle", "m4a1_silencer": "rifle", "m4a4": "rifle",
    "galil": "rifle", "famas": "rifle", "sg556": "rifle", "aug": "rifle",
    "glock": "pistol", "usp_silencer": "pistol", "deagle": "pistol", "p250": "pistol",
    "tec9": "pistol", "fiveseven": "pistol", "cz75a": "pistol", "dual_berettas": "pistol",
    "mac10": "smg", "mp9": "smg", "mp7": "smg", "ump45": "smg", "p90": "smg", "bizon": "smg",
    "nova": "shotgun", "xm1014": "shotgun", "mag7": "shotgun", "sawedoff": "shotgun",
}
AWP_LIKE = {"awp", "ssg08", "scar20"}

# item_events purchase 的 item 名 → grenades.type 投掷类型名（实测映射，incendiary 合火）
PURCHASE_ITEM_TO_GRENADE = {
    "smokegrenade": "smoke",
    "flashbang": "flashbang",
    "hegrenade": "he",
    "molotov": "molotov",
    "incendiary": "molotov",
    "decoy": "decoy",
}


def weapon_class(weapon: str | None) -> str:
    """武器归类；完美平台 demo 的饰品皮肤带 _txzNN 后缀（如 ak47_txz02），先剥离再匹配。"""
    w = (weapon or "").lower()
    w = re.sub(r"_txz\d+$", "", w)  # 完美皮肤后缀（实测 ak47_txz02/awp_txz02/nova_txz02…）
    return WEAPON_CLASSES.get(w, "other")


def distance_bucket(dist_m: float) -> str:
    if dist_m < 5:
        return "0-5m"
    if dist_m < 15:
        return "5-15m"
    return "15m+"


def _sid(v) -> str:
    """steamid 归一化：字符串直接返回（保精度），浮点尽力转换（17 位会丢精度，勿用于 grenades 帧）。"""
    s = str(v)
    if re.fullmatch(r"\d{15,18}", s):
        return s
    try:
        return str(int(float(v)))
    except (TypeError, ValueError, OverflowError):
        return s


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


def analyze_duels_damage(damages, kills, steam_id: int) -> tuple[float | None, float | None]:
    """damages 交火口径（1.1 近似）：击杀事件为窗界，user 参与且双方互伤的交火窗结算。

    - first_strike_win_rate：user 先手（窗口内首个伤害出自 user）且分出胜负的窗口中 user 胜率；
    - mirror_win_rate：双方武器类相同（各取其造成伤害的武器类）且分出胜负的窗口中 user 胜率；
    - 无击杀结算的互伤窗口不计入分母；样本为 0 时返回 None。
    """
    dmg = damages.filter(
        col("attacker_steamid").is_not_null() & col("victim_steamid").is_not_null()
    ).to_dicts() if damages.height else []
    kill_rows = [k for k in kills.to_dicts() if k.get("tick") is not None]
    kill_ticks = sorted(int(k["tick"]) for k in kill_rows)
    events = sorted(dmg, key=lambda r: int(r["tick"]))

    # 切窗：kill tick 为窗界（同 tick 伤害属被击杀收尾的窗口）
    windows: list[tuple[list[dict], int, int]] = []  # (events, start_tick, end_tick)
    cur: list[dict] = []
    cur_start = 0
    ki = 0
    for e in events:
        tick = int(e["tick"])
        while ki < len(kill_ticks) and kill_ticks[ki] < tick:
            if cur:
                windows.append((cur, cur_start, kill_ticks[ki]))
                cur = []
            cur_start = kill_ticks[ki]
            ki += 1
        if not cur:
            cur_start = tick
        cur.append(e)
    end_tick = kill_ticks[-1] if kill_ticks and kill_ticks[-1] >= cur_start else (int(events[-1]["tick"]) if events else 0)
    if cur:
        windows.append((cur, cur_start, end_tick))

    fs_wins = fs_total = 0
    mirror_wins = mirror_total = 0
    for win_events, w_start, w_end in windows:
        # 按无序对分组，只看 user 参与且双方互伤的
        by_pair: dict[tuple[int, int], list[dict]] = {}
        for e in win_events:
            a, v = int(e["attacker_steamid"]), int(e["victim_steamid"])
            if a == v:
                continue
            by_pair.setdefault(tuple(sorted((a, v))), []).append(e)
        for (ida, idb), evs in by_pair.items():
            if steam_id not in (ida, idb):
                continue
            other = idb if steam_id == ida else ida
            attackers = {int(e["attacker_steamid"]) for e in evs}
            if not attackers >= {steam_id, other}:  # 非互伤（单方面输出）不计
                continue
            first = int(evs[0]["attacker_steamid"])  # evs 已按 tick 有序
            # 结局：窗口内 user/other 之间的击杀
            outcome = None
            for k in kill_rows:
                kt = int(k["tick"])
                if kt < w_start or kt > w_end:
                    continue
                ka, kv = k.get("attacker_steamid"), k.get("victim_steamid")
                if {ka, kv} == {steam_id, other}:
                    outcome = "win" if ka == steam_id else "lose"
            if outcome is None:
                continue
            mine_class = next((weapon_class(e["weapon"]) for e in evs if int(e["attacker_steamid"]) == steam_id), "other")
            other_class = next((weapon_class(e["weapon"]) for e in evs if int(e["attacker_steamid"]) == other), "other")
            if first == steam_id:
                fs_total += 1
                fs_wins += outcome == "win"
            if mine_class == other_class:
                mirror_total += 1
                mirror_wins += outcome == "win"

    fs_rate = round(fs_wins / fs_total, 3) if fs_total else None
    mirror_rate = round(mirror_wins / mirror_total, 3) if mirror_total else None
    return fs_rate, mirror_rate


def analyze_economy(demo, kills, rounds, steam_id: int, user_side: str | None) -> EconomyDim:
    """经济：回合 buy_type 分布 + 首杀转化率 + 经济模式（1.1）。

    - eco_win_rate：eco/force 回合胜率（经济抗压能力）；
    - full_buy_lose_rate：full buy 回合败率（资源转化能力）；
    - effective_buy_ratio 保持 None（awpy 无总资金列）。
    """
    economy = demo.round_economy
    buys: list[BuyDecision] = []
    eco_wins = eco_total = full_losses = full_total = 0
    if user_side:
        mine = economy.filter(col("side") == user_side).to_dicts()
        win_map = {int(r["round_num"]): r.get("winner_side") for r in rounds.to_dicts()}
        for r in mine:
            buy = r.get("buy_type")
            won = win_map.get(int(r["round_num"])) == user_side
            if buy in ("eco", "force"):
                eco_total += 1
                eco_wins += 1 if won else 0
            elif buy == "full":
                full_total += 1
                full_losses += 0 if won else 1
            buys.append(BuyDecision(
                round_no=int(r["round_num"]),
                buy=buy,
                equip_value=int(r.get("equipment_value") or 0),
                effective=None,  # 有效购买口径需总资金列（awpy 未提供）
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
        eco_win_rate=round(eco_wins / eco_total, 3) if eco_total else None,
        full_buy_lose_rate=round(full_losses / full_total, 3) if full_total else None,
    )


GRENADE_PRICES = {"smoke": 300, "flash": 200, "molotov": 400, "incendiary": 600, "he": 300, "decoy": 50}
GRENADE_TYPES = {"smoke", "flash", "molotov", "incendiary", "he", "decoy"}


def analyze_utility_players(demo, grenades, hurts, kills) -> list[UtilityPlayer]:
    """全场 10 人的道具统计（道具分析 Tab）：投掷分类/致盲敌方与队友/道具伤害/花费估算。

    数据源：grenades 逐 tick 轨迹帧（按 entity_id 去重=一次投掷）、demoparser2 player_blind
    （attacker_steamid→user_steamid）、damages 帧燃烧瓶/手雷伤害。
    """
    from demoparser2 import DemoParser

    # 投掷去重（每 entity_id 一次）；grenades 帧 steamid 是浮点（17 位丢精度）→ 用名称映射回精确 steamid
    name_to_sid = {}
    for r in kills.to_dicts():
        name_to_sid[str(r.get("attacker_name") or "").strip()] = _sid(r.get("attacker_steamid"))
        name_to_sid[str(r.get("victim_name") or "").strip()] = _sid(r.get("victim_steamid"))
    throws = grenades.unique(subset=["entity_id"]).to_dicts()
    per: dict[str, dict] = {}

    def _acc(pid: str, name: str, side: str | None) -> dict:
        if pid not in per:
            per[pid] = {"player_id": pid, "nick_name": name, "side": side,
                        "smoke": 0, "flash": 0, "molotov": 0, "he": 0,
                        "flash_enemies": 0, "flash_teammates": 0, "util_dmg": 0, "spend": 0}
        return per[pid]

    for t in throws:
        pname = str(t.get("thrower_name") or "").strip()
        pid = name_to_sid.get(pname) or _sid(t.get("thrower_steamid"))
        gtype = (t.get("type") or "").lower()
        if gtype not in GRENADE_TYPES:
            continue
        acc = _acc(pid, pname, t.get("thrower_side"))
        if gtype in ("molotov", "incendiary"):
            acc["molotov"] += 1
        elif gtype == "he":
            acc["he"] += 1
        elif gtype == "smoke":
            acc["smoke"] += 1
        elif gtype == "flash":
            acc["flash"] += 1
        acc["spend"] += GRENADE_PRICES.get(gtype, 0)

    # 致盲事件（含敌我区分）
    sides = {}
    for r in kills.to_dicts():
        sides[_sid(r.get("attacker_steamid"))] = r.get("attacker_side")
        sides[_sid(r.get("victim_steamid"))] = r.get("victim_side")
    try:
        blind = DemoParser(str(demo.path)).parse_event("player_blind", other=["attacker_steamid", "user_steamid"])
        for r in blind.to_dict("records"):
            atk = str(r.get("attacker_steamid"))
            if atk not in per or atk == "0":
                continue
            dur = float(r.get("blind_duration") or 0)
            if dur <= 0.1:
                continue
            victim_side = sides.get(str(r.get("user_steamid")))
            atk_side = sides.get(atk)
            if victim_side and atk_side and victim_side != atk_side:
                per[atk]["flash_enemies"] += 1
            else:
                per[atk]["flash_teammates"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[demo解析] 致盲事件提取失败：{exc}")

    # 道具伤害（player_hurt 事件：inferno=燃烧瓶、hegrenade=手雷、molotov=燃烧弹）
    UTIL_WEAPONS = {"inferno", "hegrenade", "molotov"}
    for r in hurts.to_dicts():
        atk = str(r.get("attacker_steamid"))
        wpn = (r.get("weapon") or "").lower()
        wpn = re.sub(r"_txz\d+$", "", wpn)
        if atk in per and wpn in UTIL_WEAPONS:
            per[atk]["util_dmg"] += int(r.get("dmg_health") or 0)

    return [UtilityPlayer(**per[k]) for k in sorted(per)]


def compute_server_ratings(players_v1: list[dict], utility_players: list[UtilityPlayer]) -> ServerRatings:
    """六维能力评分（服务器评价 Tab）：基于 v1 全场 10 人数据 + 道具统计，本场内相对归一化 0-100。

    近似口径（与完美平台官方算法不同）：瞄准=爆头率×命中率；补枪=补枪数；突破=首杀-首死；
    道具=道具伤害+致盲敌方+投掷数；残局=vs1-v5 加权计数；火力=击杀×2+伤害/100。
    """
    util_by_pid = {u.player_id: u for u in utility_players}

    def _norm(vals: dict[str, float], pid: str) -> float | None:
        vs = list(vals.values())
        if len(vs) < 2 or max(vs) == min(vs):
            return 50.0
        lo, hi = min(vs), max(vs)
        return round(50 + (vals[pid] - lo) / (hi - lo) * 50, 1) if pid in vals else None

    raw = {dim: {} for dim in ["aim", "trade", "entry", "util", "clutch", "fire"]}
    for p in players_v1:
        pid = str(p.get("playerId"))
        u = util_by_pid.get(pid)
        hit_total = max(1, int(p.get("fireCount") or 0))
        hit_rate = int(p.get("hitCount") or 0) / hit_total
        raw["aim"][pid] = hit_rate + float(p.get("headShotRatio") or 0)
        raw["trade"][pid] = int(p.get("tradeFragCount") or 0)
        raw["entry"][pid] = int(p.get("entryKill") or 0) * 2 - int(p.get("entryDeath") or 0)
        raw["util"][pid] = (u.util_dmg if u else 0) + (u.flash_enemies * 100 if u else 0) + (u.spend / 10 if u else 0)
        clutch = sum(int(p.get(f"vs{i}") or 0) * i for i in range(1, 6))
        raw["clutch"][pid] = clutch
        raw["fire"][pid] = int(p.get("kill") or 0) * 2 + int(p.get("dmgHealth") or 0) / 100

    zh = {"aim": "瞄准能力", "trade": "补枪能力", "entry": "突破能力", "util": "道具能力", "clutch": "残局能力", "fire": "火力值"}
    players_out: dict[str, dict[str, float]] = {}
    averages: dict[str, float] = {}
    for dim, vals in raw.items():
        nums = [v for v in vals.values()]
        averages[zh[dim]] = round(sum(nums) / len(nums) / (max(nums) - min(nums) + 1e-9) * 100, 1) if nums else 50.0
        for pid in vals:
            players_out.setdefault(pid, {})[zh[dim]] = _norm(vals, pid) or 50.0
    return ServerRatings(players=players_out, averages=averages)


def collect_utility_spots(demo, steam_id: int, user_side: str | None) -> list[UtilitySpot]:
    """道具落点采集（1.1）：user 侧烟/火落点 + 与 user 相关的致盲被闪位置（雷达散点数据源）。"""
    spots: list[UtilitySpot] = []

    def add(kind: str, rows, x_key: str, y_key: str, side_key: str | None = None, side_val: str | None = None):
        for r in rows:
            x, y = r.get(x_key), r.get(y_key)
            if x is None or y is None:
                continue
            spots.append(UtilitySpot(
                kind=kind, x=float(x), y=float(y),
                start_tick=int(r["start_tick"]) if r.get("start_tick") is not None else None,
                end_tick=int(r["end_tick"]) if r.get("end_tick") is not None else None,
                side=(r.get(side_key) if side_key else side_val),
            ))

    if user_side:
        smokes = getattr(demo, "smokes", None)
        if smokes is not None and smokes.height:
            add("smoke", smokes.filter(col("thrower_side") == user_side).to_dicts(), "x", "y", "thrower_side")
        fires = getattr(demo, "fires", None)
        if fires is not None and fires.height:
            add("fire", fires.filter(col("thrower_side") == user_side).to_dicts(), "x", "y", "thrower_side")
    blinds = getattr(demo, "blinds", None)
    if blinds is not None and blinds.height:
        mine = blinds.filter(
            (col("attacker_steamid") == steam_id) | (col("victim_steamid") == steam_id)
        ).to_dicts()
        for r in mine:
            x, y = r.get("victim_x"), r.get("victim_y")
            if x is None or y is None:
                continue
            spots.append(UtilitySpot(
                kind="blind", x=float(x), y=float(y),
                start_tick=int(r["duration"] * TICK_RATE) if r.get("duration") is not None else None,
                side=r.get("victim_side"),
            ))
    return spots


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

    # 分道具购买 vs 使用（1.1）：purchase 次数 × 实际投掷数
    thrown_by_type: dict[str, int] = {}
    for t in throws:
        gtype = t.grenade_type or "unknown"
        thrown_by_type[gtype] = thrown_by_type.get(gtype, 0) + 1
    bought_by_type: dict[str, int] = {}
    item_events = getattr(demo, "item_events", None)
    if item_events is not None and item_events.height:
        buys = item_events.filter(
            (col("action") == "purchase") & (col("steamid") == steam_id)
        ).to_dicts()
        for r in buys:
            gtype = PURCHASE_ITEM_TO_GRENADE.get((r.get("item") or "").lower())
            if gtype:
                bought_by_type[gtype] = bought_by_type.get(gtype, 0) + 1
    usage = []
    for gtype in sorted(set(bought_by_type) | set(thrown_by_type)):
        bought = bought_by_type.get(gtype, 0)
        thrown = thrown_by_type.get(gtype, 0)
        if bought > 0:
            w = round(max(0, bought - thrown) / bought, 3)
        elif thrown > 0:  # 捡漏（别人掉的/死后捡的）：不算浪费
            w = 0.0
        else:
            w = None
        usage.append(GrenadeUsage(grenade_type=gtype, bought=bought, thrown=thrown, waste_rate=w))

    return UtilityDim(
        throws=throws,
        blind_median_s=round(blind_median, 2) if blind_median is not None else None,
        waste_rate=waste_rate,
        enemy_blind_s=round(enemy_blind_s, 2),
        team_blind_s=round(team_blind_s, 2),
        usage=usage,
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
        fs_rate, mirror_rate = analyze_duels_damage(demo.damages, kills, sid)
        duels_dim.first_strike_win_rate = fs_rate
        duels_dim.mirror_win_rate = mirror_rate
        economy_dim = analyze_economy(demo, kills, rounds, sid, user_side)
        utility_players = analyze_utility_players(demo, grenades, demo.damages, kills)
        utility_dim = analyze_utility(demo, grenades, sid)
        utility_dim.players = utility_players
        utility_dim.spots = collect_utility_spots(demo, sid, user_side)
        highlights = detect_highlights(kills, rounds, sid, user_side)

        analysis = FourDimAnalysis(
            match_id=match_id,
            deaths=deaths_dim,
            economy=economy_dim,
            utility=utility_dim,
            duels=duels_dim,
            highlights=highlights,
            meta=AnalysisMeta(parser="awpy 3.3.0"),
        )
    finally:
        cost = time.perf_counter() - t0
        _, peak = _tm.get_traced_memory()
        _tm.stop()
    meta = {"parser": "awpy 3.3.0", "cost_s": round(cost, 1), "peak_mem_mb": round(peak / 1e6)}
    logger.info(f"[demo解析] matchId={match_id} 耗时={meta['cost_s']}s 峰值内存={meta['peak_mem_mb']}MB")
    return analysis, meta
