"""学道具 v3 Slice 1：B 站评论时效信号。

评论接口（x/v2/reply，免签名免登录，烟测通过 2026-11-23）抓取 → 信号词提取
（90 天窗对齐：视频发布后 90 天内的评论才有时效价值）→ GrenadeCardSignal 落库。
Slice 3 card_health 聚合消费这些信号；本模块不直接改 health。
"""

import re
from typing import Any

import httpx
from loguru import logger
from sqlmodel import Session, select

from ..models import GrenadeCardSignal

REPLY_URL = "https://api.bilibili.com/x/v2/reply"

# 时效信号词：版本变动 / 点位失效 / 疑问句式（烟测样本："跳投现在是怎么投容错率高一些？"）
_SIGNAL_RE = re.compile(
    r"削|改版|这版本|新版本|旧版本|老版本|过时|不行了|更新后|更新之后|还能用|还成立|还行吗|现在还|以前"
)
# 时间窗：视频发布 90 天后的评论才算时效信号（发布 1 小时内的"被削了"是老信号）
_SIGNAL_WINDOW_DAYS = 90


def _comment_transport() -> httpx.AsyncClient:
    """默认真实传输层（测试 monkeypatch 成带 transport 的 AsyncClient）。"""
    return httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        headers=_bili_headers(),
        transport=_real_transport(),
    )


def _real_transport() -> httpx.AsyncBaseTransport | None:
    """真实 HTTP 传输（测试可 monkeypatch 为 None 走默认；生产可换代理）。"""
    return None


def _bili_headers() -> dict[str, str]:
    from .bili import HEADERS

    return dict(HEADERS)


async def _fetch_aid(bvid: str, client: httpx.AsyncClient) -> int | None:
    """BV → aid（弹幕/评论接口用 oid=aid）。失败返回 None。"""
    try:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
        )
        data = resp.json()
        if data.get("code") != 0:
            return None
        return (data.get("data") or {}).get("aid")
    except Exception as exc:  # noqa: BLE001 — 信号是锦上添花
        logger.warning(f"[评论信号] bvid={bvid} aid 解析失败：{type(exc).__name__}")
        return None


async def fetch_comments(bvid: str, max_pages: int = 2) -> list[tuple[int, str, int]]:
    """抓取视频评论：返回 [(ctime, message, rcount)]；失败降级空列表不抛异常。

    只走主楼列表（楼中楼信号密度低且翻页成本高）；分页 count 驱动，rpid 去重。
    """
    out: list[tuple[int, str, int]] = []
    seen_rpids: set[int] = set()
    try:
        transport = _comment_transport()
        async with transport as client:
            aid = await _fetch_aid(bvid, client)
            if not aid:
                return out
            pn = 1
            total = None
            while pn <= max_pages:
                resp = await client.get(
                    REPLY_URL,
                    params={"type": 1, "oid": aid, "pn": pn, "ps": 20, "sort": 1},
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.warning(f"[评论信号] bvid={bvid} pn={pn} code={data.get('code')} 停止翻页")
                    break
                d = data.get("data") or {}
                page = d.get("page") or {}
                total = total or page.get("count") or 0
                replies = d.get("replies") or []
                for r in replies:
                    rpid = r.get("rpid")
                    if rpid in seen_rpids:
                        continue
                    seen_rpids.add(rpid)
                    msg = ((r.get("content") or {}).get("message") or "").strip()
                    if msg:
                        out.append((int(r.get("ctime") or 0), msg, int(r.get("rcount") or 0)))
                fetched = len(out)
                if not replies or (total and fetched >= total):
                    break
                pn += 1
        logger.info(f"[评论信号] bvid={bvid} 抓取 {len(out)} 条评论（max_pages={max_pages}）")
        return out
    except Exception as exc:  # noqa: BLE001 — 信号抓取失败不阻断学习
        logger.warning(f"[评论信号] bvid={bvid} 抓取失败（忽略）：{type(exc).__name__}: {str(exc)[:100]}")
        return []


def extract_comment_signals(
    comments: list[tuple[int, str, int]], video_pubdate: int
) -> list[dict[str, Any]]:
    """信号词提取 + 90 天窗对齐：发布后 90 天内的评论不产出时效信号。

    返回 [{"source": "comment", "text": ..., "ctime": ...}]
    """
    window_start = video_pubdate + _SIGNAL_WINDOW_DAYS * 86400
    signals: list[dict[str, Any]] = []
    for ctime, message, _rcount in comments:
        if video_pubdate and ctime < window_start:
            continue
        if _SIGNAL_RE.search(message):
            signals.append({"source": "comment", "text": message[:200], "ctime": ctime})
    return signals


def save_signals(session: Session, card_id: int, signals: list[dict[str, Any]]) -> int:
    """信号落库（幂等：card_id+source+text 去重），返回新增条数。"""
    added = 0
    for sig in signals:
        exists = session.exec(
            select(GrenadeCardSignal).where(
                GrenadeCardSignal.card_id == card_id,
                GrenadeCardSignal.source == sig["source"],
                GrenadeCardSignal.text == sig["text"],
            )
        ).first()
        if exists:
            continue
        session.add(
            GrenadeCardSignal(
                card_id=card_id,
                source=sig["source"],
                text=sig["text"],
                ctime=sig.get("ctime"),
            )
        )
        added += 1
    session.commit()
    return added
