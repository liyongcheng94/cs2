"""完美风格完整对局分析（perfect_analysis）。

输入是「已按 demo 解析、归一化为 python dict」的事件流（tick 全部 int）：
  rounds:  [{round, start_tick, end_tick, winner("T"/"CT"), my_side}]
  kills:   [{tick, attacker_steamid, user_steamid, weapon, headshot, assister_steamid, distance, attacker_name, user_name}]
  hurts:   [{tick, attacker_steamid, user_steamid, dmg_health}]
  flashes: [{tick, thrower_steamid, blinded_steamids}]
  weapon_fires(可选): [{tick, shooter_steamid}]

steamid 允许 int/str 混用（真实 demo 里是 u64，统一转 str 比较）。
队伍归属用击杀图 2-着色推断（attacker 与 victim 必然敌对）。
"""
from __future__ import annotations

import bisect
from collections import defaultdict

from ..schemas.perfect import (
    AimDim, ClutchAttempt, ClutchDim, EntryDim, MatchupDim, MatchupRow,
    PerfectAnalysis, PerfectSummary, TradeDim, UtilityDim,
)

TRADE_WINDOW_TICKS = 320  # 5s @ 64 tick/s
TICKS_PER_SEC = 64
TRADE_NEAR_METERS = 20.0     # 队友死时我 ≤20m 才算「我的补枪机会」
TRADE_POS_WINDOW_TICKS = 128  # 位置时间线最近邻查找窗口（±2s）


def _pos_at(positions: list[dict], sid: str, tick: int) -> tuple[float, float] | None:
    """在采样的位置时间线里找 sid 离 tick 最近的一条（±窗口内），返回 (x, y)。"""
    best = None
    best_dt = TRADE_POS_WINDOW_TICKS + 1
    for p in positions:
        if p.get("steamid") != sid:
            continue
        dt = abs(int(p["tick"]) - tick)
        if dt < best_dt:
            best_dt = dt
            best = (float(p["x"]), float(p["y"]))
    return best if best_dt <= TRADE_POS_WINDOW_TICKS else None


def _sid(x) -> str | None:
    if x is None:
        return None
    try:
        v = int(x)
    except (TypeError, ValueError):
        return None
    return str(v)


def _infer_my_teammates(kills: list[dict], my: str) -> set[str]:
    """击杀图 2-着色：attacker 与 victim 敌对，与我的敌人互补的即队友。"""
    adj: dict[str, set[str]] = defaultdict(set)
    for k in kills:
        a, v = _sid(k.get("attacker_steamid")), _sid(k.get("user_steamid"))
        if a and v:
            adj[a].add(v)
            adj[v].add(a)
    color: dict[str, bool] = {my: True}
    stack = [my]
    while stack:
        cur = stack.pop()
        for nxt in adj[cur]:
            if nxt not in color:
                color[nxt] = not color[cur]
                stack.append(nxt)
    return {p for p, c in color.items() if c is True}


def _round_of(tick: int, starts: list[int]) -> int | None:
    i = bisect.bisect_right(starts, tick) - 1
    return None if i < 0 else i  # rounds 下标


