"""基线画像 API（Phase 4）：最近 30 场实时聚合；硬件信息沿用 baseline 种子；无数据兜底种子画像。"""
from fastapi import APIRouter, HTTPException

from ..database import SessionDep
from ..models import DemoAnalysis, Match, MatchStat, PlayerProfile

router = APIRouter(prefix="/profile", tags=["profile"])

_GRADE_DIMS = ["瞄准能力", "补枪能力", "突破能力", "道具能力", "残局能力", "火力值"]


def _grade(diff: float | None) -> str | None:
    if diff is None:
        return None
    if diff >= 10:
        return "A"
    if diff >= -5:
        return "B"
    return "C"


@router.get("")
def get_profile(session: SessionDep) -> dict:
    profile = session.get(PlayerProfile, "baseline")
    if profile is None:
        raise HTTPException(status_code=404, detail="画像未初始化")
    base = dict(profile.data or {})

    from datetime import datetime, timezone

    from sqlmodel import select

    from ..services import settings_service

    matches = session.exec(select(Match).order_by(Match.played_at.desc()).limit(30)).all()
    if not matches:
        return {"key": profile.key, "data": {**base, "real": False},
                "updated_at": profile.updated_at.isoformat()}

    ids = [m.match_id for m in matches]
    stats = {s.match_id: s for s in session.exec(select(MatchStat)).all() if s.match_id in set(ids)}
    analyses = {a.match_id: a for a in session.exec(select(DemoAnalysis)).all() if a.match_id in set(ids)}
    steam_id = settings_service.get_value(session, "wanmei.steam_id") or ""

    # 主玩地图：近 30 场众数
    map_count: dict[str, int] = {}
    for m in matches:
        if m.map_name:
            map_count[m.map_name] = map_count.get(m.map_name, 0) + 1
    main_map = max(map_count, key=map_count.get) if map_count else None

    # 爆头率：实测均值；手枪局：官方无 per-round WE → 用手枪局胜率代替（前端文案同步）
    hs_vals = [s.hs_rate for s in stats.values() if s.hs_rate is not None]
    pistol_total = pistol_won = 0
    for m in matches:
        da = analyses.get(m.match_id)
        if not da:
            continue
        payload = da.payload if not isinstance(da.payload, str) else {}
        pr = (payload or {}).get("pistol_rounds") or {}
        pistol_total += int(pr.get("total") or 0)
        pistol_won += int(pr.get("won") or 0)

    # 六维 grades：mine vs 房均差值 → A/B/C
    mine_acc: dict[str, list[float]] = {}
    room_acc: dict[str, list[float]] = {}
    for m in matches:
        da = analyses.get(m.match_id)
        if not da:
            continue
        payload = da.payload if not isinstance(da.payload, str) else {}
        players = ((payload or {}).get("utility") or {}).get("server_ratings", {}).get("players") or {}
        me = players.get(str(steam_id))
        if not me:
            continue
        for d in _GRADE_DIMS:
            v = me.get(d)
            if v is not None:
                mine_acc.setdefault(d, []).append(float(v))
            for p in players.values():
                pv = p.get(d)
                if pv is not None:
                    room_acc.setdefault(d, []).append(float(pv))

    grades: dict[str, str] = {}
    for d in _GRADE_DIMS:
        if mine_acc.get(d) and room_acc.get(d):
            diff = sum(mine_acc[d]) / len(mine_acc[d]) - sum(room_acc[d]) / len(room_acc[d])
            g = _grade(diff)
            if g:
                grades[d] = g

    data = {
        **base,  # 硬件：mouse/dpi/sens 等
        "real": True,
        "recent_matches": len(matches),
        "main_map": main_map,
        "hs_rate": round(sum(hs_vals) / len(hs_vals), 3) if hs_vals else None,
        "pistol_win_rate": round(pistol_won / pistol_total, 3) if pistol_total else None,
        "grades": grades,
    }
    return {"key": profile.key, "data": data, "updated_at": datetime.now(timezone.utc).isoformat()}
