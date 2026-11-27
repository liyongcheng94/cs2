"""从 demo 文件提取 perfect_analysis 所需的事件流（extract_perfect_events）。

薄胶水层：demoparser2 → 归一化 python dict（tick 全部 int）。
steamid 在真实 demo 里是 u64，这里统一转 str，下游服务只做字符串比较。
"""
from __future__ import annotations

import bisect

from demoparser2 import DemoParser


def _norm_side(t) -> str | None:
    if not isinstance(t, str):
        return None
    t = t.upper()
    if t in ("T", "TERRORIST"):
        return "T"
    if t in ("CT", "COUNTERTERRORIST", "COUNTER-TERRORIST"):
        return "CT"
    return None


def extract_perfect_events(demo_path: str, my_steam_id) -> dict:
    my = str(int(my_steam_id))
    p = DemoParser(demo_path)

    # 回合：freeze_end tick 定边界 + 我方阵营；round_end 给回合号与胜方
    fticks = sorted(p.parse_event("round_freeze_end", other=["tick"])["tick"].tolist())
    team_ticks = p.parse_ticks(["team_name"], ticks=fticks)
    side_by_round: dict[int, str | None] = {}
    for _, row in team_ticks.iterrows():
        if str(int(row["steamid"])) == my:
            r = bisect.bisect_right(fticks, int(row["tick"]))
            side_by_round[r] = _norm_side(row["team_name"])
    revents = p.parse_event("round_end", other=["round", "winner"])
    rounds = []
    for _, r in revents.iterrows():
        no = int(r["round"])
        rounds.append({
            "round": no,
            "start_tick": fticks[no - 1] if no - 1 < len(fticks) else 0,
            "end_tick": int(r["tick"]),
            "winner": _norm_side(r["winner"]),
            "my_side": side_by_round.get(no),
        })

    kills_df = p.parse_event(
        "player_death",
        other=["attacker_steamid", "user_steamid", "assister_steamid", "headshot", "distance"],
    )
    kills = []
    for _, k in kills_df.iterrows():
        kills.append({
            "tick": int(k["tick"]),
            "attacker_steamid": _s(k.get("attacker_steamid")),
            "user_steamid": _s(k.get("user_steamid")),
            "assister_steamid": _s(k.get("assister_steamid")),
            "weapon": k.get("weapon"),
            "headshot": bool(k.get("headshot")),
            "distance": float(k["distance"]) if k.get("distance") is not None else None,
            "attacker_name": k.get("attacker_name") or "",
            "user_name": k.get("user_name") or "",
        })

    hurts = []
    try:
        hurt_df = p.parse_event("player_hurt", other=["attacker_steamid", "user_steamid", "dmg_health", "weapon"])
        for _, h in hurt_df.iterrows():
            hurts.append({
                "tick": int(h["tick"]),
                "attacker_steamid": _s(h.get("attacker_steamid")),
                "user_steamid": _s(h.get("user_steamid")),
                "dmg_health": float(h.get("dmg_health") or 0),
                "weapon": h.get("weapon"),
            })
    except Exception:
        pass  # 个别 demo 无 player_hurt → ADR/命中率降级

    flashes = []
    try:
        # player_blind：每个被致盲玩家一条，attacker=扔闪人
        blind_df = p.parse_event("player_blind", other=["attacker_steamid", "user_steamid", "blind_duration"])
        grouped: dict[int, dict] = {}
        for _, b in blind_df.iterrows():
            tick = int(b["tick"])
            if b.get("attacker_steamid") is None:
                continue
            if float(b.get("blind_duration") or 0) < 0.5:  # 只算有效致盲
                continue
            g = grouped.setdefault(tick, {"tick": tick, "thrower_steamid": _s(b["attacker_steamid"]), "blinded_steamids": []})
            sid = _s(b.get("user_steamid"))
            if sid:
                g["blinded_steamids"].append(sid)
        flashes = list(grouped.values())
    except Exception:
        pass

    fires = []
    try:
        fire_df = p.parse_event("weapon_fire", other=["shooter_steamid"] if False else ["user_steamid"])
        # weapon_fire 的开枪人字段在不同版本可能叫 user_steamid（射击者本人）
        for _, f in fire_df.iterrows():
            sid = f.get("user_steamid") if f.get("user_steamid") is not None else f.get("shooter_steamid")
            fires.append({"tick": int(f["tick"]), "shooter_steamid": _s(sid)})
    except Exception:
        pass

    return {
        "rounds": rounds, "kills": kills, "hurts": hurts,
        "flashes": flashes, "weapon_fires": fires,
    }


def _s(x) -> str | None:
    if x is None:
        return None
    try:
        return str(int(x))
    except (TypeError, ValueError):
        return None