def analyze_perfect(events: dict, my_steam_id, side: str = "ALL") -> PerfectAnalysis:
    my = _sid(my_steam_id)
    rounds = events.get("rounds") or []
    kills = events.get("kills") or []
    hurts = events.get("hurts") or []
    flashes = events.get("flashes") or []
    fires = events.get("weapon_fires") or []
    positions = events.get("positions") or []  # 有位置时间线 → 补枪机会按 ≤20m 距离过滤

    sel = [r for r in rounds if side == "ALL" or r.get("my_side") == side]
    starts = [int(r["start_tick"]) for r in sel]
    ends = [int(r["end_tick"]) for r in sel]
    win_by_idx = {i: r.get("winner") for i, r in enumerate(sel)}
    side_by_idx = {i: r.get("my_side") for i, r in enumerate(sel)}
    no_by_idx = {i: r.get("round") for i, r in enumerate(sel)}

    def idx_of(tick: int) -> int | None:
        i = _round_of(int(tick), starts)
        if i is None or int(tick) > ends[i]:
            return None
        return i

    teammates = _infer_my_teammates(kills, my)

    # ---- 击杀按回合分组（时序） ----
    kills_by_idx: dict[int, list[dict]] = defaultdict(list)
    for k in kills:
        i = idx_of(int(k["tick"]))
        if i is not None:
            kills_by_idx[i].append(k)
    for i in kills_by_idx:
        kills_by_idx[i].sort(key=lambda k: int(k["tick"]))

    util = UtilityDim()  # 提前初始化，伤害统计里填充
    # ---- 综合数据 ----
    sumr = PerfectSummary(rounds=len(sel))
    my_damage_total = 0.0
    for i, klist in kills_by_idx.items():
        if win_by_idx.get(i) == side_by_idx.get(i):
            sumr.round_wins += 1
        if klist:
            first = klist[0]
            fa, fv = _sid(first.get("attacker_steamid")), _sid(first.get("user_steamid"))
            if fa == my:
                sumr.opening_kills += 1
            elif fv == my:
                sumr.opening_deaths += 1
        for k in klist:
            a, v = _sid(k.get("attacker_steamid")), _sid(k.get("user_steamid"))
            if a == my:
                sumr.kills += 1
                if k.get("headshot"):
                    sumr.hs_kills += 1
            if v == my:
                sumr.deaths += 1
            if k.get("assister_steamid") is not None and _sid(k.get("assister_steamid")) == my:
                sumr.assists += 1
    for h in hurts:
        i = idx_of(int(h["tick"]))
        if i is not None and _sid(h.get("attacker_steamid")) == my:
            my_damage_total += float(h.get("dmg_health") or 0)
            if str(h.get("weapon") or "").lower() in {"hegrenade", "inferno", "molotov", "incgrenade", "decoy"}:
                util.util_damage += float(h.get("dmg_health") or 0)
    sumr.adr = round(my_damage_total / len(sel), 1) if sel else 0.0

    # ---- 瞄准 ----
    my_kill_keys = {
        (int(k["tick"]), _sid(k.get("user_steamid")))
        for k in kills if _sid(k.get("attacker_steamid")) == my and idx_of(int(k["tick"])) is not None
    }
    shots = sum(
        1 for f in fires
        if _sid(f.get("shooter_steamid")) == my and idx_of(int(f["tick"])) is not None
    )
    hits = 0
    for h in hurts:
        i = idx_of(int(h["tick"]))
        if i is None or _sid(h.get("attacker_steamid")) != my:
            continue
        key = (int(h["tick"]), _sid(h.get("user_steamid")))
        if key in my_kill_keys:  # 致死一击已在击杀里计过
            my_kill_keys.discard(key)
            continue
        hits += 1
    hits += len(my_kill_keys)  # 剩余的致死击杀各算一次命中
    dists = [
        float(k["distance"]) for k in kills
        if _sid(k.get("attacker_steamid")) == my and k.get("distance") is not None and idx_of(int(k["tick"])) is not None
    ]
    aim = AimDim(
        shots=shots,
        hits=hits,
        hit_rate=round(hits / shots, 3) if shots else 0.0,
        avg_kill_distance=round(sum(dists) / len(dists), 1) if dists else 0.0,
    )

    # ---- 突破（每回合第一个击杀事件的归因） ----
    entry = EntryDim()
    for i, klist in kills_by_idx.items():
        if not klist:
            continue
        first = klist[0]
        if _sid(first.get("attacker_steamid")) == my:
            entry.entry_kills += 1
        elif _sid(first.get("user_steamid")) == my:
            entry.entry_deaths += 1

    # ---- 补枪（5s 窗口复仇） ----
    trade = TradeDim()
    for i, klist in kills_by_idx.items():
        deaths: list[tuple[int, str, str]] = [  # (tick, victim, killer)
            (int(k["tick"]), _sid(k.get("user_steamid")), _sid(k.get("attacker_steamid")))
            for k in klist
        ]
        for tick_t, victim, killer in deaths:
            if victim is None or killer is None:
                continue
            if victim in teammates and victim != my:
                # 有位置数据时：只有队友死时我活着且在 ≤TRADE_NEAR_METERS 内才计入「我的机会」
                if positions:
                    vp = _pos_at(positions, victim, tick_t)
                    mp = _pos_at(positions, my, tick_t)
                    if vp is None or mp is None:
                        continue
                    if ((vp[0] - mp[0]) ** 2 + (vp[1] - mp[1]) ** 2) ** 0.5 > TRADE_NEAR_METERS:
                        continue
                trade.trade_opportunities += 1
                if any(
                    _sid(k.get("attacker_steamid")) == my and _sid(k.get("user_steamid")) == killer
                    and 0 <= int(k["tick"]) - tick_t <= TRADE_WINDOW_TICKS
                    for k in klist
                ):
                    trade.trade_kills += 1
            if victim == my:
                if any(
                    _sid(k.get("attacker_steamid")) in teammates and _sid(k.get("user_steamid")) == killer
                    and 0 <= int(k["tick"]) - tick_t <= TRADE_WINDOW_TICKS
                    for k in klist
                ):
                    trade.created_opportunities += 1

    # ---- 道具 ----
    for f in flashes:
        i = idx_of(int(f["tick"]))
        if i is None:
            continue
        thrower = _sid(f.get("thrower_steamid"))
        if thrower != my:
            continue
        for b in f.get("blinded_steamids") or []:
            bs = _sid(b)
            if bs == my:
                continue
            if bs in teammates:
                util.flash_teammates += 1
            else:
                util.flash_enemies += 1

    # ---- 残局 ----
    clutch = ClutchDim()
    all_players = set()
    for k in kills:
        for key in ("attacker_steamid", "user_steamid"):
            s = _sid(k.get(key))
            if s:
                all_players.add(s)
    for i, klist in kills_by_idx.items():
        my_side = side_by_idx.get(i)
        alive = set(all_players)
        alive.add(my)  # 我可能整场无击杀/无死亡，但残局检测需要我在场
        clutch_started = False
        vs_count = 0
        ckills = 0
        died_in_clutch = False
        for k in klist:
            v = _sid(k.get("user_steamid"))
            alive.discard(v)
            if clutch_started:
                if _sid(k.get("attacker_steamid")) == my:
                    ckills += 1
            mates_alive = sum(1 for p in alive if p in teammates and p != my)
            enemies_alive = sum(1 for p in alive if p not in teammates)
            if not clutch_started and my in alive and mates_alive == 0 and enemies_alive >= 1:
                clutch_started = True
                vs_count = enemies_alive
            if v == my:
                died_in_clutch = clutch_started
        if clutch_started:
            won = win_by_idx.get(i) == my_side
            if won:
                outcome = "win"
            elif died_in_clutch:
                outcome = "loss"
            else:
                outcome = "saved"
            clutch.attempts.append(
                ClutchAttempt(round_no=no_by_idx.get(i, 0), vs_count=vs_count,
                              outcome=outcome, kills_in_clutch=ckills)
            )

    # ---- 对位矩阵 ----
    opp: dict[str, MatchupRow] = {}
    for k in kills:
        i = idx_of(int(k["tick"]))
        if i is None:
            continue
        a, v = _sid(k.get("attacker_steamid")), _sid(k.get("user_steamid"))
        if a == my and v not in teammates and v != my:
            row = opp.setdefault(v, MatchupRow(opponent_id=v, opponent_name=str(k.get("user_name") or "")))
            row.my_kills += 1
        if v == my and a not in teammates and a != my:
            row = opp.setdefault(a, MatchupRow(opponent_id=a, opponent_name=str(k.get("attacker_name") or "")))
            row.my_deaths += 1
    for h in hurts:
        i = idx_of(int(h["tick"]))
        if i is None:
            continue
        a, v = _sid(h.get("attacker_steamid")), _sid(h.get("user_steamid"))
        dmg = float(h.get("dmg_health") or 0)
        if a == my and v not in teammates and v != my:
            opp.setdefault(v, MatchupRow(opponent_id=v, opponent_name=f"p{v[-4:]}")).my_damage += dmg
        if v == my and a not in teammates and a != my:
            opp.setdefault(a, MatchupRow(opponent_id=a, opponent_name=f"p{a[-4:]}")).their_damage += dmg

    return PerfectAnalysis(
        side=side,
        summary=sumr, aim=aim, entry=entry, trade=trade,
        utility=util, clutch=clutch, matchup=MatchupDim(rows=list(opp.values())),
    )
