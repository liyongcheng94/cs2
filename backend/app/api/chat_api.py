"""AI 教练对话 API：会话 CRUD + 一轮对话。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import SessionDep
from ..services.chat_coach import chat, delete_session, list_messages, list_sessions

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatBody(BaseModel):
    session_id: int | None = None
    content: str


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
    out = await chat(body.content.strip(), body.session_id)
    if out.get("reply") is None:
        raise HTTPException(status_code=502, detail=out.get("error") or "AI 调用失败")
    return out
