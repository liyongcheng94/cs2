"""demo_fetch：API 直下完美 demo（签名 URL + X-PWA 头）并串现有分析流水线。

场景：
- 正常路径：签名请求下载 zip → 解压 → demo_analyze 链 → demo_status=analyzed、pushed
- 边界：服务器返回 JSON（demo 过期/不存在）→ 任务 failed 且错误信息明确
- 错误处理：401 → WanmeiAuthError（熔断 NEED_AUTH）
- 边界：缓存已有 .dem → 跳过下载直接分析
- 业务规则：非 PVP@ 场次拒绝
"""

from __future__ import annotations

import zipfile
from typing import Callable

import httpx
import pytest


class FakeSigner:
    """确定性假签名器：URL 参数拼进 sig 便于断言。"""

    def sign_demo_request(self, randnum: str, timestamp: str, data: str) -> bytes:
        return f"sig({randnum}|{data})".encode()

    def build_x_pwa_signature(self, steamid: str, timestamp: int, ip_addr: str) -> bytes:
        return f"xp({timestamp}|{ip_addr})".encode()


def _stub_env(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]):
    import app.services.demo_fetch as df

    df._signer = FakeSigner()
    df._transport = httpx.MockTransport(handler)
    df._public_ip_cache = None
    monkeypatch.setattr(df, "_PUBLIC_IP_URLS", ["https://ip.test/"])


def _make_zip_response(match_num: str) -> httpx.Response:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{match_num}_0.dem", "FAKE_DEMO_BYTES")
    return httpx.Response(
        200,
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(buf.getvalue()))},
        content=buf.getvalue(),
    )


def _seed_match(num: str) -> None:
    """demo_analyze 编排要求 Match 行先存在（真实由 wanmei_sync 建）。"""
    import datetime

    from app.database import session_factory
    from app.models import Match

    with session_factory() as s:
        s.add(Match(match_id=f"PVP@{num}", map_name="de_mirage", win=True, played_at=datetime.datetime(2026, 11, 25, 19, 42)))
        s.commit()


def _stub_analysis_pipeline(monkeypatch):
    """桩化 demo_analyze 的解析与推送（下载环节保持真实）。"""
    from app.schemas.analysis import AnalysisMeta, DuelBucket, DuelDim, FourDimAnalysis

    import app.services.demo_analyze as da

    analysis = FourDimAnalysis(
        match_id="X",
        duels=DuelDim(by_weapon_distance=[DuelBucket(distance="0-5m", weapon="AK-47", win_rate=0.22)]),
        meta=AnalysisMeta(parser="stub", cost_s=0.1, peak_mem_mb=100),
    )

    def fake_run(dem_path, match_id, steam_id):
        return analysis, {"cost_s": 0.1, "peak_mem_mb": 100, "parser": "stub"}

    async def fake_push(analysis_arg, md, **kw):
        from app.database import session_factory
        from app.models import Report
        from app.services.report import PromptVersion, compute_source_hash

        with session_factory() as s:
            s.add(Report(
                match_id=analysis_arg.match_id,
                prompt_version=PromptVersion,
                source_hash=compute_source_hash(analysis_arg.match_id, PromptVersion),
                title=f"复盘 · {analysis_arg.match_id}",
                content_md=md or "复盘",
                degraded=False,
                pushed=True,
                mv_uuid="u-1",
            ))
            s.commit()
        return {"created": True, "uuid": "u-1", "reason": None, "match_id": analysis_arg.match_id}

    monkeypatch.setattr(da, "run_analysis", fake_run)
    monkeypatch.setattr(da, "gc_raw_demo", lambda p: None)
    monkeypatch.setattr(da, "push_report", fake_push)


def _seed_token(client) -> None:
    client.put("/api/settings", json={"wanmei.access_token": "tok", "wanmei.steam_id": "76561198339750836"})


