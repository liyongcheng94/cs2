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
from ..models import BiliVideo, GrenadeCard, Task, VideoSummary, utcnow
from . import settings_service
from .ai_client import AiClient
from .bili import (
    BiliRiskError,
    fetch_subtitle_timed,
    fetch_video_meta,
    format_timed_subtitle,
    resolve_bvid,
    search_user_videos,
    search_videos,
)
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


def _upsert_video_summary(session: Session, bvid: str, summary_md: str, model: str | None) -> VideoSummary:
    """总结本地落库（grill-me 决策 A）：按 bvid 幂等更新，CS2HQ 自站可看不依赖 MV。"""
    row = session.exec(select(VideoSummary).where(VideoSummary.bvid == bvid)).first()
    if row is None:
        row = VideoSummary(bvid=bvid, summary_md=summary_md, model=model)
    else:
        row.summary_md, row.model = summary_md, model
        row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _push_note(mv, title: str, content: str, topic: str, source_hash: str) -> dict:
    """B站内容推送（幂等按 source_hash 前置查重——复用 push_note+本地 GrenadeCard/BiliVideo 行记录）。"""
    return {}


# CS2 相关性判定：游戏名/地图名/战术道具词白名单（2026-11-23 实测修复：
# 「持械入宋」等剧集解说混进关键词检索结果被学习+推送）
_CS2_TOKENS = (
    "cs2", "cs:go", "csgo", "counter-strike", "反恐精英",
    "dust2", "de_dust", "mirage", "inferno", "nuke", "ancient", "anubis",
    "train", "vertigo", "overpass", "cache", "office", "炼狱小镇",
    "荒漠迷城", "炙热沙城", "死亡游乐园", "殒命大厦", "远古遗迹", "列车停放站",
    "道具", "烟雾弹", "闪光弹", "燃烧弹", "烟雾", "手雷", "雷点", "点位",
    "爆弹", "假打", "rush", "eco", "急停", "压枪", "爆头", "对枪", "架枪",
    "peek", "拉枪线", "身位", "拆弹", "下包", "残局", "身法", "跳台",
)


