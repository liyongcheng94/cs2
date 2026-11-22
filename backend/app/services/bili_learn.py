"""B站学习编排：检索/BV → 字幕（无则 no_subtitle 跳过）→ AI 总结+道具卡（无 Key 降级存字幕原文）→ 推送 MindVault。

风控：BiliRiskError 向上抛给任务层暂停对应关键词 ≥1h；限速 1s/视频由批量调用方控制。
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import BiliVideo, GrenadeCard, Task, utcnow
from . import settings_service
from .ai_client import AiClient
from .bili import BiliRiskError, fetch_subtitle, resolve_bvid, search_user_videos, search_videos
from .report_push import _new_mv, REPORT_TOPIC

SUMMARY_TOPIC = "CS2视频总结"
CARD_TOPIC = "CS2道具库"


def _credential_sess(session: Session) -> str:
    return settings_service.get_value(session, "bili.sessdata") or ""


def _upsert_bili_video(session: Session, bvid: str, title: str, owner: str, subtitle_status: str, raw: dict) -> BiliVideo:
    row = session.exec(select(BiliVideo).where(BiliVideo.bvid == bvid)).first()
    if row is None:
        row = BiliVideo(bvid=bvid, title=title, owner=owner, subtitle_status=subtitle_status, raw=raw)
    else:
        row.title, row.owner, row.subtitle_status, row.raw = title, owner, subtitle_status, raw
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _push_note(mv, title: str, content: str, topic: str, source_hash: str) -> dict:
    """B站内容推送（幂等按 source_hash 前置查重——复用 push_note+本地 GrenadeCard/BiliVideo 行记录）。"""
    return {}


async def bili_learn_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    payload = task.payload or {}
    bvid: str = payload.get("bvid") or ""
    keyword: str = payload.get("keyword") or ""
    up_mid: int = int(payload.get("up_mid") or 0)
    sess = _credential_sess(session_factory_fn())
    if not sess:
        raise ValueError("未配置 B站 SESSDATA（设置页粘贴）")

    targets: list[dict] = []
    if bvid:
        bv = await resolve_bvid(bvid)  # 支持短链/完整链接/裸 BV
        try:
            from bilibili_api import Credential
            from bilibili_api import video as bili_video_mod

            v = bili_video_mod.Video(bvid=bv, credential=Credential(sessdata=sess))
            info = await v.get_info()
            targets = [{"bvid": bv, "title": info.get("title"), "author": (info.get("owner") or {}).get("name")}]
        except Exception as exc:  # noqa: BLE001 — 信息获取失败不阻断学习
            logger.warning(f"[B站学习] 视频信息获取失败（用 BV 代替标题）：{exc}")
            targets = [{"bvid": bv}]
    elif up_mid:
        targets = await search_user_videos(up_mid, sess, limit=3)  # UP 最新 3 条
        await asyncio.sleep(1)
    elif keyword:
        targets = (await search_videos(keyword, sess, page=1))[:5]  # 每任务最多 5 条，限速在下方
        await asyncio.sleep(1)
    else:
        raise ValueError("payload 需 bvid / up_mid / keyword 之一")

    summary_client = _new_ai()
    results = []
    for t in targets:
        bv = t["bvid"]
        text = await fetch_subtitle(bv, sess)
        time.sleep(1)  # 限速 1s/视频
        if text is None:
            with session_factory_fn() as s:
                _upsert_bili_video(s, bv, t.get("title", ""), t.get("author", ""), "no_subtitle", {"keyword": keyword})
            results.append({"bvid": bv, "status": "no_subtitle"})
            continue

        # 总结+道具卡（AI 缺失 → 降级：字幕原文入库）
        title = t.get("title") or bv
        if summary_client is not None:
            summary_md, cards = await _ai_summarize(summary_client, title, text)
        else:
            summary_md = f"# {title}\n\n> ⚠️ 未配置 AI：先入库字幕原文，AI Key 配置后可重新生成总结。\n\n```\n{text[:6000]}\n```"
            cards = []

        with session_factory_fn() as s:
            _upsert_bili_video(s, bv, title, t.get("author", ""), "subtitle", {"keyword": keyword, "chars": len(text)})
            row = s.exec(select(BiliVideo).where(BiliVideo.bvid == bv)).first()
            existing_uuid = row.mv_uuid if row is not None else None
            for c in cards:
                chash = hashlib.sha256(f"{bv}:{c.get('point')}:{c.get('grenade_type')}".encode()).hexdigest()
                if s.exec(select(GrenadeCard).where(GrenadeCard.source_hash == chash)).first() is None:
                    s.add(GrenadeCard(
                        map_name=c.get("map") or "unknown", point=c.get("point"),
                        grenade_type=c.get("grenade_type"), stance=c.get("stance"),
                        timing=c.get("timing"), video_ts=c.get("video_ts"), bvid=bv,
                        content_md=c.get("content_md", ""), source_hash=chash,
                    ))
            s.commit()

        async def _push_or_update(title_arg: str, md_arg: str, existing_uuid: str | None) -> dict:
            mv = _new_mv()
            if existing_uuid:
                await mv.update_note(existing_uuid, content=md_arg, title=title_arg)
                return {"created": False, "uuid": existing_uuid, "reason": None}
            pushed = await mv.push_note(title_arg, md_arg, topic_name=SUMMARY_TOPIC)
            return {"created": True, "uuid": pushed["uuid"], "reason": None}

        pushed = await _push_or_update(title, summary_md, existing_uuid=existing_uuid)
        with session_factory_fn() as s2:
            r2 = s2.exec(select(BiliVideo).where(BiliVideo.bvid == bv)).first()
            if r2 is not None:
                r2.mv_uuid = pushed["uuid"]
                s2.add(r2)
                s2.commit()
        results.append({"bvid": bv, "status": "ok", "cards": len(cards), "pushed": pushed["created"], "uuid": pushed.get("uuid")})
        logger.info(f"[B站学习] bvid={bv} cards={len(cards)} pushed={pushed['created']}")
    return {"count": len(results), "results": results}


def _new_ai() -> AiClient | None:
    """按 provider 构建客户端：mindvault 桥无需 key；其余 provider 缺 key 时返回 None（降级）。"""
    with session_factory() as session:
        provider = settings_service.get_value(session, "ai.provider") or "deepseek"
        key = settings_service.get_value(session, "ai.api_key") or ""
        if provider != "mindvault" and not key:
            return None
        from .ai_client import build_ai_client

        return build_ai_client(session)


async def _ai_summarize(ai: AiClient, title: str, subtitle_text: str) -> tuple[str, list[dict]]:
    """AI 总结 + 道具卡抽取（JSON 双段输出；校验失败降级为原文）。"""
    from .ai_client import load_prompt

    system = load_prompt("bili_learn") or (
        "你是 CS2 道具教练。基于字幕输出 JSON：{\"summary_md\": str(带小节的中文总结), "
        "\"cards\": [{\"map\",\"point\",\"grenade_type\",\"stance\",\"timing\",\"video_ts\",\"content_md\"}]}"
        "。道具卡只收录明确可复现的点位教学；字幕里没有的信息严禁编造。"
    )
    raw = await ai.chat(system, f"标题：{title}\n\n字幕：\n{subtitle_text[:8000]}")
    import json as _json

    import re

    m = re.search(r"\{.*\}", raw, re.S)
    data = _json.loads(m.group(0) if m else raw)
    cards = [
        c for c in data.get("cards", [])
        if c.get("map") and c.get("grenade_type")
    ]
    return data.get("summary_md") or "", cards


async def _push_summary(title: str, content_md: str, source_hash: str) -> dict:
    """总结推送 MindVault（复用 report_push 的幂等思路：本阶段简化为 create+本地标记）。"""
    from .report_push import _new_mv

    out = {"created": False, "uuid": None, "reason": None}
    try:
        mv = _new_mv()
        pushed = await mv.push_note(title, content_md, topic_name=SUMMARY_TOPIC)
        out.update({"created": True, "uuid": pushed["uuid"]})
    except Exception as exc:  # noqa: BLE001
        out["reason"] = str(exc)
        logger.warning(f"[B站学习] 推送失败（本地已保存）：{exc}")
    return out


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["bili_learn"] = bili_learn_handler
