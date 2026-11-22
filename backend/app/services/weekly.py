"""周报：近 7 天对局聚合（胜率/平均 rating/demo 分析数/道具卡数）→ 推送 MindVault「CS2周报」。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import BiliVideo, GrenadeCard, Match, MatchStat, Report, Task, utcnow
from .mindvault_client import MindVaultClient, MindVaultError
from .report_push import _new_mv

WEEKLY_TOPIC = "CS2周报"


def _week_key(now: datetime) -> str:
    """ISO 周键（如 2026-W47），幂等推送键。"""
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def build_weekly_markdown(session: Session, now: datetime) -> tuple[str, dict]:
    week_ago = now - timedelta(days=7)
    matches = session.exec(select(Match).where(Match.played_at >= week_ago)).all()
    stats = session.exec(select(MatchStat)).all()
    stat_by_mid = {s.match_id: s for s in stats}
    played = [m for m in matches if m.match_id in stat_by_mid]
    wins = sum(1 for m in played if m.win)
    ratings = [stat_by_mid[m.match_id].rating for m in played if stat_by_mid[m.match_id].rating]
    analyzed = session.exec(select(Match).where(Match.demo_status == "analyzed")).all()
    reports = session.exec(select(Report).where(Report.pushed == True)).all()  # noqa: E712
    cards = session.exec(select(GrenadeCard)).all()
    videos = session.exec(select(BiliVideo).where(BiliVideo.subtitle_status == "subtitle")).all()

    win_rate = wins / len(played) if played else None
    avg_rating = sum(ratings) / len(ratings) if ratings else None

    md = [
        f"# CS2 周报 · {_week_key(now)}",
        "",
        f"- 对局：{len(matches)} 场（{wins} 胜 / {len(played) - wins} 负），胜率 {f'{win_rate:.0%}' if win_rate is not None else '—'}",
        f"- 平均 rating：{f'{avg_rating:.2f}' if avg_rating is not None else '—'}",
        f"- demo 分析累计：{len(analyzed)} 场，复盘推送：{len(reports)} 篇",
        f"- 道具卡：{len(cards)} 张（本周学习视频 {len(videos)} 个）",
        "",
        "## 本周结论",
        "- 数据直读周报（AI 周评随 AI Key/桥可用后增强）。",
    ]
    payload = {
        "matches": len(matches),
        "wins": wins,
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "avg_rating": round(avg_rating, 3) if avg_rating is not None else None,
        "analyzed": len(analyzed),
        "reports_pushed": len(reports),
        "grenade_cards": len(cards),
    }
    return "\n".join(md), payload


async def weekly_report_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    now = utcnow()
    week = _week_key(now)
    with session_factory_fn() as session:
        md, payload = build_weekly_markdown(session, now)
    title = f"CS2 周报 · {week}"
    out: dict = {"created": False, "uuid": None, "reason": None, "week": week}
    try:
        mv = _new_mv()
        pushed = await mv.push_note(title, md, topic_name=WEEKLY_TOPIC)
        out.update({"created": True, "uuid": pushed["uuid"]})
        logger.info(f"[周报] {week} 推送成功 uuid={pushed['uuid']}")
    except MindVaultError as exc:
        out["reason"] = str(exc)
        logger.warning(f"[周报] {week} 推送失败：{exc}")
    out["payload"] = payload
    return out


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["weekly_report"] = weekly_report_handler