def _looks_like_cs2_video(title: str | None) -> bool:
    """标题含 CS2 游戏名、地图名或战术道具语义词才视为相关（无标题一律不相关）。"""
    if not title:
        return False
    low = title.lower()
    return any(tok in low for tok in _CS2_TOKENS)


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
            targets = [{"bvid": bv, "title": info.get("title"), "author": (info.get("owner") or {}).get("name"), "pubdate": info.get("pubdate")}]
        except Exception as exc:  # noqa: BLE001 — 信息获取失败不阻断学习
            logger.warning(f"[B站学习] 视频信息获取失败（用 BV 代替标题）：{exc}")
            targets = [{"bvid": bv}]
    elif up_mid:
        targets = await search_user_videos(up_mid, sess, limit=3)  # UP 最新 3 条
        await asyncio.sleep(1)
    elif keyword:
        hits = await search_videos(keyword, sess, page=1)  # 每任务最多 5 条，限速在下方
        targets = [t for t in hits if _looks_like_cs2_video(t.get("title"))][:5]
        skipped = len(hits) - len(targets)
        if skipped > 0:
            logger.info(f"[B站学习] keyword={keyword!r} 相关性过滤剔除 {skipped} 条无关视频")
        await asyncio.sleep(1)
    else:
        raise ValueError("payload 需 bvid / up_mid / keyword 之一")

    summary_client = _new_ai()
    results = []
    for t in targets:
        bv = t["bvid"]
        text = await fetch_subtitle_timed(bv, sess)
        time.sleep(1)  # 限速 1s/视频
        if text is None:
            with session_factory_fn() as s:
                _upsert_bili_video(s, bv, t.get("title", ""), t.get("author", ""), "no_subtitle", {"keyword": keyword})
            results.append({"bvid": bv, "status": "no_subtitle"})
            continue
        subtitle_text = format_timed_subtitle(text)

        # 总结+道具卡（AI 缺失 → 降级：字幕原文入库）
        title = t.get("title") or bv
        if summary_client is not None:
            summary_md, cards = await _ai_summarize(summary_client, title, subtitle_text)
            summary_model = getattr(summary_client, "model", None)
        else:
            summary_md = f"# {title}\n\n> ⚠️ 未配置 AI：先入库字幕原文，AI Key 配置后可重新生成总结。\n\n```\n{subtitle_text[:6000]}\n```"
            cards = []
            summary_model = None

        # 封面/时长元数据（grill-me 决策 C：学习时顺手抓，零额外请求）
        meta = await fetch_video_meta(bv, sess)

        with session_factory_fn() as s:
            _upsert_bili_video(s, bv, title, t.get("author", ""), "subtitle", {"keyword": keyword, "chars": len(subtitle_text), **(meta or {})})
            _upsert_video_summary(s, bv, summary_md, summary_model)
            row = s.exec(select(BiliVideo).where(BiliVideo.bvid == bv)).first()
            existing_uuid = row.mv_uuid if row is not None else None
            video_pubdate = t.get("pubdate")
            for c in cards:
                chash = hashlib.sha256(f"{bv}:{c.get('point')}:{c.get('grenade_type')}".encode()).hexdigest()
                if s.exec(select(GrenadeCard).where(GrenadeCard.source_hash == chash)).first() is None:
                    s.add(GrenadeCard(
                        map_name=c.get("map") or "unknown", point=c.get("point"),
                        grenade_type=c.get("grenade_type"), stance=c.get("stance"),
                        timing=c.get("timing"), video_ts=c.get("video_ts"), bvid=bv,
                        content_md=c.get("content_md", ""), source_hash=chash,
                        zone=c.get("zone"),
                        video_pubdate=int(video_pubdate) if video_pubdate else None,
                    ))
            s.commit()

        # v3 S1 集成：评论时效信号顺路抓取（任何失败降级空列表，不阻断学习）
        video_pubdate = t.get("pubdate") or 0
        if video_pubdate:
            from .bili_signals import extract_comment_signals, fetch_comments, save_signals

            try:
                comments = await fetch_comments(bv, max_pages=2)
                signals = extract_comment_signals(comments, int(video_pubdate))
            except Exception as exc:  # noqa: BLE001 — 信号是锦上添花
                logger.warning(f"[B站学习] bvid={bv} 评论信号失败（忽略）：{type(exc).__name__}: {str(exc)[:80]}")
                signals = []
            if signals:
                with session_factory_fn() as s:
                    new_cards = s.exec(select(GrenadeCard).where(GrenadeCard.bvid == bv)).all()
                    added = sum(save_signals(s, c.id, signals) for c in new_cards)
                logger.info(f"[B站学习] bvid={bv} 评论信号入库 {added} 条")

        async def _push_or_update(title_arg: str, md_arg: str, existing_uuid: str | None) -> dict:
            mv = _new_mv()
            if existing_uuid:
                await mv.update_note(existing_uuid, content=md_arg, title=title_arg)
                return {"created": False, "uuid": existing_uuid, "reason": None}
            pushed = await mv.push_note(title_arg, md_arg, topic_name=SUMMARY_TOPIC)
            # 新笔记 → AI 生成道具复习闪卡（幂等；失败不影响总结已推送）
            try:
                await mv.generate_flashcards(pushed["uuid"], count=3)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[B站学习] 闪卡生成跳过：{exc}")
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

    try:
        m = re.search(r"\{.*\}", raw, re.S)
        data = _json.loads(m.group(0) if m else raw)
        cards = [
            c for c in data.get("cards", [])
            if c.get("map") and c.get("grenade_type")
        ]
        return data.get("summary_md") or "", cards
    except Exception as exc:  # noqa: BLE001 — AI 未按 JSON 输出：降级为原文标注，绝不崩任务
        logger.warning(f"[B站学习] AI 输出解析失败（降级存原文）：{exc}")
        return f"# {title}\n\n> ⚠️ AI 输出解析失败，先入库字幕原文。\n\n```\n{subtitle_text[:6000]}\n```", []


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
