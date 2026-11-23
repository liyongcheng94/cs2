"""学道具 v3 Slice 3：card_health 三信号聚合。

优先级：report（用户上报，最强）> comment（近 90 天评论信号）> patch（补丁对照）。
- report 信号存在 → stale
- 近 90 天内 comment 信号 ≥1 → aging
- 视频发布时间早于最近一次含 grenade 关键词的 Steam 更新 → aging
- 无信号 → alive（默认）
"""

import time
from typing import Any

import httpx
from loguru import logger
from sqlmodel import Session, select

from ..models import GrenadeCard, GrenadeCardSignal

COMMENT_WINDOW_DAYS = 90
STEAM_NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
_GRENADE_PATCH_RE_KEYWORDS = ("grenade", "molotov", "smoke", "flash", "incendiary")


def _comment_transport() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10, follow_redirects=True)


def fetch_grenade_patch_dates() -> list[int]:
    """Steam News：近期含道具词的更新发布时间列表（unix 秒）。失败降级空列表。

    烟测（2026-11-23）：appid=730 GetNewsForApp 免 key 可达，3/5 条含 grenade 词。
    """
    try:
        resp = httpx.get(
            STEAM_NEWS_URL,
            params={"appid": 730, "count": 10, "maxlength": 400, "format": "json"},
            timeout=10,
        )
        items = (resp.json().get("appnews") or {}).get("newsitems") or []
        dates: list[int] = []
        for n in items:
            blob = (n.get("title") or "") + (n.get("contents") or "")
            if any(k in blob.lower() for k in _GRENADE_PATCH_RE_KEYWORDS):
                dates.append(int(n.get("date") or 0))
        return [d for d in dates if d > 0]
    except Exception as exc:  # noqa: BLE001 — 补丁对照是锦上添花
        logger.warning(f"[健康度] Steam 补丁获取失败（忽略）：{type(exc).__name__}: {str(exc)[:80]}")
        return []


def aggregate_health(session: Session, card: GrenadeCard, patch_dates: list[int] | None = None) -> str:
    """三信号聚合出 health 并写回卡（不 commit，调用方决定事务边界）。"""
    signals = session.exec(
        select(GrenadeCardSignal).where(GrenadeCardSignal.card_id == card.id)
    ).all()

    # 1) report 最高优先级
    if any(s.source == "report" for s in signals):
        card.health = "stale"
        return card.health

    now = int(time.time())
    window_start = now - COMMENT_WINDOW_DAYS * 86400

    # 2) 时效窗内的评论信号
    if any(
        s.source == "comment" and s.ctime and s.ctime >= window_start
        for s in signals
    ):
        card.health = "aging"
        return card.health

    # 3) 补丁对照：视频发布早于某次含道具词的 Steam 更新 → 点位可能已变
    if patch_dates is None:
        patch_dates = fetch_grenade_patch_dates()
    if card.video_pubdate and patch_dates and card.video_pubdate < max(patch_dates):
        card.health = "aging"
        return card.health

    card.health = "alive"
    return card.health


def health_summary(cards: list[GrenadeCard]) -> dict[str, Any]:
    """列表页摘要：{alive: n, aging: n, stale: n}。"""
    out = {"alive": 0, "aging": 0, "stale": 0}
    for c in cards:
        out[c.health if c.health in out else "alive"] += 1
    return out
