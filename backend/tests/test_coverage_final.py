"""收尾覆盖：detailStats / 降级 markdown / 提示词资产 / bili_learn 错误路径 / moments 目录默认值。"""
import httpx
import pytest

from app.services.report import load_prompt, render_markdown
from app.schemas.analysis import AnalysisMeta, DuelBucket, DuelDim, FourDimAnalysis, ReviewOutput


@pytest.mark.anyio
async def test_wanmei_detail_stats_parses(client, monkeypatch):
    """
    Given detailStats 端点桩（真实信封结构）
    When  detail_stats()
    Then  解包 data 字段
    """
    from app.services.wanmei import WanmeiAPI

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/csgo/home/pvp/detailStats"
        return httpx.Response(200, json={"statusCode": 0, "data": {"adr": 71.5, "rating": 1.02}})

    api = WanmeiAPI(token="t", steam_id="1", transport=httpx.MockTransport(handler))
    out = await api.detail_stats()
    assert out["adr"] == 71.5


def test_load_prompt_review_asset_exists():
    """
    Given 防幻觉复盘提示词资产
    When  load_prompt("review")
    Then  含防幻觉铁律与 JSON 输出约定
    """
    p = load_prompt("review")
    assert "复盘教练" in p and "JSON" in p
    assert load_prompt("no_such_prompt") == ""


def test_render_markdown_degraded_fallback(client):
    """
    Given ReviewOutput=None（降级）
    When  render_markdown（经 build_report fallback 路径）
    Then  Markdown 含降级原因与四维数据块
    """
    import asyncio

    from app.services.report import build_report

    analysis = FourDimAnalysis(
        match_id="PVP@FB",
        duels=DuelDim(by_weapon_distance=[DuelBucket(distance="0-5m", weapon="AK-47", win_rate=0.22)]),
        meta=AnalysisMeta(parser="awpy 3.3.0", cost_s=1.0),
    )
    result = asyncio.run(build_report(analysis, ai=None))
    assert result.degraded is True and result.review is None
    md = result.markdown
    assert "AI降级" in md and "## 对枪矩阵" in md and "## 今日唯一重点" in md


def test_bili_learn_requires_sessdata(client):
    """
    Given 未配置 SESSDATA
    When  执行 bili_learn
    Then  failed 且提示设置页配置
    """
    task_id = client.post("/api/tasks", json={"type": "bili_learn", "payload": {"bvid": "BV1x"}}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "failed"
    assert "SESSDATA" in body["error"]


def test_bili_learn_requires_payload(client):
    """
    Given 配置了 SESSDATA 但 payload 缺 bvid/keyword
    When  执行 bili_learn
    Then  failed 且报 payload 要求
    """
    client.put("/api/settings", json={"bili.sessdata": "SESS"})
    task_id = client.post("/api/tasks", json={"type": "bili_learn", "payload": {}}).json()["id"]
    client.post(f"/api/tasks/{task_id}/run")
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "failed"
    assert "bvid" in body["error"]


def test_moments_dir_default_created(client, monkeypatch, tmp_path):
    """
    Given 未配置 moments.dir
    When  moments_dir()
    Then  返回 data/moments 且目录已创建
    """
    import app.services.moments as mo

    monkeypatch.setattr(mo.settings_service, "get_value", lambda session, key: None)
    out = mo.moments_dir()
    assert out.exists() and out.name == "moments"


class _FakeSession:
    def __init__(self, values):
        self._v = values

    def exec(self, *a, **k):
        raise NotImplementedError

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_moments_dir_from_settings(client, monkeypatch, tmp_path):
    """
    Given settings 配置 moments.dir
    When  moments_dir()
    Then  使用配置目录
    """
    import app.services.moments as mo

    class S:
        def get_value(self, key):
            return str(tmp_path / "exported") if key == "moments.dir" else None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mo.settings_service, "get_value", lambda session, key: str(tmp_path / "exported") if key == "moments.dir" else None)
    assert mo.moments_dir() == tmp_path / "exported"


def test_render_markdown_full_shape_guard():
    """
    Given 完整 ReviewOutput
    When  render_markdown
    Then  不因空列表崩溃且四节齐全（边界条件）
    """
    review = ReviewOutput(match_id="PVP@E", mistakes=[], highlights=[], today_focus="", tomorrow=[])
    analysis = FourDimAnalysis(match_id="PVP@E", meta=AnalysisMeta(parser="awpy 3.3.0"))
    md = render_markdown(review, analysis)
    assert "无明显失误" in md and "（无）" in md
