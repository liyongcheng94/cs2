"""具体点位（callout）标注场景测试。

场景（Given/When/Then）：
1. 点位归属：给定 mirage 狙位坐标（SnipersNest 矩形内），Then place_of 返回 SnipersNest；
   空白区域（无矩形包含且最近中心 >150 units）→ None。
2. 聚合：给定我与对手在 PalaceAlley 互杀 2/1、在 CTSpawn 0/2，Then
   analyze_callouts 返回 PalaceAlley 2/1、CTSpawn 0/2，样本<3 标"均衡"。
3. 最小矩形优先：嵌套矩形（BombsiteA 内的小区 Shop）→ 命中更小的那个。
4. 无坐标/未知地图 → 空列表不崩溃。
"""
import pytest

from app.services.position_analysis import analyze_callouts, place_of

MIRAGE = {
    "name": "SnipersNest", "x0": 500.0, "x1": 600.0, "y0": -200.0, "y1": -100.0, "z0": 0.0, "z1": 128.0,
}
CT = {
    "name": "CTSpawn", "x0": -500.0, "x1": -400.0, "y0": -400.0, "y1": -300.0, "z0": 0.0, "z1": 128.0,
}
PALACE = {
    "name": "PalaceAlley", "x0": 100.0, "x1": 200.0, "y0": 100.0, "y1": 200.0, "z0": 0.0, "z1": 128.0,
}


@pytest.fixture
def fake_map(monkeypatch):
    monkeypatch.setattr("app.services.position_analysis._load_callouts", lambda map_en: [MIRAGE, CT, PALACE])


def test_place_of_inside_rect(fake_map):
    assert place_of("de_mirage", 550.0, -150.0, 64.0) == "SnipersNest"


def test_place_of_blank_area_returns_none(fake_map):
    assert place_of("de_mirage", 5000.0, 5000.0, 64.0) is None


def test_smallest_containing_rect_wins(fake_map):
    # 在 PalaceAlley 内构造一个嵌套小矩形（模拟 BombsiteA 内 Shop）
    import app.services.position_analysis as pa
    pa._load_callouts = lambda map_en: [PALACE, {"name": "Shop", "x0": 120.0, "x1": 160.0, "y0": 120.0, "y1": 160.0, "z0": 0.0, "z1": 64.0}]
    assert place_of("de_mirage", 140.0, 140.0, 32.0) == "Shop"


def test_analyze_callouts_aggregates(fake_map):
    import polars as pl
    sid = 76561198339750836
    rows = [
        # PalaceAlley：我杀 2 死 1
        {"attacker_steamid": sid, "victim_steamid": 1, "attacker_x": 150.0, "attacker_y": 150.0, "attacker_z": 64.0},
        {"attacker_steamid": sid, "victim_steamid": 2, "attacker_x": 180.0, "attacker_y": 180.0, "attacker_z": 64.0},
        {"attacker_steamid": 3, "victim_steamid": sid, "victim_x": 160.0, "victim_y": 120.0, "victim_z": 64.0},
        # CTSpawn：我死 2
        {"attacker_steamid": 4, "victim_steamid": sid, "victim_x": -450.0, "victim_y": -350.0, "victim_z": 64.0},
        {"attacker_steamid": 5, "victim_steamid": sid, "victim_x": -420.0, "victim_y": -320.0, "victim_z": 64.0},
    ]
    kills = pl.DataFrame(rows)
    cells = analyze_callouts(kills, sid, "de_mirage")
    by = {c.place: c for c in cells}
    assert by["PalaceAlley"].kills == 2 and by["PalaceAlley"].deaths == 1
    # n=3, wr=2/3=0.667 ≥0.6 → 优势
    assert by["PalaceAlley"].label == "优势"
    assert by["CTSpawn"].deaths == 2 and by["CTSpawn"].kills == 0
    assert by["CTSpawn"].label == "均衡"  # n=2 <3 不贴标签


def test_no_coords_or_unknown_map_empty():
    import polars as pl
    kills = pl.DataFrame(schema={"attacker_steamid": pl.Int64, "victim_steamid": pl.Int64,
                                 "attacker_x": pl.Float64, "attacker_y": pl.Float64, "attacker_z": pl.Float64,
                                 "victim_x": pl.Float64, "victim_y": pl.Float64, "victim_z": pl.Float64})
    assert analyze_callouts(kills, 123, "de_mirage") == []
    assert analyze_callouts(kills, 123, "de_nonslaught") == []
