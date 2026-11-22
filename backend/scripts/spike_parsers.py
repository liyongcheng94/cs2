"""解析库 spike：demoparser2 vs awpy 基准（ARCHITECTURE.md 阶段 2 Day 1）。

跑法：backend/.venv/Scripts/python.exe scripts/spike_parsers.py <demo_path>
测量：整场解析耗时 + 峰值内存（tracemalloc）+ 四维所需事件的可得性与行数。
结论写入 docs/spike-demo-parsers.md（人工整理）。
"""
from __future__ import annotations

import json
import sys
import time
import tracemalloc
from pathlib import Path


def bench(name: str, fn):
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        out = fn()
        err = None
    except Exception as exc:  # noqa: BLE001
        out, err = None, f"{type(exc).__name__}: {exc}"
    cost = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"[{name}] cost={cost:.1f}s peak={peak / 1e6:.0f}MB err={err}")
    return out, err


def spike_demoparser2(demo: Path) -> dict:
    """demoparser2 按需提取：只取四维所需事件（评审约定：不建全量 DataFrame）。"""
    from demoparser2 import DemoParser

    p = DemoParser(str(demo))
    header = p.parse_header()
    events = p.parse_events(
        ["player_death", "grenade_throw", "player_blind", "round_start", "round_end", "bomb_planted"]
    )
    out: dict = {
        "header_map": header.get("map_name"),
        "duration_s": header.get("duration"),
        "event_rows": {k: int(len(v)) for k, v in events.items()},
    }
    # 对枪矩阵所需字段示例（player_death：武器/距离/先手判定基础）
    pd = events.get("player_death")
    if pd is not None and len(pd):
        out["player_death_cols"] = sorted(list(pd.columns))[:24]
        out["sample_kill"] = {c: (str(pd.iloc[0][c])) for c in ["attacker_name", "user_name", "dmg_weapon", "distance", "total_rounds_played"] if c in pd.columns}
    return out


def spike_awpy(demo: Path) -> dict:
    """awpy 3.x：Demo 对象（内部 demoparser2，输出 polars）。"""
    from awpy import Demo

    d = Demo(path=str(demo))
    out: dict = {"props": [a for a in dir(d) if not a.startswith("_")][:30]}
    for key in ("kills", "grenades", "bomb", "rounds", "ticks"):
        attr = getattr(d, key, None)
        if attr is not None and hasattr(attr, "height"):
            out[key] = int(attr.height)
    if hasattr(d, "kills") and d.kills is not None and d.kills.height:
        out["kills_cols"] = d.kills.columns[:24]
    return out


def main() -> None:
    demo = Path(sys.argv[1])
    assert demo.exists(), f"demo 不存在：{demo}"
    size_mb = demo.stat().st_size / 1e6
    print(f"demo={demo} size={size_mb:.0f}MB")
    results = {"demo": str(demo), "size_mb": size_mb}
    r1, e1 = bench("demoparser2", lambda: spike_demoparser2(demo))
    results["demoparser2"] = r1 or {"error": e1}
    r2, e2 = bench("awpy", lambda: spike_awpy(demo))
    results["awpy"] = r2 or {"error": e2}
    out_file = Path(__file__).resolve().parents[2] / "docs" / "spike-results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
