"""demo_analyze 任务编排：acquire → 解析（选型库）→ 复盘（护栏）→ 推送（幂等）→ 磁盘 GC。

解析引擎接口：run_analysis(dem_path, match_id, steam_id) -> (FourDimAnalysis, meta_dict)
由 demo_analysis 引擎实现（阶段 2b spike 定选后落地）；此处只编排，不关心解析细节。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from ..database import session_factory
from ..models import DemoAnalysis, Match, Task, utcnow
from ..schemas.analysis import FourDimAnalysis
from . import settings_service
from .demo_dl import DemoNotAvailableError, acquire_demo
from .report import PromptVersion, build_report
from .report_push import gc_raw_demo, push_report

# 解析引擎（awpy 选型，见 docs/spike-demo-parsers.md）；测试桩可 monkeypatch 替换
from .demo_analysis import run_analysis  # noqa: E402

# CPU 密集隔离：Semaphore(1) 串行防 OOM（评审确定）
ANALYSIS_SEMAPHORE = asyncio.Semaphore(1)


def _ensure_match_row(session: Session, match_id: str) -> None:
    """匹配行由 wanmei_sync 建；若缺失（直接分析场景）给出可读错误。"""
    if session.exec(select(Match).where(Match.match_id == match_id)).first() is None:
        raise ValueError(f"对局 {match_id} 不在本地库（先同步战绩）")


def _set_demo_status(match_id: str, status: str) -> None:
    with session_factory() as session:
        m = session.exec(select(Match).where(Match.match_id == match_id)).first()
        if m is not None:
            m.demo_status = status
            session.add(m)
            session.commit()


async def demo_analyze_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    match_id = str(task.payload.get("match_id") or "")
    if not match_id:
        raise ValueError("payload 缺 match_id")

    with session_factory_fn() as session:
        steam_id = settings_service.get_value(session, "wanmei.steam_id") or ""
        _ensure_match_row(session, match_id)

    # 1) 取 demo（客户端协作；拿不到 → pending_demo 提示）
    try:
        dem = acquire_demo(match_id)
    except DemoNotAvailableError as exc:
        _set_demo_status(match_id, "pending_demo")
        raise DemoNotAvailableError(str(exc)) from exc
    _set_demo_status(match_id, "downloaded")

    # 2) 解析（CPU 密集：线程池 + Semaphore(1) 串行防 OOM）
    if run_analysis is None:
        raise ValueError("解析引擎未初始化（阶段 2b spike 后注入 run_analysis）")
    async with ANALYSIS_SEMAPHORE:
        analysis, meta = await asyncio.to_thread(run_analysis, Path(dem), match_id, steam_id)
    with session_factory_fn() as session:
        row = session.exec(select(DemoAnalysis).where(DemoAnalysis.match_id == match_id)).first()
        if row is None:
            row = DemoAnalysis(match_id=match_id, schema_version=analysis.schema_version)
        row.payload = analysis.model_dump()
        row.parser = meta.get("parser", "")
        row.cost_s = meta.get("cost_s")
        row.peak_mem_mb = meta.get("peak_mem_mb")
        row.created_at = utcnow()
        session.add(row)
        session.commit()
    _set_demo_status(match_id, "analyzed")
    logger.info(f"[demo解析] matchId={match_id} 耗时={meta.get('cost_s')}s 峰值内存={meta.get('peak_mem_mb')}MB parser={meta.get('parser')}")

    # 3) 复盘（AI 缺失自动降级纯文本）
    report = await build_report(analysis, ai=None)

    # 4) 推送（幂等；MindVault 挂了只降级）
    pushed = await push_report(
        analysis,
        report.markdown,
        prompt_version=PromptVersion,
        review_json=report.review.model_dump() if report.review else None,
        degraded=report.degraded,
    )

    # 5) 磁盘 GC（raw demo 删除；客户端 zip 原件不动）
    gc_raw_demo(Path(dem))

    return {
        "match_id": match_id,
        "parser": meta.get("parser"),
        "pushed": pushed["created"],
        "degraded": report.degraded,
        "uuid": pushed.get("uuid"),
    }


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["demo_analyze"] = demo_analyze_handler
