"""demo_analyze 任务编排契约：取 demo → 解析 → 复盘 → 推送 → 磁盘 GC；MindVault/AI 缺失逐级降级。"""
import asyncio
from pathlib import Path

import pytest

from app.schemas.analysis import AnalysisMeta, DuelBucket, DuelDim, FourDimAnalysis


@pytest.fixture()
def fake_pipeline(client, monkeypatch, tmp_path):
    """桩化整条管线：demo 可得、解析返回固定四维 JSON、报告纯数据降级、推送走桩。"""
    import app.services.demo_analyze as da
    from app.services.report import PromptVersion

    dem = tmp_path / "fake.dem"
    dem.write_bytes(b"dem")

    analysis = FourDimAnalysis(
        match_id="PVP@PIPE1",
        duels=DuelDim(by_weapon_distance=[DuelBucket(distance="0-5m", weapon="AK-47", win_rate=0.22)]),
        meta=AnalysisMeta(parser="stub", cost_s=0.1, peak_mem_mb=100),
    )

    monkeypatch.setattr(da, "acquire_demo", lambda match_id, cache_dir=None: dem)
    monkeypatch.setattr(da, "run_analysis", lambda dem_path, match_id, steam_id: (analysis, {"cost_s": 0.1, "peak_mem_mb": 100, "parser": "stub"}))
    gc_calls = []  # 1.3 起 demo 持久保存，模块不再引用 gc_raw_demo
    pushed = {"called": False}

    async def fake_push(analysis_arg, md, **kw):
        pushed["called"] = True
        # 与真实 push_report 对齐：本地 Report 行始终落库
        from app.database import session_factory
        from app.models import Report
        from app.services.report import compute_source_hash

        with session_factory() as s:
            s.add(Report(
                match_id=analysis_arg.match_id,
                prompt_version=PromptVersion,
                source_hash=compute_source_hash(analysis_arg.match_id, PromptVersion),
                title=f"复盘 · {analysis_arg.match_id}",
                content_md=md,
                degraded=kw.get("degraded", False),
                pushed=True,
                mv_uuid="u-1",
            ))
            s.commit()
        return {"created": True, "uuid": "u-1", "reason": None, "match_id": analysis_arg.match_id}

    monkeypatch.setattr(da, "push_report", fake_push)

    # 编排要求 Match 行先存在（由 wanmei_sync 建）；测试直接种两场
    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        for mid in ("PVP@PIPE1", "PVP@PIPE2"):
            s.add(Match(match_id=mid, map_name="de_mirage", win=True, played_at=__import__("datetime").datetime(2026, 11, 21)))
        s.commit()

    return {"dem": dem, "analysis": analysis, "gc_calls": gc_calls, "pushed": pushed, "prompt_version": PromptVersion}


def _seed_token(client):
    client.put("/api/settings", json={"wanmei.access_token": "tok", "wanmei.steam_id": "76561198339750836"})


def test_demo_analyze_happy_path(client, fake_pipeline):
    """
    Given demo 可得、解析桩就绪、MindVault 推送桩
    When  创建并执行 demo_analyze 任务（PVP@PIPE1）
    Then  status=success；DemoAnalysis 与 Report 落库；raw demo 被 GC；推送被调用
    """
    _seed_token(client)
    task_id = client.post("/api/tasks", json={"type": "demo_analyze", "payload": {"match_id": "PVP@PIPE1"}}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success", body["error"]

    # 解析与复盘落库
    from sqlmodel import select

    from app.database import session_factory
    from app.models import DemoAnalysis, Report

    with session_factory() as s:
        da = s.exec(select(DemoAnalysis).where(DemoAnalysis.match_id == "PVP@PIPE1")).first()
        assert da is not None and da.payload["duels"]["by_weapon_distance"][0]["win_rate"] == 0.22
        rp = s.exec(select(Report).where(Report.match_id == "PVP@PIPE1")).first()
        assert rp is not None and rp.content_md

    assert fake_pipeline["pushed"]["called"] is True
    # 1.3 起 demo 持久保存（不再 GC raw demo，避免重复下载）
    assert fake_pipeline["gc_calls"] == []


def test_demo_analyze_missing_demo_marks_pending(client, fake_pipeline, monkeypatch):
    """
    Given 客户端与缓存都没有 demo
    When  执行 demo_analyze
    Then  任务 failed 且 error 提示在客户端点开；Match.demo_status=pending_demo（若 Match 行存在）
    """
    import app.services.demo_analyze as da
    from app.services.demo_dl import DemoNotAvailableError

    _seed_token(client)
    monkeypatch.setattr(da, "acquire_demo", lambda match_id, cache_dir=None: (_ for _ in ()).throw(DemoNotAvailableError("请在客户端点开")))

    task_id = client.post("/api/tasks", json={"type": "demo_analyze", "payload": {"match_id": "PVP@PIPE2"}}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "failed"
    assert "客户端" in body["error"]
