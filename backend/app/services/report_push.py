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
    out: dict = {"created": False, "uuid": None, "reason": None, "match_id": match_id}
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
            if is_update:
                await mv.update_note(row.mv_uuid, content=content_md, title=row.title)
                out["uuid"] = row.mv_uuid
                logger.info(f"[推送] matchId={match_id} 更新已有笔记 uuid={row.mv_uuid}")
            else:
                pushed = await mv.push_note(row.title, content_md, topic_name=REPORT_TOPIC)
                row.mv_uuid = pushed["uuid"]
                out["uuid"] = pushed["uuid"]
                logger.info(f"[推送] matchId={match_id} 新建笔记 uuid={pushed['uuid']}")
            row.pushed = True
            out["created"] = not is_update
        except MindVaultError as exc:
            row.pushed = False
            out["reason"] = str(exc)
            logger.warning(f"[推送] matchId={match_id} 失败（本地已保存）：{exc}")
        session.add(row)
        session.commit()
        return out


def gc_raw_demo(dem_path: Path) -> None:
    """磁盘 GC：解析入库后删除本地 raw demo（客户端 zip 原件不动，可随时重解压）。"""
    if dem_path.exists():
        dem_path.unlink()
        logger.info(f"[GC] 已删除 raw demo {dem_path}")
