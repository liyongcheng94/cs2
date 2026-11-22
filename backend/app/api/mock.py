"""Mock 全链路自检：假数据 → 四维分析 → 复盘 → MindVault 推送（ MindVault 不可达时降级不阻塞）。"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from fastapi import APIRouter, Depends
from loguru import logger

from ..database import SessionDep
from ..models import DemoAnalysis, Match, MatchStat, Report, utcnow
from ..schemas.analysis import (
    AnalysisMeta,
    BuyDecision,
    DeathDim,
    DeathEvent,
    DuelBucket,
    DuelDim,
    EconomyDim,
    FourDimAnalysis,
    ReviewOutput,
    ReviewPoint,
    SCHEMA_VERSION,
    ThrowEvent,
    UtilityDim,
)
from ..services.mindvault_client import MindVaultClient, MindVaultError
from .deps import get_mv_client

router = APIRouter(tags=["test"])

MOCK_TOPIC = "CS2复盘"


def _build_fake_analysis(match_id: str) -> FourDimAnalysis:
    return FourDimAnalysis(
        match_id=match_id,
        deaths=DeathDim(
            events=[
                DeathEvent(
                    round_no=3, killer_weapon="AK-47", distance_m=8.2,
                    first_duel=True, teammate_support=False, disadvantaged_position=True,
                ),
                DeathEvent(
                    round_no=12, killer_weapon="AWP", distance_m=28.0,
                    first_duel=False, teammate_support=True, disadvantaged_position=False,
                ),
            ],
            buckets=[DuelBucket(distance="0-5m", weapon="AK-47", deaths=2)],
            disadvantaged_rate=0.35,
        ),
        economy=EconomyDim(
            buy_decisions=[BuyDecision(round_no=1, buy="full", equip_value=4900, effective=True)],
            effective_buy_ratio=0.72,
            first_kill_conversion=0.61,
        ),
        utility=UtilityDim(
            throws=[ThrowEvent(round_no=5, grenade_type="smoke", point="A大", effective=True)],
            blind_median_s=2.1,
            waste_rate=0.18,
        ),
        duels=DuelDim(
            by_weapon_distance=[
                DuelBucket(distance="0-5m", weapon="AK-47", kills=3, deaths=5, win_rate=0.375),
                DuelBucket(distance="15m+", weapon="AWP", kills=4, deaths=1, win_rate=0.8),
            ],
            first_strike_win_rate=0.55,
            mirror_win_rate=None,
        ),
        meta=AnalysisMeta(parser="mock", cost_s=0.01, peak_mem_mb=None),
    )


def _build_fake_report(match_id: str, analysis: FourDimAnalysis) -> tuple[str, str, ReviewOutput]:
    title = f"[MOCK] CS2HQ 全链路自检 · {match_id}"
    review = ReviewOutput(
        match_id=match_id,
        mistakes=[
            ReviewPoint(
                title="近战对枪胜率偏低，急停不干净",
                evidence=f"duels.by_weapon_distance[0]: 0-5m AK-47 win_rate={analysis.duels.by_weapon_distance[0].win_rate}",
                severity="high",
            ),
            ReviewPoint(
                title="部分死亡处于劣势枪位",
                evidence=f"deaths.disadvantaged_rate={analysis.deaths.disadvantaged_rate}",
                severity="mid",
            ),
        ],
        highlights=["15m+ AWP 对枪 4/1 胜率 80%"],
        today_focus="近战急停：aim_botz 移动急停开枪 10 分钟",
        tomorrow=["道具特训：A大 smoke 3 次成功", "手枪死斗 10 分钟"],
    )
    content = (
        f"# {title}\n\n"
        "## 失误 Top3\n\n"
        f"1. **{review.mistakes[0].title}**（证据：`{review.mistakes[0].evidence}`）\n"
        f"2. **{review.mistakes[1].title}**（证据：`{review.mistakes[1].evidence}`）\n\n"
        "## 高光\n\n- " + "\n- ".join(review.highlights) + "\n\n"
        "## 今日唯一重点\n\n" + review.today_focus + "\n\n"
        "## 明日练什么\n\n- " + "\n- ".join(review.tomorrow) + "\n\n"
        "---\n\n*CS2HQ mock-flow 自动生成*"
    )
    return title, content, review


@router.post("/test/mock-flow")
async def mock_flow(session: SessionDep, mv: MindVaultClient = Depends(get_mv_client)) -> dict:
    now = utcnow()
    match_id = f"PVP@MOCK-{now.strftime('%Y%m%d%H%M%S%f')}"

    match = Match(
        match_id=match_id,
        map_name="de_dust2",
        score1=13,
        score2=9,
        win=True,
        mode="competitive",
        played_at=now - timedelta(hours=1),
        demo_status="analyzed",
        raw={"mock": True},
    )
    session.add(match)
    session.add(
        MatchStat(
            match_id=match_id, rating=1.12, pw_rating=1500, adr=82.5, rws=70.2,
            hs_rate=0.33, kills=22, deaths=15, assists=6, mvp=3,
        )
    )
    analysis = _build_fake_analysis(match_id)
    session.add(
        DemoAnalysis(
            match_id=match_id, schema_version=SCHEMA_VERSION,
            payload=analysis.model_dump(), parser="mock", cost_s=analysis.meta.cost_s,
        )
    )
    title, content, review = _build_fake_report(match_id, analysis)
    prompt_version = "v1"
    source_hash = hashlib.sha256(f"{match_id}+{prompt_version}".encode()).hexdigest()
    report = Report(
        match_id=match_id, prompt_version=prompt_version, source_hash=source_hash,
        title=title, content_md=content, review_json=review.model_dump(),
    )
    session.add(report)
    session.commit()

    out: dict = {"ok": True, "match_id": match_id, "topic": MOCK_TOPIC}
    try:
        pushed = await mv.push_note(title, content, topic_name=MOCK_TOPIC)
        report.pushed = True
        report.mv_uuid = pushed["uuid"]
        session.add(report)
        session.commit()
        out.update({"pushed": True, "mv_uuid": pushed["uuid"]})
        logger.info(f"[Mock全链路] matchId={match_id} 推送成功 uuid={pushed['uuid']}")
    except MindVaultError as exc:
        out.update({"pushed": False, "reason": str(exc)})
        logger.warning(f"[Mock全链路] matchId={match_id} 推送失败（已降级本地保存）：{exc}")
    return out
