"""GO指导定位分析（Phase 3）：
- analyze_positions：把「与我相关的交战」（我击杀/我被杀）按 3×3 归一化网格聚合，
  每格 kills/deaths/win_rate + 标签（优势 ≥60% & n≥3；劣势 ≤40% & n≥3；其余均衡）。
- 坐标范围按交战点 2%~98% 分位取界（去炸弹/世界伤害的离群坐标），与具体地图 callout 解耦；
  未来接社区 callout JSON 时只需替换 grid_row/grid_col → 区域名映射。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import polars as pl
from polars import col

from ..schemas.analysis import CalloutCell, GridCell

_MIN_SAMPLE = 3  # 样本 <3 不贴优势/劣势标签（防 1 格 100% 假信号）
_NEAR_UNITS = 150.0  # 空白区域最近矩形中心的吸附半径（units）


@lru_cache(maxsize=32)
def _load_callouts(map_en: str) -> list[dict]:
    """按地图加载 callout 矩形表（app/data/callouts.json，nav mesh place names）。"""
    path = Path(__file__).parent.parent / "data" / "callouts.json"
    try:
        tables = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return tables.get(map_en) or []


def place_of(map_en: str, x: float, y: float, z: float | None = None) -> str | None:
    """世界坐标 → callout 地名：面积最小且包含该点的矩形；无包含时吸附最近中心（≤150 units）。"""
    rects = _load_callouts(map_en)
    if not rects:
        return None
    best = None  # (面积, name)
    nearest = None  # (距离, name)
    for r in rects:
        x0, x1, y0, y1 = r["x0"], r["x1"], r["y0"], r["y1"]
        if r["z0"] is not None and z is not None and not (r["z0"] <= z <= r["z1"]):
            continue
        if x0 <= x <= x1 and y0 <= y <= y1:
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, r["name"])
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
        if nearest is None or d < nearest[0]:
            nearest = (d, r["name"])
    if best:
        return best[1]
    if nearest and nearest[0] <= _NEAR_UNITS:
        return nearest[1]
    return None


def analyze_callouts(kills, steam_id: int, map_en: str) -> list[CalloutCell]:
    """与 user 相关的交战按 callout 地名聚合（击杀点=我方枪位，死亡点=我方枪位）。"""
    if not _load_callouts(map_en):
        return []
    sid = str(steam_id)
    involved = kills.with_columns(
        col("attacker_steamid").cast(pl.Utf8).alias("attacker_steamid"),
        col("victim_steamid").cast(pl.Utf8).alias("victim_steamid"),
    ).filter((col("attacker_steamid") == sid) | (col("victim_steamid") == sid))
    agg: dict[str, dict] = {}
    for r in involved.to_dicts():
        mine_attacker = r.get("attacker_steamid") == sid
        x, y = (r.get("attacker_x"), r.get("attacker_y")) if mine_attacker else (r.get("victim_x"), r.get("victim_y"))
        z = (r.get("attacker_z") if mine_attacker else r.get("victim_z")) or 0.0
        if x is None or y is None:
            continue
        place = place_of(map_en, float(x), float(y), float(z))
        if not place:
            continue
        cell = agg.setdefault(place, {"kills": 0, "deaths": 0})
        if mine_attacker:
            cell["kills"] += 1
        else:
            cell["deaths"] += 1
    cells: list[CalloutCell] = []
    for place, v in sorted(agg.items(), key=lambda kv: -(kv[1]["kills"] + kv[1]["deaths"])):
        n = v["kills"] + v["deaths"]
        wr = v["kills"] / n if n else None
        if n >= _MIN_SAMPLE and wr is not None and wr >= 0.6:
            label = "优势"
        elif n >= _MIN_SAMPLE and wr is not None and wr <= 0.4:
            label = "劣势"
        else:
            label = "均衡"
        cells.append(CalloutCell(
            place=place, kills=v["kills"], deaths=v["deaths"],
            win_rate=round(wr, 3) if wr is not None else None, label=label,
        ))
    return cells


def _percentile_bounds(xs: list[float], ys: list[float]) -> tuple[float, float, float, float]:
    xs_sorted = sorted(xs)
    ys_sorted = sorted(ys)

    def _pct(arr: list[float], p: float) -> float:
        if not arr:
            return 0.0
        idx = max(0, min(len(arr) - 1, int(p * (len(arr) - 1))))
        return arr[idx]

    return (
        _pct(xs_sorted, 0.02), _pct(xs_sorted, 0.98),
        _pct(ys_sorted, 0.02), _pct(ys_sorted, 0.98),
    )


def _grid_of(x: float, y: float, x0: float, x1: float, y0: float, y1: float) -> tuple[int, int]:
    col_i = 1 if x1 <= x0 else min(2, max(0, int((x - x0) / (x1 - x0) * 3)))
    row_i = 1 if y1 <= y0 else min(2, max(0, int((y - y0) / (y1 - y0) * 3)))
    return row_i, col_i


def analyze_positions(kills, steam_id: int) -> list[GridCell]:
    """与 user 相关的交战 → 3×3 网格聚合。击杀点=我方枪位(attacker)，死亡点=我方枪位(victim)。"""
    sid = str(steam_id)
    # 真实 demo 的 steamid 列可能被 awpy 推断为 u64，与字符串比较会 ComputeError → 先统一转 Utf8
    involved = kills.with_columns(
        col("attacker_steamid").cast(pl.Utf8).alias("attacker_steamid"),
        col("victim_steamid").cast(pl.Utf8).alias("victim_steamid"),
    ).filter((col("attacker_steamid") == sid) | (col("victim_steamid") == sid))
    rows = involved.to_dicts()
    pts: list[tuple[float, float]] = []
    for r in rows:
        if r.get("attacker_steamid") == sid:
            if r.get("attacker_x") is not None and r.get("attacker_y") is not None:
                pts.append((float(r["attacker_x"]), float(r["attacker_y"])))
        else:
            if r.get("victim_x") is not None and r.get("victim_y") is not None:
                pts.append((float(r["victim_x"]), float(r["victim_y"])))
    if not pts:
        return []
    x0, x1, y0, y1 = _percentile_bounds([p[0] for p in pts], [p[1] for p in pts])

    agg: dict[tuple[int, int], dict] = {}
    for r in rows:
        mine_attacker = r.get("attacker_steamid") == sid
        if mine_attacker:
            x, y = r.get("attacker_x"), r.get("attacker_y")
        else:
            x, y = r.get("victim_x"), r.get("victim_y")
        if x is None or y is None:
            continue  # 炸弹/世界击杀无坐标
        cell = agg.setdefault(_grid_of(float(x), float(y), x0, x1, y0, y1), {"kills": 0, "deaths": 0})
        if mine_attacker:
            cell["kills"] += 1
        else:
            cell["deaths"] += 1

    cells: list[GridCell] = []
    for (row_i, col_i), v in sorted(agg.items()):
        n = v["kills"] + v["deaths"]
        wr = v["kills"] / n if n else None
        if n >= _MIN_SAMPLE and wr is not None and wr >= 0.6:
            label = "优势"
        elif n >= _MIN_SAMPLE and wr is not None and wr <= 0.4:
            label = "劣势"
        else:
            label = "均衡"
        cells.append(GridCell(
            grid_row=row_i, grid_col=col_i, kills=v["kills"], deaths=v["deaths"],
            win_rate=round(wr, 3) if wr is not None else None, label=label,
        ))
    return cells
