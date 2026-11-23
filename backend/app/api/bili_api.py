"""B站内容查询 API：视频总结列表 / 道具库（按地图/道具类型筛选）。"""
from __future__ import annotations

import shutil
import uuid as uuid_mod
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import select

from ..config import get_data_dir
from ..database import SessionDep
from ..models import BiliVideo, GrenadeCard, GrenadeCardImage, VideoSummary

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
            "zone": r.zone,
            "favorited": bool(r.favorited),
        })
    return out


@router.patch("/grenades/{card_id}/favorite")
def patch_favorite(card_id: int, body: dict, session: SessionDep) -> dict:
    """收藏/取消收藏（grill-me v2 决策 1d：★角标 + 收藏置顶）。"""
    card = session.get(GrenadeCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="道具卡不存在")
    card.favorited = bool(body.get("favorited"))
    session.add(card)
    session.commit()
    return {"id": card.id, "favorited": card.favorited}


# ---- 道具卡贴图（grill-me v2 决策 1a-1c：用户手传多图，存 data/uploads/{card_id}/） ----

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMG_BYTES = 5 * 1024 * 1024  # 5MB（与 nginx client_max_body_size 10m 配合）


def _uploads_dir(card_id: int) -> Path:
    d = get_data_dir() / "uploads" / str(card_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# 扩展名 → MIME（下发时按扩展名给正确 Content-Type）
_EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _serve_image(card_id: int, filename: str) -> FileResponse:
    # 路径穿越校验：resolve 后必须仍在 uploads/{card_id} 内
    base = (_uploads_dir(card_id)).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    mime = _EXT_MIME.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=mime)


@router.get("/uploads/{card_id}/{filename}", include_in_schema=False)
def get_upload(card_id: int, filename: str):
    """上传图下发（决策 1b：API 路由而非 StaticFiles mount）。"""
    return _serve_image(card_id, filename)


@router.get("/grenades/{card_id}/images")
def list_images(card_id: int, session: SessionDep) -> list[dict]:
    if session.get(GrenadeCard, card_id) is None:
        raise HTTPException(status_code=404, detail="道具卡不存在")
    rows = session.exec(
        select(GrenadeCardImage).where(GrenadeCardImage.card_id == card_id).order_by(GrenadeCardImage.id)
    ).all()
    return [
        {"id": r.id, "filename": r.filename, "url": f"/api/bili/uploads/{card_id}/{r.filename}"}
        for r in rows
    ]


@router.post("/grenades/{card_id}/images")
async def upload_images(card_id: int, files: list[UploadFile], session: SessionDep) -> list[dict]:
    """多图上传（≤9 张/卡，单文件 ≤5MB，MIME 白名单 jpg/png/webp）。"""
    card = session.get(GrenadeCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="道具卡不存在")

    existing = session.exec(
        select(GrenadeCardImage).where(GrenadeCardImage.card_id == card_id)
    ).all()
    if len(existing) + len(files) > 9:
        raise HTTPException(status_code=400, detail="每卡最多 9 张图")

    out: list[dict] = []
    updir = _uploads_dir(card_id)
    for f in files:
        ctype = (f.content_type or "").lower()
        if ctype not in _ALLOWED_MIME:
            raise HTTPException(status_code=400, detail=f"不支持的类型 {ctype}，仅 jpg/png/webp")
        data = await f.read()
        if len(data) > _MAX_IMG_BYTES:
            raise HTTPException(status_code=400, detail="单图最大 5MB")
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[ctype]
        fname = f"{uuid_mod.uuid4().hex}{suffix}"
        (updir / fname).write_bytes(data)
        row = GrenadeCardImage(card_id=card_id, filename=fname)
        session.add(row)
        session.commit()
        session.refresh(row)
        out.append({"id": row.id, "filename": fname, "url": f"/api/bili/uploads/{card_id}/{fname}"})
    return out


@router.delete("/grenades/{card_id}/images/{image_id}")
def delete_image(card_id: int, image_id: int, session: SessionDep) -> dict:
    """删图：文件 + 行同删。"""
    row = session.get(GrenadeCardImage, image_id)
    if row is None or row.card_id != card_id:
        raise HTTPException(status_code=404, detail="图片不存在")
    f = _uploads_dir(card_id) / row.filename
    if f.is_file():
        f.unlink()
    session.delete(row)
    session.commit()
    return {"deleted": image_id}
