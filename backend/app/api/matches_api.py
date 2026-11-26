from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from ..database import SessionDep, session_factory
from .auth_api import CurrentUser
from ..models import User
from ..models import DemoAnalysis, Match, MatchStat, Report, SeasonStats
from ..services.wanmei import WanmeiAuthError, WanmeiError


# 完美平台中文地图名 → 英文 ID（雷达底图用）
MAP_NAME_EN = {
    "荒漠迷城": "de_mirage",
    "炙热沙城Ⅱ": "de_dust2",
    "炙热沙城": "de_dust2",
    "炼狱小镇": "de_inferno",
    "核子危机": "de_nuke",
    "远古遗迹": "de_ancient",
    "阿努比斯": "de_anubis",
    "殒命大厦": "de_vertigo",
    "死亡游乐园": "de_overpass",
    "列车停放站": "de_train",
}

router = APIRouter(prefix="/matches", tags=["matches"])


def _scoped(stmt, user: User):
    """数据隔离：admin 看全部（含 legacy 无主行）；普通用户只看自己的行。"""
    if user.is_admin:
        return stmt
    return stmt.where(Match.user_id == user.id)


@router.get("/stats/season")
def season_stats(session: SessionDep) -> dict:
    """赛季统计快照（趋势/雷达/热图数据源）。"""
    row = session.exec(
        select(SeasonStats).order_by(SeasonStats.updated_at.desc())
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="尚未同步赛季统计（先执行完美平台同步）")
    return {"season_id": row.season_id, "data": row.payload, "updated_at": row.updated_at.isoformat()}


@router.get("/stats/trends")
def stats_trends(session: SessionDep, user: CurrentUser) -> dict:
    """长期追踪（1.1）：逐场聚合点（rating/adr/经济/道具指标）+ 地图胜率。"""
    matches = session.exec(_scoped(select(Match).order_by(Match.played_at.desc()), user)).all()
    stats = {s.match_id: s for s in session.exec(select(MatchStat)).all()}
    analyses = {a.match_id: a.payload or {} for a in session.exec(select(DemoAnalysis)).all()}

    points: list[dict] = []
    by_map: dict[str, dict] = {}
    for m in matches:
        stat = stats.get(m.match_id)
        payload = analyses.get(m.match_id, {})
        map_en = MAP_NAME_EN.get(m.map_name, "")
        points.append({
            "match_id": m.match_id,
            "played_at": m.played_at.isoformat() if m.played_at else None,
            "map_name": m.map_name,
            "map_en": map_en,
            "win": m.win,
            "rating": stat.rating if stat else None,
            "adr": stat.adr if stat else None,
            "hs_rate": stat.hs_rate if stat else None,
            "utility": payload.get("utility"),
            "economy": payload.get("economy"),
        })
        if not map_en:
            continue
        bucket = by_map.setdefault(map_en, {"map_en": map_en, "map_name": m.map_name, "games": 0, "wins": 0})
        bucket["games"] += 1
        if m.win:
            bucket["wins"] += 1
    for bucket in by_map.values():
        bucket["win_rate"] = round(bucket["wins"] / bucket["games"], 3) if bucket["games"] else None
    return {"points": points, "by_map": list(by_map.values())}


@router.get("")
def list_matches(session: SessionDep, user: CurrentUser) -> list[dict]:
    stmt = _scoped(select(Match).order_by(Match.played_at.desc()), user)
    return [
        {
            "id": m.id,
            "match_id": m.match_id,
            "map_name": m.map_name,
            "score1": m.score1,
            "score2": m.score2,
            "win": m.win,
            "draw": (m.raw or {}).get("winTeam") == -1,  # 平局口径实测：winTeam=-1（2026-11-23）
            "map_en": MAP_NAME_EN.get(m.map_name, ""),
            "mode": m.mode,
            "played_at": m.played_at.isoformat() if m.played_at else None,
            "demo_status": m.demo_status,
        }
        for m in session.exec(stmt).all()
    ]


@router.get("/{match_id}")
def get_match(match_id: int, session: SessionDep, user: CurrentUser) -> dict:
    match = session.get(Match, match_id)
    if match is None or not (user.is_admin or match.user_id in (user.id, None)):
        raise HTTPException(status_code=404, detail="对局不存在")
    stat = session.exec(select(MatchStat).where(MatchStat.match_id == match.match_id)).first()
    analysis = session.exec(
        select(DemoAnalysis).where(DemoAnalysis.match_id == match.match_id)
    ).first()
    report = session.exec(select(Report).where(Report.match_id == match.match_id)).first()
    return {
        "match": {
            "id": match.id,
            "match_id": match.match_id,
            "map_name": match.map_name,
            "score1": match.score1,
            "score2": match.score2,
            "win": match.win,
            "mode": match.mode,
            "played_at": match.played_at.isoformat() if match.played_at else None,
            "demo_status": match.demo_status,
            "player_id": (match.raw or {}).get("playerId"),
        },
        "stat": stat.model_dump(exclude={"raw"}) if stat else None,
        "analysis": analysis.payload if analysis else None,
        "report": {"title": report.title, "pushed": report.pushed} if report else None,
    }


@router.get("/{match_id}/detail-v1")
async def match_detail_v1(match_id: int, session: SessionDep, user: CurrentUser) -> dict:
    """全场详细数据（v1 端点：双方 10 人 KAST/伤害/首杀/补枪/道具效果/命中率）；结果缓存进 Match.detail_json。"""
    match = session.get(Match, match_id)
    if match is None or not (user.is_admin or match.user_id in (user.id, None)):
        raise HTTPException(status_code=404, detail="对局不存在")
    if match.detail_json:
        return match.detail_json

    from ..services.wanmei_sync import build_api_from_settings

    try:
        with session_factory() as s:
            api = build_api_from_settings(s)
        data = await api.match_detail_v1(match.match_id)
    except WanmeiAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except WanmeiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    match.detail_json = data
    session.add(match)
    session.commit()
    return data


@router.get("/{match_id}/report-md")
def match_report_md(match_id: int, session: SessionDep, user: CurrentUser) -> dict:
    """复盘 Markdown 内容（AI 复盘 Tab 数据源）。"""
    match = session.get(Match, match_id)
    if match is None or not (user.is_admin or match.user_id in (user.id, None)):
        raise HTTPException(status_code=404, detail="对局不存在")
    report = session.exec(select(Report).where(Report.match_id == match.match_id)).first()
    if report is None:
        raise HTTPException(status_code=404, detail="尚未生成复盘")
    return {"title": report.title, "content_md": report.content_md, "degraded": report.degraded, "pushed": report.pushed}
