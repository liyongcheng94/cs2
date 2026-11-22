"""完美平台对局同步：match/list 分页拉取 → 幂等 UPSERT；任务 handler 注册为 wanmei_sync。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from ..models import Match, MatchStat, Task, utcnow
from .wanmei import WanmeiAPI

MAX_PAGES_PER_RUN = 3  # 单次任务最多拉 3 页，防风控
PAGE_INTERVAL_S = 2.0  # ≥2s/请求限速


def _parse_played_at(raw: dict) -> datetime:
    """优先 startTime 字符串（平台本地时区，naive 存储），其次 timeStamp 秒级。"""
    start = raw.get("startTime")
    if isinstance(start, str) and start:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(start, fmt)
            except ValueError:
                continue
    ts = raw.get("timeStamp") or raw.get("matchTime") or 0
    try:
        ts = int(ts)
        if ts > 10**12:  # 毫秒时间戳
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OSError):
        return utcnow()


def upsert_match(session: Session, raw: dict, my_steam_id: str) -> Match:
    """按 matchId 幂等写入 Match + MatchStat（重复同步不产生新行）。

    真实结构（2026-11-22 实测）：winTeam/team 为 1/2 整数，胜负 = winTeam == team；
    mapName 为中文名；mvp/pvpMvp 为布尔；we 为 WE 评分；startTime 为本地时间字符串。
    """
    match_id = str(raw.get("matchId") or "")
    if not match_id:
        raise ValueError(f"对局记录缺 matchId：{str(raw)[:120]}")
    score1, score2 = int(raw.get("score1") or 0), int(raw.get("score2") or 0)
    win_team, my_team = raw.get("winTeam"), raw.get("team")
    if win_team is not None and my_team is not None:
        win = str(win_team) == str(my_team)
    else:  # 兜底：比分 + 己方默认 1 队
        win = score1 > score2 if my_team in (1, "1", None) else score2 > score1

    existing = session.exec(select(Match).where(Match.match_id == match_id)).first()
    if existing is None:
        match = Match(
            match_id=match_id,
            map_name=str(raw.get("mapName") or "unknown"),
            score1=score1,
            score2=score2,
            win=win,
            mode=str(raw.get("mode") or raw.get("matchType") or ""),
            played_at=_parse_played_at(raw),
            raw=raw,
        )
        session.add(match)
    else:
        match = existing
        match.map_name = str(raw.get("mapName") or match.map_name)
        match.score1, match.score2 = score1, score2
        match.win = win
        match.raw = raw

    mvp = raw.get("mvp") or raw.get("pvpMvp")
    fields = {
        "rating": raw.get("rating"),
        "pw_rating": raw.get("pwRating"),
        "rws": raw.get("rws"),
        "hs_rate": raw.get("headshotRate") or raw.get("hsRate"),
        "kills": raw.get("kill"),
        "deaths": raw.get("death"),
        "assists": raw.get("assist"),
        "mvp": int(bool(mvp)) if mvp is not None else None,
        "we": raw.get("we"),
        "k4": raw.get("k4"),
        "k5": raw.get("k5"),
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    stat = session.exec(select(MatchStat).where(MatchStat.match_id == match_id)).first()
    if stat is None:
        stat = MatchStat(match_id=match_id, **fields, raw={"mySteamId": my_steam_id})
        session.add(stat)
    else:
        for k, v in fields.items():
            setattr(stat, k, v)
        stat.raw = {"mySteamId": my_steam_id}
    session.commit()
    session.refresh(match)
    return match


async def sync_matches(
    task: Task,
    session_factory: Callable[[], Session],
    api: WanmeiAPI,
    max_pages: int = MAX_PAGES_PER_RUN,
    page_size: int = 20,
) -> dict:
    """拉取对局列表并幂等入库；NEED_AUTH/普通异常向上抛给任务层分流。"""
    inserted, updated, pages_fetched = 0, 0, 0
    for page in range(1, max_pages + 1):
        result = await api.match_list(page=page, page_size=page_size)
        pages_fetched = page
        rows = result.get("matchList") or result.get("dataList") or result.get("list") or []
        if not rows:
            break
        with session_factory() as session:
            for raw in rows:
                existing = session.exec(
                    select(Match).where(Match.match_id == str(raw.get("matchId")))
                ).first()
                upsert_match(session, raw, api.steam_id)
                if existing is None:
                    inserted += 1
                else:
                    updated += 1
        logger.info(f"[完美同步] taskId={task.id} 第{page}页 新增={inserted} 更新={updated}")
        if len(rows) < page_size:
            break
        if page < max_pages:
            await asyncio.sleep(PAGE_INTERVAL_S)
    return {"inserted": inserted, "updated": updated, "pages": pages_fetched}


def build_api_from_settings(session: Session) -> WanmeiAPI:
    """从 settings（解密）构建已登录 API 客户端；缺凭证时给可读错误。"""
    from . import settings_service
    from .wanmei import WanmeiError

    token = settings_service.get_value(session, "wanmei.access_token")
    steam_id = settings_service.get_value(session, "wanmei.steam_id")
    if not token or not steam_id:
        raise WanmeiError("尚未登录完美平台：请先在设置页完成短信登录")
    return WanmeiAPI(token=token, steam_id=steam_id)


async def wanmei_sync_handler(task: Task, session_factory: Callable[[], Session]) -> dict:
    """任务中心 handler：wanmei_sync。凭证缺失/失效由异常类型分流（Error/NEED_AUTH）。"""
    with session_factory() as session:
        api = build_api_from_settings(session)
    return await sync_matches(task, session_factory, api)


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["wanmei_sync"] = wanmei_sync_handler
