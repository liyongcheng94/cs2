"""重复死亡模式（1.1）：跨场聚合 DemoAnalysis.deaths.events，同图同网格 ≥MIN_COUNT 次为"惯性死亡点"。

网格 500 unit ≈ 9.5m（对枪距离桶的细粒度补充）；产物供周报段落与 AI 教练上下文注入。
"""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import DemoAnalysis, Match

GRID_UNITS = 500  # ≈9.5m
MIN_COUNT = 3
TOP_N = 5


def death_patterns(session: Session) -> list[dict]:
    """跨场聚合：返回 [{map_name, x, y, count, disadvantaged_n, matches_n}]（count 降序 TopN）。"""
    analyses = session.exec(select(DemoAnalysis)).all()
    if not analyses:
        return []
    map_by_mid = {
        m.match_id: m.map_name for m in session.exec(select(Match)).all()
    }
    cells: dict[tuple[str, int, int], dict] = {}
    for a in analyses:
        map_name = map_by_mid.get(a.match_id)
        if not map_name:
            continue  # 地图未知（如 mock/实验数据）不入模式
        events = ((a.payload or {}).get("deaths") or {}).get("events") or []
        for e in events:
            x, y = e.get("victim_x"), e.get("victim_y")
            if x is None or y is None:
                continue
            key = (map_name, int(x // GRID_UNITS), int(y // GRID_UNITS))
            cell = cells.setdefault(key, {"xs": [], "ys": [], "count": 0, "disadvantaged_n": 0, "match_ids": set()})
            cell["xs"].append(x)
            cell["ys"].append(y)
            cell["count"] += 1
            if e.get("disadvantaged_position"):
                cell["disadvantaged_n"] += 1
            cell["match_ids"].add(a.match_id)

    out = [
        {
            "map_name": map_name,
            "x": round(sum(c["xs"]) / len(c["xs"]), 1),
            "y": round(sum(c["ys"]) / len(c["ys"]), 1),
            "count": c["count"],
            "disadvantaged_n": c["disadvantaged_n"],
            "matches_n": len(c["match_ids"]),
        }
        for (map_name, _, _), c in cells.items()
        if c["count"] >= MIN_COUNT
    ]
    out.sort(key=lambda p: (-p["count"], -p["disadvantaged_n"]))
    return out[:TOP_N]
