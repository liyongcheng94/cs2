"""AI 教练对话：多轮会话持久化 + 上下文注入（玩家画像 + 最近复盘）+ MindVault AI 桥。"""
from __future__ import annotations

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import ChatMessage, ChatSession, PlayerProfile, Report
from .ai_client import AiError, build_ai_client, load_prompt


async def chat_stream(user_content: str, session_id: int | None = None, session_factory_fn=None, image_ids: list[int] | None = None):
    """流式对话：返回 SSE 生成器（delta/done 事件）；结束时持久化 assistant 消息。图片 OCR 同 chat()。"""
    import json as _json

    sf = session_factory_fn or session_factory
    ocr_block = ""
    if image_ids:
        from ..models import ChatImage
        from .ocr import ocr_image
        from ..config import get_data_dir

        texts = []
        with sf() as session:
            for img_id in image_ids:
                img = session.get(ChatImage, img_id)
                if img is None:
                    continue
                path = get_data_dir() / "uploads" / "chat" / str(img.id) / img.filename
                text = ocr_image(path) if path.exists() else ""
                img.ocr_text = text
                img.session_id = session_id if session_id else None
                session.add(img)
                if text:
                    texts.append(f"[图片{img_id}内容]\n{text}")
        if texts:
            ocr_block = "\n".join(texts) + "\n\n"

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
                cs.title = user_content[:20] or "新对话"
                session.add(cs)
        session.add(
            ChatMessage(
                session_id=session_id,
                role="user",
                content=user_content,
                image_ids=_json.dumps(image_ids) if image_ids else None,
            )
        )
        session.commit()

    instruction = _build_instruction()
    with sf() as session:
        history = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        ).all()
    history_text = "\n".join(f"[{m.role}] {m.content}" for m in history)
    user_payload = f"{ocr_block}[user] {user_content}" if ocr_block else history_text
    with sf() as session:
        ai = build_ai_client(session)

    async def gen():
        full: list[str] = []
        try:
            async for delta in ai.chat_stream(instruction, user_payload):
                full.append(delta)
                yield f"data: {_json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            reply = "".join(full)
            with sf() as session:
                session.add(ChatMessage(session_id=session_id, role="assistant", content=reply))
                session.commit()
            yield f"data: {_json.dumps({'done': True, 'session_id': session_id}, ensure_ascii=False)}\n\n"
        except AiError as exc:
            logger.warning(f"[AI教练] 会话 {session_id} 流式调用失败：{exc}")
            yield f"data: {_json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return gen()


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
        # 惯性死亡点（1.1）：跨场网格聚合的重复死亡区域，教练可主动点名
        from .death_patterns import death_patterns

        patterns = death_patterns(s)
        if patterns:
            desc = "；".join(
                f"{p['map_name']}({p['x']},{p['y']}) {p['count']}次/跨{p['matches_n']}场"
                for p in patterns
            )
            parts.append(f"惯性死亡点（跨场重复死亡区域）：{desc}——用户提问位置/残局问题时优先对照这些点位")
    return "\n\n".join(parts)


async def chat(
    user_content: str,
    session_id: int | None = None,
    session_factory_fn=None,
    image_ids: list[int] | None = None,
) -> dict:
    """一轮对话：存 user 消息 → 带历史调 AI → 存 assistant 回复。AI 失败仅存 user 并报错。

    image_ids 非空时：绑定图片到消息 + OCR 文本以「[图片N内容]」注入本轮上下文
    （DeepSeek 无 vision，2026-11-23 用户选型 OCR 间接路线）。
    """
    sf = session_factory_fn or session_factory
    ocr_block = ""
    if image_ids:
        from ..models import ChatImage
        from .ocr import ocr_image
        from ..config import get_data_dir

        texts = []
        with sf() as session:
            for img_id in image_ids:
                img = session.get(ChatImage, img_id)
                if img is None:
                    continue
                img.session_id = session_id if session_id else None
                path = get_data_dir() / "uploads" / "chat" / str(img.id) / img.filename
                text = ocr_image(path) if path.exists() else ""
                img.ocr_text = text
                session.add(img)
                if text:
                    texts.append(f"[图片{img_id}内容]\n{text}")
        if texts:
            ocr_block = "\n".join(texts) + "\n\n"

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
        import json as _json

        session.add(
            ChatMessage(
                session_id=session_id,
                role="user",
                content=user_content,
                image_ids=_json.dumps(image_ids) if image_ids else None,
            )
        )
        session.commit()

    instruction = _build_instruction()
    with sf() as session:
        history = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
        ).all()
    history_text = "\n".join(f"[{m.role}] {m.content}" for m in history)
    user_payload = f"{ocr_block}[user] {user_content}" if ocr_block else history_text
    try:
        with sf() as session:
            ai = build_ai_client(session)
        reply = await ai.chat(instruction, user_payload)
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
    import json as _json

    rows = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    ).all()
    return [
        {"id": r.id, "role": r.role, "content": r.content,
         "image_ids": _json.loads(r.image_ids) if r.image_ids else [],
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