@pytest.mark.anyio
async def test_f1_download_and_analyze_chain(client, monkeypatch):
    """Given PVP@ 场次且无本地缓存，When 执行 demo_fetch，Then 下载解压并自动完成分析。"""
    # 用一个不在客户端目录的场：PVP@9000000000000000001
    num = "9000000000000000001"
    seen: dict[str, httpx.Request] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["demo"] = req
        if req.url.host == "ip.test":
            return httpx.Response(200, text="1.2.3.4")
        return _make_zip_response(num)

    _stub_env(monkeypatch, handler)
    _seed_match(num)
    _seed_token(client)
    _stub_analysis_pipeline(monkeypatch)
    resp = client.post("/api/tasks", json={"type": "demo_fetch", "payload": {"match_id": f"PVP@{num}"}})
    assert resp.status_code == 200
    tid = resp.json()["id"]
    run = client.post(f"/api/tasks/{tid}/run").json()
    assert run["status"] == "success", run.get("error")

    # 签名 URL 契约
    url = seen["demo"].url
    assert url.host == "pwaweblogin.wmpvp.com"
    assert url.params["a"] == "20000"
    assert url.params["match_id"] == num
    assert url.params["s"].startswith("sig(")
    assert seen["demo"].headers["X-PWA-Signature"].startswith("xp(")
    assert seen["demo"].headers["Referer"] == "https://client.wmpvp.com"

    # 分析链完成：状态 + 结果
    from sqlmodel import select

    from app.database import session_factory
    from app.models import Match, Report

    with session_factory() as s:
        m = s.get(Match, f"PVP@{num}")
        assert m is not None and m.demo_status == "analyzed"
        rp = s.exec(select(Report).where(Report.match_id == f"PVP@{num}")).first()
        assert rp is not None


@pytest.mark.anyio
async def test_f2_expired_demo_json_error(client, monkeypatch):
    """Given 服务器返回 JSON 错误，When 下载，Then 任务 failed 且错误信息含『demo 已过期』。"""
    num = "9000000000000000002"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "ip.test":
            return httpx.Response(200, text="1.2.3.4")
        return httpx.Response(200, json={"error": "Demo Url out of date"})

    _stub_env(monkeypatch, handler)
    _seed_match(num)
    resp = client.post("/api/tasks", json={"type": "demo_fetch", "payload": {"match_id": f"PVP@{num}"}})
    tid = resp.json()["id"]
    run = client.post(f"/api/tasks/{tid}/run").json()
    assert run["status"] == "failed"
    assert "过期" in (run.get("error") or "") or "不存在" in (run.get("error") or "")


@pytest.mark.anyio
async def test_f3_auth_error_breaker(client, monkeypatch):
    """Given 服务器 401，When 下载，Then 熔断为 NEED_AUTH 且不重试。"""
    num = "9000000000000000003"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "ip.test":
            return httpx.Response(200, text="1.2.3.4")
        return httpx.Response(401, json={"detail": "unauthorized"})

    _stub_env(monkeypatch, handler)
    _seed_match(num)
    resp = client.post("/api/tasks", json={"type": "demo_fetch", "payload": {"match_id": f"PVP@{num}"}})
    tid = resp.json()["id"]
    run = client.post(f"/api/tasks/{tid}/run").json()
    assert run["status"] == "NEED_AUTH"


@pytest.mark.anyio
async def test_f4_cache_hit_skips_download(client, monkeypatch):
    """Given 缓存目录已有 .dem，When 执行，Then 不发起 demo 下载请求直接分析。"""
    from app.config import get_data_dir

    num = "9000000000000000004"
    (get_data_dir() / "demos").mkdir(parents=True, exist_ok=True)
    (get_data_dir() / "demos" / f"{num}_0.dem").write_bytes("FAKE_DEMO")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "ip.test":
            return httpx.Response(200, text="1.2.3.4")
        if req.url.host == "pwaweblogin.wmpvp.com":
            raise AssertionError("缓存命中时不应发起下载")
        return _make_zip_response(num)

    _stub_env(monkeypatch, handler)
    _seed_match(num)
    _seed_token(client)
    _stub_analysis_pipeline(monkeypatch)
    resp = client.post("/api/tasks", json={"type": "demo_fetch", "payload": {"match_id": f"PVP@{num}"}})
    tid = resp.json()["id"]
    run = client.post(f"/api/tasks/{tid}/run").json()
    assert run["status"] == "success", run.get("error")


@pytest.mark.anyio
async def test_f5_reject_non_pvp_match(client, monkeypatch):
    """Given 非 PVP@ 前缀场次，When 执行，Then 拒绝（任务 failed）。"""
    _stub_env(monkeypatch, lambda req: httpx.Response(200, text="1.2.3.4"))
    resp = client.post("/api/tasks", json={"type": "demo_fetch", "payload": {"match_id": "LOCAL@123"}})
    tid = resp.json()["id"]
    run = client.post(f"/api/tasks/{tid}/run").json()
    assert run["status"] == "failed"
