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
    return out


def spike_demoparser2(demo: Path) -> dict:
    """demoparser2：直接按需提取四维事件（dict[str, DataFrame]）。"""
    from demoparser2 import parse_demo

    out: dict = {}
    kills = parse_demo(demo, ["total_rounds_played"], player=["steamid", "name", "team_name"], other=["total_rounds_played"])
    out["player_death_rows"] = len(kills)
    # 按需事件：死亡/投掷/致盲/回合
    import demoparser2 as dp2

    df = dp2.parse_demo(str(demo))
    out["top_keys"] = sorted(df.keys())
    for key in ("player_death", "grenade_throw", "player_blind", "round_start", "round_end", "bomb_planted"):
        if key in df:
            out[key] = int(len(df[key]))
    return out


def spike_awpy(demo: Path) -> dict:
    """awpy：高层 Demo 对象（内部 demoparser2，输出 polars）。"""
    from awpy import Demo

    d = Demo(path=str(demo), parse_props=None)
    out: dict = {"top_keys": sorted(d.frames.keys()) if hasattr(d, "frames") else "n/a"}
    for key in ("kills", "grenades", "bomb_planted", "rounds", "ticks"):
        attr = getattr(d, key, None)
        if attr is not None:
            out[key] = int(getattr(attr, "height", 0))
    out["ticks_rows"] = int(d.ticks.height) if hasattr(d, "ticks") else None
    return out


def main() -> None:
    demo = Path(sys.argv[1])
    assert demo.exists(), f"demo 不存在：{demo}"
    size_mb = demo.stat().st_size / 1e6
    print(f"demo={demo} size={size_mb:.0f}MB")
    results = {"demo": str(demo), "size_mb": size_mb}
    results["demoparser2"] = bench("demoparser2", lambda: spike_demoparser2(demo))
    results["awpy"] = bench("awpy", lambda: spike_awpy(demo))
    out_file = Path(__file__).resolve().parents[2] / "docs" / "spike-results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"已写入 {out_file}")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str)[:2000])


if __name__ == "__main__":
    main()
