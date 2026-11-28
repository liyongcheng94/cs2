"""复盘推送：source_hash 前置查重 → 已有 mv_uuid 走 REST 更新，新报告走 MCP create；MindVault 挂了只降级不丢数据。"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import Report
from ..schemas.analysis import FourDimAnalysis
from ..services import settings_service
from .mindvault_client import MindVaultClient, MindVaultError
from .report import PromptVersion, compute_source_hash

REPORT_TOPIC = "CS2复盘"


def _new_mv() -> MindVaultClient:
    with session_factory() as session:
        base = settings_service.get_value(session, "mv.base_url")
        pwd = settings_service.get_value(session, "mindvault.password")
    return MindVaultClient(base_url=base or "http://127.0.0.1:8001", password=pwd or None)


def mv_enabled(session: Session) -> bool:
    """MindVault 联动全局开关（默认不联动）。"""
    from . import settings_service

    return (settings_service.get_value(session, "mv.enabled") or "0") == "1"


async def push_report(
    analysis: FourDimAnalysis,
    content_md: str,
    *,
    prompt_version: str = PromptVersion,
    title: str | None = None,
    review_json: dict | None = None,
    degraded: bool = False,
) -> dict:
    """推送复盘到 MindVault（幂等键 matchId+prompt_version）；结果永远先落本地 Report 行。"""
    match_id = analysis.match_id
    source_hash = compute_source_hash(match_id, prompt_version)
    out: dict = {"created": False, "uuid": None, "reason": None, "match_id": match_id, "skipped": False}
    with session_factory() as session:
        if not mv_enabled(session):
            # 开关关闭：仅本地保存，不做任何 MindVault 网络调用
            row = session.exec(select(Report).where(Report.source_hash == source_hash)).first()
            if row is None:
                row = Report(match_id=match_id, prompt_version=prompt_version,
                             source_hash=source_hash, title=title or f"复盘 · {match_id}",
                             content_md=content_md, review_json=review_json, degraded=degraded)
                session.add(row)
                session.commit()
            out["skipped"] = True
            return out
    with session_factory() as session:
        row = session.exec(select(Report).where(Report.source_hash == source_hash)).first()
        is_new_row = row is None
        if row is None:
            row = Report(
                match_id=match_id,
                prompt_version=prompt_version,
                source_hash=source_hash,
                title=title or f"复盘 · {match_id}",
                content_md=content_md,
                review_json=review_json,
                degraded=degraded,
            )
            session.add(row)
            session.commit()
            session.refresh(row)

        is_update = bool(row.mv_uuid)  # 已有笔记 → REST 更新；否则 MCP 新建
        row.content_md = content_md
        row.review_json = review_json
        row.degraded = degraded
        try:
            mv = _new_mv()
            created_now = False
            try:
                if is_update:
                    await mv.update_note(row.mv_uuid, content=content_md, title=row.title)
                    out["uuid"] = row.mv_uuid
                    logger.info(f"[推送] matchId={match_id} 更新已有笔记 uuid={row.mv_uuid}")
                else:
                    raise _NoteMissing()  # 统一走新建分支
            except _NoteMissing:
                pushed = await mv.push_note(row.title, content_md, topic_name=REPORT_TOPIC)
                row.mv_uuid = pushed["uuid"]
                out["uuid"] = pushed["uuid"]
                created_now = True
                logger.info(f"[推送] matchId={match_id} 新建笔记 uuid={pushed['uuid']}")
            row.pushed = True
            out["created"] = created_now
        except MindVaultError as exc:
            # 更新 404（实例迁移/笔记被删）→ 自愈：清 uuid 转新建，仅当本次为更新尝试
            if is_update and "404" in str(exc):
                row.mv_uuid = None
                session.add(row)
                session.commit()
                logger.info(f"[推送] matchId={match_id} 更新 404 自愈转新建")
                return await push_report(analysis, content_md, prompt_version=prompt_version,
                                         title=title, review_json=review_json, degraded=degraded)
            row.pushed = False
            out["reason"] = str(exc)
            logger.warning(f"[推送] matchId={match_id} 失败（本地已保存）：{exc}")
        session.add(row)
        session.commit()
        return out


class _NoteMissing(Exception):
    """内部信号：无既有笔记，转新建分支。"""


def gc_raw_demo(dem_path: Path) -> None:
    """磁盘 GC：解析入库后删除本地 raw demo（客户端 zip 原件不动，可随时重解压）。"""
    if dem_path.exists():
        dem_path.unlink()
        logger.info(f"[GC] 已删除 raw demo {dem_path}")
