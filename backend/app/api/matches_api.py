from fastapi import APIRouter, HTTPException
from sqlmodel import select

from ..database import SessionDep
from ..models import DemoAnalysis, Match, MatchStat, Report, SeasonStats

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("/stats/season")
def season_stats(session: SessionDep) -> dict:
    """赛季统计快照（趋势/雷达/热图数据源）。"""
    row = session.exec(
        select(SeasonStats).order_by(SeasonStats.updated_at.desc())
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="尚未同步赛季统计（先执行完美平台同步）")
    return {"season_id": row.season_id, "data": row.payload, "updated_at": row.updated_at.isoformat()}


@router.get("")
def list_matches(session: SessionDep) -> list[dict]:
    stmt = select(Match).order_by(Match.played_at.desc())
    return [
        {
            "id": m.id,
            "match_id": m.match_id,
            "map_name": m.map_name,
            "score1": m.score1,
            "score2": m.score2,
            "win": m.win,
            "mode": m.mode,
            "played_at": m.played_at.isoformat() if m.played_at else None,
            "demo_status": m.demo_status,
        }
        for m in session.exec(stmt).all()
    ]


@router.get("/{match_id}")
def get_match(match_id: int, session: SessionDep) -> dict:
    match = session.get(Match, match_id)
    if match is None:
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
        },
        "stat": stat.model_dump(exclude={"raw"}) if stat else None,
        "analysis": analysis.payload if analysis else None,
        "report": {"title": report.title, "pushed": report.pushed} if report else None,
    }
