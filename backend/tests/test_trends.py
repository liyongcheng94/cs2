"""长期追踪契约：GET /api/matches/stats/trends 跨场聚合（逐场点 + 地图胜率）。"""
from datetime import datetime

from app.database import session_factory
from app.models import DemoAnalysis, Match, MatchStat


def _seed():
    with session_factory() as s:
        s.add(Match(match_id="T1", map_name="炙热沙城Ⅱ", win=True, played_at=datetime(2026, 11, 21, 12, 0, 0)))
        s.add(Match(match_id="T2", map_name="炙热沙城Ⅱ", win=False, played_at=datetime(2026, 11, 22, 12, 0, 0)))
        s.add(Match(match_id="T3", map_name="炼狱小镇", win=False, played_at=datetime(2026, 11, 22, 20, 0, 0)))
        s.add(MatchStat(match_id="T1", rating=1.2, adr=85, hs_rate=0.5))
        s.add(MatchStat(match_id="T2", rating=0.8, adr=70, hs_rate=0.4))
        s.add(MatchStat(match_id="T3", rating=0.9, adr=75, hs_rate=0.45))
        s.add(DemoAnalysis(match_id="T1", schema_version="1.1", parser="awpy 3.3.0", payload={
            "utility": {"enemy_blind_s": 20.0, "team_blind_s": 4.0, "waste_rate": 0.2},
            "economy": {"eco_win_rate": 0.5, "full_buy_lose_rate": 0.3},
        }))
        s.commit()


def test_trends_points_and_by_map(client):
    """
    Given 3 场对局（dust2 一胜一负 + 小镇一负）+ stats + 1 场解析 payload
    When  GET /api/matches/stats/trends
    Then  points 3 个（时间倒序，T1 含 utility/economy 指标）；by_map dust2 胜率 0.5
    """
    _seed()
    out = client.get("/api/matches/stats/trends").json()
    assert len(out["points"]) == 3
    assert out["points"][0]["match_id"] == "T3"  # 时间倒序
    p1 = next(p for p in out["points"] if p["match_id"] == "T1")
    assert p1["rating"] == 1.2 and p1["map_en"] == "de_dust2"
    assert p1["utility"]["enemy_blind_s"] == 20.0 and p1["economy"]["eco_win_rate"] == 0.5
    by_map = {m["map_en"]: m for m in out["by_map"]}
    assert by_map["de_dust2"]["games"] == 2 and by_map["de_dust2"]["win_rate"] == 0.5
    assert by_map["de_inferno"]["games"] == 1


def test_trends_empty(client):
    """
    Given 无对局
    When  GET trends
    Then  points/by_map 为空数组（不 404，前端好渲染空态）
    """
    out = client.get("/api/matches/stats/trends").json()
    assert out["points"] == [] and out["by_map"] == []
