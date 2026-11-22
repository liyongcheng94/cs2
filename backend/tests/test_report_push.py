"""复盘推送契约：source_hash 前置查重 → 已存在走 REST 更新 / 新报告走 MCP create；MindVault 挂了不丢本地数据；磁盘 GC。"""
import asyncio
import json

import httpx
import pytest

from app.schemas.analysis import AnalysisMeta, DuelBucket, DuelDim, FourDimAnalysis
from app.services.report import PromptVersion, compute_source_hash


def _fake_analysis(match_id="PVP@PUSH1") -> FourDimAnalysis:
    return FourDimAnalysis(
        match_id=match_id,
        duels=DuelDim(by_weapon_distance=[DuelBucket(distance="0-5m", weapon="AK-47", win_rate=0.22)]),
        meta=AnalysisMeta(parser="spike", cost_s=1.0),
    )


@pytest.fixture()
def mv_stub(monkeypatch):
    """MindVaultClient 桩：记录 create/update 调用。"""
    import app.services.report_push as rp
    from app.services.mindvault_client import MindVaultClient

    state = {"created": 0, "updated": 0, "uuid": "mv-uuid-push-1"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/topics":
            if request.method == "GET":
                return httpx.Response(200, json=[])
            return httpx.Response(201, json={"id": 7, "name": "CS2复盘"})
        if request.url.path == "/api/mcp":
            state["created"] += 1
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"content": [{"type": "text", "text": json.dumps({"item_id": 1, "uuid": state["uuid"], "title": body["params"]["arguments"]["title"]})}], "isError": False},
                },
            )
        if request.method == "PUT" and request.url.path.startswith("/api/items/"):
            state["updated"] += 1
            return httpx.Response(200, json={"uuid": state["uuid"]})
        return httpx.Response(404)

    stub = MindVaultClient(base_url="http://stub", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(rp, "_new_mv", lambda: stub)
    return state


def test_push_report_creates_new(client, mv_stub):
    """
    Given 新对局的复盘（无历史笔记）
    When  push_report
    Then  走 MCP create_note；Report 行记录 mv_uuid 与 source_hash
    """
    from app.services.report_push import push_report

    out = asyncio.run(push_report(_fake_analysis(), "复盘MD内容", prompt_version=PromptVersion))
    assert out["created"] is True and out["uuid"] == "mv-uuid-push-1"
    assert mv_stub["created"] == 1 and mv_stub["updated"] == 0

    from sqlmodel import select

    from app.database import session_factory
    from app.models import Report

    with session_factory() as s:
        row = s.exec(select(Report).where(Report.match_id == "PVP@PUSH1")).first()
        assert row is not None
        assert row.pushed is True and row.mv_uuid == "mv-uuid-push-1"
        assert row.source_hash == compute_source_hash("PVP@PUSH1", PromptVersion)
        assert row.content_md == "复盘MD内容"


def test_push_report_updates_existing(client, mv_stub):
    """
    Given 同 matchId+prompt_version 已推过（Report.mv_uuid 已存）
    When  再次 push_report（解析升级后重新生成）
    Then  走 REST PUT 更新而非 create（不产生重复笔记）
    """
    from sqlmodel import select

    from app.database import session_factory
    from app.models import Report
    from app.services.report_push import push_report

    with session_factory() as s:
        s.add(Report(
            match_id="PVP@PUSH2",
            prompt_version=PromptVersion,
            source_hash=compute_source_hash("PVP@PUSH2", PromptVersion),
            title="旧标题",
            content_md="旧内容",
            mv_uuid="mv-uuid-push-1",
        ))
        s.commit()

    out = asyncio.run(push_report(_fake_analysis("PVP@PUSH2"), "升级后的MD", prompt_version=PromptVersion))
    assert out["created"] is False and out["uuid"] == "mv-uuid-push-1"
    assert mv_stub["created"] == 0 and mv_stub["updated"] == 1

    with session_factory() as s:
        row = s.exec(select(Report).where(Report.match_id == "PVP@PUSH2")).first()
        assert row.content_md == "升级后的MD"


def test_push_report_mindvault_down_keeps_local(client, monkeypatch):
    """
    Given MindVault 不可达
    When  push_report
    Then  返回 created=False + reason；Report 行保留本地内容（不丢数据）
    """
    import app.services.report_push as rp
    from app.services.mindvault_client import MindVaultClient
    from app.services.report_push import push_report

    monkeypatch.setattr(rp, "_new_mv", lambda: MindVaultClient(base_url="http://127.0.0.1:1", transport=None))
    out = asyncio.run(push_report(_fake_analysis("PVP@PUSH3"), "md", prompt_version=PromptVersion))
    assert out["created"] is False and out["reason"]

    from sqlmodel import select

    from app.database import session_factory
    from app.models import Report

    with session_factory() as s:
        row = s.exec(select(Report).where(Report.match_id == "PVP@PUSH3")).first()
        assert row is not None and row.content_md == "md" and row.pushed is False


def test_gc_raw_demo(client, tmp_path):
    """
    Given 磁盘 GC 约定：解析入库后删除本地 raw demo
    When  gc_raw_demo(dem_path)
    Then  文件被删除（客户端 zip 原件不受影响，可重新解压）
    """
    from app.services.report_push import gc_raw_demo

    p = tmp_path / "x.dem"
    p.write_bytes(b"abc")
    gc_raw_demo(p)
    assert not p.exists()
