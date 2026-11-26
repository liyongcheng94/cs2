"""Phase 4：基线画像实时聚合（最近 30 场实测数据，删「来自 DeepSeek 对话还原」静态标注）。
Given 近 30 场 Match+MatchStat+demoanalysis.server_ratings
When  GET /api/profile
Then  data 含 real=true；main_map=近30场众数地图；hs_rate=MatchStat 均值；
      pistol_we=手枪局 WE 均值（payload.pistol_rounds）；grades=六维 mine-vs-room 差值 A/B/C；
      硬件（mouse/dpi/sens）沿用 baseline 种子
"""
import pytest


def test_profile_computed_from_recent_matches(client):
    with_pistol = {"pistol_rounds": {"rounds": 2, "won": 1, "total": 2}}
    def ratings(zhen):
        return {"utility": {"server_ratings": {"players": {
            "1": {"瞄准能力": zhen, "补枪能力": 70.0, "突破能力": 60.0, "道具能力": 60.0, "残局能力": 55.0, "火力值": 65.0},
            "2": {"瞄准能力": 50.0, "补枪能力": 50.0, "突破能力": 50.0, "道具能力": 50.0, "残局能力": 50.0, "火力值": 50.0},
        }}}}

    from sqlmodel import Session

    from app.database import session_factory
    from app.models import DemoAnalysis, Match, MatchStat

    with session_factory() as s:
        for i in range(4):
            m = Match(match_id=f"pm{i}", map_name="Mirage" if i < 3 else "Ancient",
                      mode="competitive", win=True, score1=13, score2=5, demo_status="analyzed")
            s.add(m)
            s.commit()
            s.add(MatchStat(match_id=f"pm{i}", hs_rate=0.5, we=10.0))
            s.add(DemoAnalysis(match_id=f"pm{i}", schema_version="1.0",
                               payload={"pistol_rounds": with_pistol["pistol_rounds"], **ratings(80.0)},
                               parser="awpy"))
        s.commit()

    client.put("/api/settings", json={"wanmei.steam_id": "1"})
    r = client.get("/api/profile")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["real"] is True
    assert data["main_map"] == "Mirage"
    assert data["hs_rate"] == pytest.approx(0.5)
    assert data["recent_matches"] == 4
    # 瞄准 80 vs 房均 (80+50)/2=65 → +15 → A
    assert data["grades"]["瞄准能力"] == "A"
    # 硬件信息保留
    assert "dpi" in data


def test_profile_falls_back_to_seed_without_matches(client):
    r = client.get("/api/profile")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["real"] is False  # 无对局数据 → 种子画像兜底
