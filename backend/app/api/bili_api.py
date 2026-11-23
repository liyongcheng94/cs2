"""B站内容查询 API：视频总结列表 / 道具库（按地图/道具类型筛选）。"""
from __future__ import annotations

from fastapi import APIRouter
from sqlmodel import select

from ..database import SessionDep
from ..models import BiliVideo, GrenadeCard, VideoSummary

router = APIRouter(prefix="/bili", tags=["bili"])


@router.get("/videos")
def list_videos(session: SessionDep) -> list[dict]:
    """已学视频列表（卡片墙用）：联 VideoSummary 总结 + raw 封面/时长。"""
    rows = session.exec(select(BiliVideo).order_by(BiliVideo.created_at.desc())).all()
    summaries = {s.bvid: s for s in session.exec(select(VideoSummary)).all()}
    out = []
    for r in rows:
        raw = r.raw or {}
        s_row = summaries.get(r.bvid)
        out.append({
            "bvid": r.bvid,
            "title": r.title,
            "owner": r.owner,
            "subtitle_status": r.subtitle_status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            # grill-me 决策 A：总结本地可读；cover/duration 供卡片墙渲染
            "summary_md": s_row.summary_md if s_row else None,
            "cover": raw.get("cover") or None,
            "duration": raw.get("duration") or None,
        })
    return out


@router.get("/grenades")
def list_grenades(session: SessionDep, map_name: str = "", grenade_type: str = "") -> list[dict]:
    stmt = select(GrenadeCard).order_by(GrenadeCard.created_at.desc())
    rows = session.exec(stmt).all()
    out = []
    for r in rows:
        if map_name and (r.map_name or "").lower() != map_name.lower():
            continue
        if grenade_type and (r.grenade_type or "").lower() != grenade_type.lower():
            continue
        out.append({
            "id": r.id,
            "map_name": r.map_name,
            "point": r.point,
            "grenade_type": r.grenade_type,
            "stance": r.stance,
            "timing": r.timing,
            "video_ts": r.video_ts,
            "bvid": r.bvid,
            "content_md": r.content_md,
        })
    return out
