"""GO指导定位分析（Phase 3）：
Given demo kills 坐标（attacker/victim x/y）
When  analyze_positions 按 3×3 归一化网格聚合我的交战（击杀+死亡）
Then  每格 kills/deaths/win_rate/区域标签（优势≥60% & n≥3、劣势≤40% & n≥3、其余均衡）
And   五维聚合：五维 vs 房均（server_ratings 六维按 match 聚合，mine vs all-players 均值）
"""
import polars as pl
import pytest

from app.services.position_analysis import analyze_positions, GridCell


def _kills_df(rows):
    schema = {
        "tick": pl.Int64, "attacker_steamid": pl.Utf8, "victim_steamid": pl.Utf8,
        "attacker_x": pl.Float64, "attacker_y": pl.Float64,
        "victim_x": pl.Float64, "victim_y": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


ME = "1000"

def test_advantage_cell_labeled():
    # 9 次交战全在同一格：我 6 杀 3 死 → 66.7% ≥60% 且 n=9≥3 → 优势
    rows = []
    for i in range(6):  # my kills: attacker=me @ (100,100), victim @ (150,100)
        rows.append({"tick": 100 + i, "attacker_steamid": ME, "victim_steamid": "2",
                     "attacker_x": 100.0, "attacker_y": 100.0, "victim_x": 150.0, "victim_y": 100.0})
    for i in range(3):  # my deaths: attacker=2 @ (150,100), victim=me @ (100,100)
        rows.append({"tick": 200 + i, "attacker_steamid": "2", "victim_steamid": ME,
                     "attacker_x": 150.0, "attacker_y": 100.0, "victim_x": 100.0, "victim_y": 100.0})
    cells = analyze_positions(_kills_df(rows), int(ME))
    assert len(cells) >= 1
    c = max(cells, key=lambda c: c.kills + c.deaths)
    assert c.kills == 6 and c.deaths == 3
    assert c.win_rate == pytest.approx(6 / 9, abs=0.01)
    assert c.label == "优势"


def test_disadvantage_cell_labeled():
    rows = []
    for i in range(1):  # 1 kill
        rows.append({"tick": 100, "attacker_steamid": ME, "victim_steamid": "2",
                     "attacker_x": 100.0, "attacker_y": 100.0, "victim_x": 150.0, "victim_y": 100.0})
    for i in range(4):  # 4 deaths same cell
        rows.append({"tick": 200 + i, "attacker_steamid": "2", "victim_steamid": ME,
                     "attacker_x": 150.0, "attacker_y": 100.0, "victim_x": 100.0, "victim_y": 100.0})
    cells = analyze_positions(_kills_df(rows), int(ME))
    c = max(cells, key=lambda c: c.kills + c.deaths)
    assert c.kills == 1 and c.deaths == 4
    assert c.label == "劣势"


def test_low_sample_cell_is_balanced():
    # 2 交战全胜（n=2 <3）→ 均衡（样本不足不给标签）
    rows = [{"tick": 100, "attacker_steamid": ME, "victim_steamid": "2",
             "attacker_x": 100.0, "attacker_y": 100.0, "victim_x": 150.0, "victim_y": 100.0},
            {"tick": 101, "attacker_steamid": ME, "victim_steamid": "3",
             "attacker_x": 100.0, "attacker_y": 100.0, "victim_x": 150.0, "victim_y": 100.0}]
    cells = analyze_positions(_kills_df(rows), int(ME))
    c = max(cells, key=lambda c: c.kills + c.deaths)
    assert c.label == "均衡"


def test_cells_span_full_map_grid():
    # 交战分布在四个象限 → 至少 4 格
    pts = [(100.0, 100.0), (1000.0, 100.0), (100.0, 1000.0), (1000.0, 1000.0)]
    rows = []
    t = 0
    for x, y in pts:
        rows.append({"tick": t, "attacker_steamid": ME, "victim_steamid": "2",
                     "attacker_x": x, "attacker_y": y, "victim_x": x + 50, "victim_y": y})
        t += 1
    cells = analyze_positions(_kills_df(rows), int(ME))
    assert len({(c.grid_row, c.grid_col) for c in cells}) == 4


def test_go_report_aggregates_five_dim_and_positions(client, monkeypatch):
    """
    Given 3 场 demoanalysis payload（server_ratings 六维 + positions）
    When  GET /api/matches/go-report?n=3
    Then  five_dim 含瞄准/道具等 6 维 {mine, room_avg}；positions 跨场按格合并；
          普通用户只见自己的数据
    """
    import json as _json

    from app.database import session_factory
    from app.models import DemoAnalysis, Match

    def ratings_payload(k_zhen, k_dao):
        return {
            "utility": {"server_ratings": {"players": {
                "1": {"瞄准能力": k_zhen, "补枪能力": 70.0, "突破能力": 60.0, "道具能力": k_dao, "残局能力": 55.0, "火力值": 65.0},
                "2": {"瞄准能力": 50.0, "补枪能力": 50.0, "突破能力": 50.0, "道具能力": 50.0, "残局能力": 50.0, "火力值": 50.0},
            }}},
            "positions": [
                {"grid_row": 1, "grid_col": 1, "kills": 2, "deaths": 0, "win_rate": 1.0, "label": "均衡"},
            ],
        }

    with session_factory() as s:
        for i, (z, d) in enumerate([(80.0, 40.0), (60.0, 50.0), (70.0, 60.0)]):
            m = Match(match_id=f"m{i}", map_name="Mirage", mode="competitive", win=True,
                      score1=13, score2=5, demo_status="analyzed")
            s.add(m)
            s.commit()
            s.add(DemoAnalysis(match_id=f"m{i}", schema_version=1, payload=ratings_payload(z, d),
                               parser="awpy", user_id=None))
        s.commit()

    client.put("/api/settings", json={"wanmei.steam_id": "1"})
    r = client.get("/api/matches/go-report?n=3")
    assert r.status_code == 200, r.text
    body = r.json()
    fd = body["five_dim"]
    assert fd["瞄准能力"]["mine"] == pytest.approx((80 + 60 + 70) / 3)
    assert fd["瞄准能力"]["room_avg"] == pytest.approx((80 + 50 + 60 + 50 + 70 + 50) / 6)
    assert len(body["positions"]) == 1
    assert body["positions"][0]["kills"] == 6  # 3 场 × 2 杀 同格合并
    assert body["matches_analyzed"] == 3
