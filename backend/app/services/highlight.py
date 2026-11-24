"""高光检测（纯解析版，借鉴 cs2-highlights-maker 的"可看性"评分思路）。

demo 驱动：user 击杀按回合内时间间隔（>20s 断开）聚类成"时刻"，逐时刻打分取 TopN。
1vX 完整残局判定需逐 tick 存活跟踪（留 HLAE 方案）；此处用"时刻起点队内存活 ≤2"近似残局起点。

评分公式：kills×2 + 爆头×1 + 特殊击杀(刀/zeus/taser/noscope/穿墙 各+1) + 多杀加成(3K+2/4K+5/ACE+8)
         + 回合胜利 +1 + 残局起点(队内存活 ≤2) +2；单时刻击杀 < MIN_KILLS 不收录。
"""
from __future__ import annotations

import polars as pl
from polars import col

from app.schemas.analysis import HighlightMoment

TICK_RATE = 64  # CS2 标准 64 tick（128 tick demo 的聚类阈值误差可接受）
GAP_TICKS = 20 * TICK_RATE  # 时刻聚类间隔：20s
MIN_KILLS = 2  # 单时刻最少击杀数（对齐 cs2-highlights-maker 默认）
TOP_N = 5

SPECIAL_WEAPONS = ("knife", "zeus", "taser")
MULTI_BONUS = {"ACE": 8, "4K": 5, "3K": 2}
TEAM_ALIVE_SIZE = 5


def _special_count(weapon: str | None, noscope: bool, penetrated: bool) -> int:
    w = (weapon or "").lower()
    return int(any(s in w for s in SPECIAL_WEAPONS)) + int(bool(noscope)) + int(bool(penetrated))


def _label(kills: int) -> str:
    if kills >= 5:
        return "ACE"
    if kills == 4:
        return "4K"
    if kills == 3:
        return "3K"
    return "双杀"


def detect_highlights(kills, rounds, steam_id: int, user_side: str | None) -> list[HighlightMoment]:
    """聚类 user 击杀 → 逐时刻评分 → TopN（score 降序）。"""
    my = kills.filter(col("attacker_steamid") == steam_id).to_dicts()
    if not my:
        return []
    my.sort(key=lambda r: int(r["tick"]))
    rounds_list = rounds.to_dicts()
    win_map = {int(r["round_num"]): r.get("winner_side") for r in rounds_list}

    def _bounds(r: dict) -> tuple[int, int]:
        """回合起止（official_end_tick 真实数据可为 None → end_tick 兜底；仍缺则跳过该回合）。"""
        start = int(r["start_tick"])
        raw_end = r["official_end_tick"] if r["official_end_tick"] is not None else r.get("end_tick")
        return start, int(raw_end) if raw_end is not None else -1

    round_bounds = {int(r["round_num"]): _bounds(r) for r in rounds_list}

    def round_of(tick: int) -> int | None:
        for rn, (s, e) in round_bounds.items():
            if e >= s and s <= tick <= e:
                return rn
        return None

    # 逐回合内聚类（跨回合必断开；回合内 >20s 断开）
    moments: list[list[dict]] = []
    cur: list[dict] = []
    cur_round: int | None = None
    for k in my:
        tick = int(k["tick"])
        rn = round_of(tick)
        if cur and (rn != cur_round or tick - int(cur[-1]["tick"]) > GAP_TICKS):
            moments.append(cur)
            cur = []
        cur.append(k)
        cur_round = rn
    if cur:
        moments.append(cur)

    out: list[HighlightMoment] = []
    for m in moments:
        if len(m) < MIN_KILLS:
            continue
        rn = round_of(int(m[0]["tick"]))
        kills_n = len(m)
        headshots = sum(1 for k in m if k.get("headshot"))
        specials = sum(_special_count(k.get("weapon"), bool(k.get("noscope")), bool(k.get("penetrated"))) for k in m)
        label = _label(kills_n)
        won = win_map.get(rn) == user_side if rn is not None else None
        # 残局起点近似：时刻首杀前，user 侧已死亡人数 ≥3（队内存活 ≤2，含 user）
        clutch = False
        if user_side and rn is not None:
            start_tick = int(m[0]["tick"])
            dead_team = sum(
                1 for k in kills.to_dicts()
                if k.get("victim_side") == user_side and int(k["tick"]) < start_tick
            )
            clutch = (TEAM_ALIVE_SIZE - dead_team) <= 2
        score = (
            kills_n * 2
            + headshots
            + specials
            + MULTI_BONUS.get(label, 0)
            + (1 if won else 0)
            + (2 if clutch else 0)
        )
        out.append(HighlightMoment(
            round_no=rn,
            start_tick=int(m[0]["tick"]),
            end_tick=int(m[-1]["tick"]),
            kills=kills_n,
            headshots=headshots,
            score=score,
            label=label,
            round_won=won,
            clutch=clutch,
        ))
    out.sort(key=lambda h: h.score or 0, reverse=True)
    return out[:TOP_N]
