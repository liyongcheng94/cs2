"""AI 教练对话：多轮会话持久化 + 上下文注入（玩家画像 + 最近复盘）+ MindVault AI 桥。"""
from __future__ import annotations

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import ChatMessage, ChatSession, PlayerProfile, Report
from .ai_client import AiError, build_ai_client, load_prompt


def _build_instruction() -> str:
    """注入玩家画像 + 最近复盘（教练答的是'你'，不是通用攻略）。"""
    parts = [load_prompt("coach") or "你是用户的专属 CS2 教练，回答具体、可执行、不套话，中文。"]
    with session_factory() as s:
        prof = s.get(PlayerProfile, "baseline")
        if prof is not None:
            d = prof.data
            parts.append(
                f"玩家画像：eDPI≈{d.get('edpi')}，主玩 {d.get('main_map')}，"
                f"等级 {d.get('grades')}，爆头率 {d.get('hs_rate')}，来源：{d.get('source')}"
            )
        recent = s.exec(select(Report).order_by(Report.created_at.desc()).limit(3)).all()
        if recent:
            titles = "；".join(r.title for r in recent)
            parts.append(f"最近的复盘笔记：{titles}（用户追问战绩细节时可引用其数据口径）")
    return "\n\n".join(parts)


async def chat(user_content: str, session_id: int | None = None, session_factory_fn=None) -> dict:
    """一轮对话：存 user 消息 → 带历史调 AI → 存 assistant 回复。AI 失败仅存 user 并报错。"""
    sf = session_factory_fn or session_factory
    with sf() as session:
        if session_id is None:
            cs = ChatSession(title=user_content[:20] or "新对话")
            session.add(cs)
            session.commit()
            session.refresh(cs)
            session_id = cs.id
        else:
            cs = session.get(ChatSession, session_id)
            if cs is not None and cs.title == "新对话":
                cs.title = user_content[:20] or "新对话"  # 首句自动作标题
                session.add(cs)
        session.add(ChatMessage(session_id=session_id, role="user", content=user_content))
        session.commit()

    instruction = _build_instruction()
    with sf() as session:
        history = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        ).all()
    history_text = "\n".join(f"[{m.role}] {m.content}" for m in history)
    try:
        with sf() as session:
            ai = build_ai_client(session)
        reply = await ai.chat(instruction, history_text)
    except AiError as exc:
        logger.warning(f"[AI教练] 会话 {session_id} 调用失败：{exc}")
        return {"session_id": session_id, "reply": None, "error": str(exc)}

    with sf() as session:
        session.add(ChatMessage(session_id=session_id, role="assistant", content=reply))
        session.commit()
    return {"session_id": session_id, "reply": reply, "error": None}


def list_sessions(session: Session) -> list[dict]:
    rows = session.exec(select(ChatSession).order_by(ChatSession.created_at.desc())).all()
    return [{"id": r.id, "title": r.title, "created_at": r.created_at.isoformat()} for r in rows]


def list_messages(session: Session, session_id: int) -> list[dict]:
    rows = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    ).all()
    return [
        {"id": r.id, "role": r.role, "content": r.content,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


def delete_session(session: Session, session_id: int) -> None:
    for m in session.exec(select(ChatMessage).where(ChatMessage.session_id == session_id)).all():
        session.delete(m)
    cs = session.get(ChatSession, session_id)
    if cs is not None:
        session.delete(cs)
    session.commit()
