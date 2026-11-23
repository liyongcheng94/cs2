"""AI 教练对话 API：会话 CRUD + 一轮对话 + 流式（SSE）+ 图片上传（OCR 间接路线）。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..config import get_data_dir
from ..database import SessionDep
from ..models import ChatSession
from sqlmodel import select
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


class BindImageItem(BaseModel):
    image_id: int
    message_index: int  # 会话内消息顺序（0-based）


class BindImagesBody(BaseModel):
    session_id: int
    bindings: list[BindImageItem]


@router.post("/import/bind-images")
async def import_bind_images(body: BindImagesBody, session: SessionDep) -> dict:
    """导入后补绑图片：把已上传（/chat/images）的图片绑定到会话内第 N 条消息。幂等（重复绑覆盖同值）。"""
    from ..models import ChatImage, ChatMessage

    bound = 0
    for b in body.bindings:
        msgs = session.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == body.session_id)
            .order_by(ChatMessage.id)
        ).all()
        if b.message_index < 0 or b.message_index >= len(msgs):
            raise HTTPException(status_code=400, detail=f"message_index {b.message_index} 越界（共 {len(msgs)} 条）")
        img = session.get(ChatImage, b.image_id)
        if img is None:
            raise HTTPException(status_code=404, detail=f"image {b.image_id} 不存在")
        msg = msgs[b.message_index]
        ids = json.loads(msg.image_ids) if msg.image_ids else []
        if b.image_id not in ids:
            ids.append(b.image_id)
        msg.image_ids = json.dumps(ids)
        img.session_id = body.session_id
        session.add(msg)
        session.add(img)
        bound += 1
    session.commit()
    return {"bound": bound}


class ImportMessage(BaseModel):
    role: str
    content: str
    images: list[str] | None = None  # 图片 URL（导入时下载存 ChatImage）


class ImportBody(BaseModel):
    title: str
    share_key: str  # 幂等键（DeepSeek 分享 id）
    messages: list[ImportMessage]


def _download_image(url: str, timeout: float = 30.0, headers: dict | None = None) -> bytes | None:
    """下载图片字节；失败返回 None（导入不阻断）。"""
    try:
        import httpx

        resp = httpx.get(url, timeout=timeout, headers=headers or {}, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


@router.post("/import")
async def import_conversation(body: ImportBody, session: SessionDep) -> dict:
    """导入外部对话（DeepSeek 分享页等）：新建会话 + 逐条落消息；图片下载绑定 image_ids；同 share_key 幂等。"""
    from ..models import ChatImage, ChatMessage

    # 幂等：同 share_key 已导入过 → 直接返回既有会话
    existing = session.exec(
        select(ChatSession).where(ChatSession.import_key == body.share_key)
    ).first()
    if existing is not None:
        return {"session_id": existing.id, "imported": 0, "images_downloaded": 0}

    cs = ChatSession(title=body.title[:40] or "导入对话", import_key=body.share_key)
    session.add(cs)
    session.commit()
    session.refresh(cs)

    imported = 0
    downloaded = 0
    for m in body.messages:
        image_ids: list[int] = []
        for url in m.images or []:
            data = _download_image(url, headers={"User-Agent": "Mozilla/5.0 (CS2HQ import)"})
            if data is None:
                continue
            ctype = "image/webp" if url.lower().endswith(".webp") or "webp" in url else "image/png"
            if ctype not in _ALLOWED_MIME:
                ctype = "image/png"
            ext = ".webp" if ctype == "image/webp" else ".png"
            img = ChatImage(filename="", session_id=cs.id)
            session.add(img)
            session.commit()
            session.refresh(img)
            filename = f"{uuid.uuid4().hex}{ext}"
            (_chat_uploads_dir(img.id) / filename).write_bytes(data)
            img.filename = filename
            img.ocr_text = ocr_image(_chat_uploads_dir(img.id) / filename)
            session.add(img)
            session.commit()
            session.refresh(img)
            image_ids.append(img.id)
            downloaded += 1
        session.add(
            ChatMessage(
                session_id=cs.id,
                role=m.role if m.role in ("user", "assistant") else "user",
                content=m.content,
                image_ids=json.dumps(image_ids) if image_ids else None,
            )
        )
        imported += 1
    session.commit()
    return {"session_id": cs.id, "imported": imported, "images_downloaded": downloaded}


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
