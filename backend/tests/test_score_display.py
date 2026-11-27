# 场景（BDD）：对局列表比分与时间显示口径
# 背景：完美 API 的 score1/score2 = 队1/队2 的分，我方队伍号在 raw.team（1 或 2），
#       胜负以 win 列为权威。历史教训：score1 不一定是我方分。
# 场景1：我方是队2（team=2）时，API 返回 my_score=score2 / opponent_score=score1
# 场景2：我方是队1（team=1）时，API 返回 my_score=score1 / opponent_score=score2
# 场景3：raw 缺 team（legacy）时，用 win+比分推断：win=False 且 score1>score2 → my=score2
# 场景4：upsert_match 后 raw 里保留 team 字段，win 以 winTeam==team 判定
import pytest
from sqlmodel import Session, select

from app.database import get_engine
from app.models import Match
from app.services.wanmei_sync import upsert_match


def _raw(match_id, team, score1, score2, win_team):
    return {
        "matchId": match_id,
        "mapName": "荒漠迷城",
        "score1": score1,
        "score2": score2,
        "team": team,
        "winTeam": win_team,
        "mode": 2,
        "startTime": "2026-11-26 20:47:52",
    }


def _login(client):
    resp = client.post("/api/auth/login", json={"username": "testadmin", "password": "pw123456"})
    assert resp.status_code == 200, resp.text
    return resp.cookies.get("cs2hq_token")


def _api(client, match_id):
    cookie = _login(client)
    resp = client.get("/api/matches?limit=50", headers={"Cookie": f"cs2hq_token={cookie}"})
    assert resp.status_code == 200, resp.text
    for m in resp.json():
        if m["match_id"] == match_id:
            return m
    return None


def _upsert(raw, owner=1):
    s = Session(get_engine())
    m = upsert_match(s, raw, "76561198929200000", owner_user_id=owner)
    s.add(m)
    s.commit()
    return m


def test_team2_my_score_is_score2(client):
    """场景1：我方队2，比分 3:13 且 winTeam=2 → 我胜，my_score=13。"""
    _upsert(_raw("PVP@sd_t2", 2, 3, 13, 2))
    m = _api(client, "PVP@sd_t2")
    assert m is not None
    assert m["win"] is True
    assert m["my_score"] == 13
    assert m["opponent_score"] == 3


def test_team1_my_score_is_score1(client):
    """场景2：我方队1，比分 13:7 且 winTeam=1 → 我胜，my_score=13。"""
    _upsert(_raw("PVP@sd_t1", 1, 13, 7, 1))
    m = _api(client, "PVP@sd_t1")
    assert m["win"] is True
    assert m["my_score"] == 13
    assert m["opponent_score"] == 7


def test_legacy_missing_team_infers_from_win(client):
    """场景3：无 raw.team 的 legacy 行（score1=13 score2=3 win=False）→ 推断 my=score2=3。"""
    s = Session(get_engine())
    s.add(Match(match_id="PVP@sd_legacy", map_name="荒漠迷城", score1=13, score2=3, win=False, raw={}))
    s.commit()
    row = _api(client, "PVP@sd_legacy")
    assert row["my_score"] == 3
    assert row["opponent_score"] == 13


def test_upsert_keeps_team_in_raw(client):
    """场景4：upsert 后 raw 里保留 team 字段。"""
    m = _upsert(_raw("PVP@sd_raw", 2, 4, 13, 2))
    s = Session(get_engine())
    m2 = s.exec(select(Match).where(Match.match_id == "PVP@sd_raw")).first()
    assert m2 is not None and m2.raw.get("team") == 2
    assert m2.win is True
