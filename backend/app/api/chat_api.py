"""AI 教练对话 API：会话 CRUD + 一轮对话 + 流式（SSE）+ 图片上传（OCR 间接路线）。"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..config import get_data_dir
from ..database import SessionDep
from ..services.chat_coach import chat, chat_stream, delete_session, list_messages, list_sessions
from ..services.ocr import ocr_image

router = APIRouter(prefix="/chat", tags=["chat"])

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMG_BYTES = 5 * 1024 * 1024  # 5MB（与 nginx client_max_body_size 10m 配合）
_EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class ChatBody(BaseModel):
    session_id: int | None = None
    content: str
    image_ids: list[int] | None = None  # 本轮携带的对话图片


def _chat_uploads_dir(image_id: int) -> Path:
    d = get_data_dir() / "uploads" / "chat" / str(image_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/images")
async def upload_images(files: list[UploadFile] = File(...), session: SessionDep = None) -> list[dict]:
    """上传对话图片（可多张）：落 data/uploads/chat/{id}/，即刻 OCR（AI 以文字间接看图）。"""
    out: list[dict] = []
    from ..models import ChatImage

    for file in files:
        if file.content_type not in _ALLOWED_MIME:
            raise HTTPException(status_code=400, detail=f"仅支持图片（jpeg/png/webp），收到 {file.content_type}")
        data = await file.read()
        if len(data) > _MAX_IMG_BYTES:
            raise HTTPException(status_code=400, detail="图片超过 5MB 限制")

        ext = Path(file.filename or "img.png").suffix.lower() or ".png"
        if ext not in _EXT_MIME:
            ext = ".png"
        img = ChatImage(filename="")
        session.add(img)
        session.commit()
        session.refresh(img)

        filename = f"{uuid.uuid4().hex}{ext}"
        target = _chat_uploads_dir(img.id) / filename
        target.write_bytes(data)
        img.filename = filename
        img.ocr_text = ocr_image(target)
        session.add(img)
        session.commit()
        session.refresh(img)
        out.append({
            "id": img.id,
            "url": f"/api/chat/uploads/{img.id}/{filename}",
            "filename": filename,
            "ocr_text": img.ocr_text,
        })
    return out


@router.get("/uploads/{image_id}/{filename}", include_in_schema=False)
def get_upload(image_id: int, filename: str) -> FileResponse:
    """下发对话图片（路径穿越校验）。"""
    base = (_chat_uploads_dir(image_id)).resolve()
    target = (base / filename).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    mime = _EXT_MIME.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=mime)


@router.post("/sessions")
def create_session(session: SessionDep) -> dict:
    from ..models import ChatSession

    cs = ChatSession()
    session.add(cs)
    session.commit()
    session.refresh(cs)
    return {"id": cs.id, "title": cs.title}


@router.get("/sessions")
def get_sessions(session: SessionDep) -> list[dict]:
    return list_sessions(session)


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: int, session: SessionDep) -> list[dict]:
    return list_messages(session, session_id)


@router.delete("/sessions/{session_id}")
def remove_session(session_id: int, session: SessionDep) -> dict:
    delete_session(session, session_id)
    return {"deleted": True}


@router.post("")
async def send_message(body: ChatBody, session: SessionDep) -> dict:
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    out = await chat(body.content.strip(), body.session_id, image_ids=body.image_ids)
    if out.get("reply") is None:
        raise HTTPException(status_code=502, detail=out.get("error") or "AI 调用失败")
    return out


@router.post("/stream")
async def stream_message(body: ChatBody, session: SessionDep) -> StreamingResponse:
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    gen = await chat_stream(body.content.strip(), body.session_id, image_ids=body.image_ids)
    return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
