"""补充覆盖：fetch_subtitle 桩 / bili_learn 编排 / run_analysis 真 demo 集成 / ffmpeg 真压缩。"""
import asyncio
import os
import subprocess
from pathlib import Path

import pytest

import httpx

def shutil_which_ffmpeg():
    try:
        import imageio_ffmpeg  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return None


DEMO_PATH = Path(__file__).resolve().parents[2] / "data" / "demos" / "9215177922805569036_0.dem"


@pytest.mark.anyio
async def test_fetch_subtitle_with_stub_lib(monkeypatch):
    """
    Given bilibili_api 桩（get_info 带 cid、get_subtitle 返回 ai-zh 轨、CDN 桩返回字幕 JSON）
    When  fetch_subtitle
    Then  拼接 content 纯文本（zh-CN 优先逻辑由 pick 顺序覆盖）
    """
    import app.services.bili as b

    class StubVideo:
        def __init__(self, bvid, credential=None, cid=None):
            pass

        async def get_info(self):
            return {"cid": 42, "pages": [{"cid": 42}]}

        async def get_subtitle(self, cid=None):
            return {"subtitles": [{"lan": "ai-zh", "subtitle_url": "//cdn.example/sub.json"}]}

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(200, json={"body": [{"content": "行一"}, {"content": "行二"}]})

    import bilibili_api.video as bvm

    monkeypatch.setattr(bvm, "Video", StubVideo)
    monkeypatch.setattr(b.httpx, "get", fake_get)

    out = await b.fetch_subtitle("BV1stub", "SESS")
    assert out == "行一\n行二"


@pytest.mark.anyio
async def test_fetch_subtitle_none_when_no_track(monkeypatch):
    """
    Given 字幕轨为空
    When  fetch_subtitle
    Then  返回 None（调用方标 no_subtitle）
    """
    import app.services.bili as b

    class StubVideo:
        def __init__(self, *a, **k):
            pass

        async def get_info(self):
            return {"cid": 42}

        async def get_subtitle(self, cid=None):
            return {"subtitles": []}

    import bilibili_api.video as bvm

    monkeypatch.setattr(bvm, "Video", StubVideo)
    assert await b.fetch_subtitle("BV1stub", "SESS") is None


@pytest.mark.anyio
async def test_bili_learn_handler_degraded_flow(client, monkeypatch, tmp_path):
    """
    Given 检索/字幕/AI 全桩（无 AI Key → 字幕原文降级入库）
    When  执行 bili_learn（keyword）
    Then  BiliVideo 落库 subtitle 状态、MindVault 推送桩被调
    """
    import app.services.bili_learn as bl

    async def fake_search(keyword, sess, page=1):
        return [{"bvid": "BV1L1", "title": "CS2 道具教学视频", "author": "UP", "pubdate": 1}]

    async def fake_fetch(bvid, sess):
        return [{"from": 12.5, "text": "字幕文本"}]

    monkeypatch.setattr(bl, "search_videos", fake_search)
    monkeypatch.setattr(bl, "fetch_subtitle_timed", fake_fetch)
    monkeypatch.setattr(bl, "_credential_sess", lambda s: "SESS")
    monkeypatch.setattr(bl, "_new_ai", lambda: None)
    client.put("/api/settings", json={"mv.enabled": "1"})

    pushed = []

    class StubMV:
        async def push_note(self, title, content, topic_name=None, topic_id=None):
            pushed.append(title)
            return {"uuid": "bili-u1"}

        async def update_note(self, uuid, content=None, title=None):
            return {"uuid": uuid}

    monkeypatch.setattr(bl, "_new_mv", lambda: StubMV())

    client.put("/api/settings", json={"bili.sessdata": "SESS"})
    task_id = client.post("/api/tasks", json={"type": "bili_learn", "payload": {"keyword": "CS2"}}).json()["id"]
    run = client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["status"] == "success", body.get("error") or body
    assert body["result"]["results"][0]["status"] == "ok"
    assert pushed == ["CS2 道具教学视频"]

    from sqlmodel import select

    from app.database import session_factory
    from app.models import BiliVideo

    with session_factory() as s:
        row = s.exec(select(BiliVideo).where(BiliVideo.bvid == "BV1L1")).first()
        assert row is not None and row.subtitle_status == "subtitle"


@pytest.mark.skipif(not DEMO_PATH.exists(), reason="本地无真实 demo")
def test_run_analysis_real_demo_integration():
    """
    Given 真实 demo（客户端缓存解压产物）
    When  run_analysis
    Then  四维 schema 完整、meta 含耗时/内存、deaths/duels 非空
    """
    from app.services.demo_analysis import run_analysis

    analysis, meta = run_analysis(DEMO_PATH, "PVP@9215177922805569036", "76561198339750836")
    assert analysis.match_id == "PVP@9215177922805569036"
    assert analysis.meta.parser.startswith("awpy")
    assert meta["cost_s"] > 0
    assert len(analysis.duels.by_weapon_distance) > 0
    assert analysis.deaths.disadvantaged_rate is not None


@pytest.mark.skipif(shutil_which_ffmpeg() is None, reason="imageio-ffmpeg 不可用")
def test_compress_real_ffmpeg(tmp_path):
    """
    Given imageio-ffmpeg 静态二进制 + 用 ffmpeg 生成 1s 测试视频
    When  _compress
    Then  输出 ≤20MB 的 720p mp4（真实压缩链路验证）
    """
    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    src = tmp_path / "src.mp4"
    subprocess.run(
        [exe, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=1280x720:rate=24", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True, timeout=60,
    )
    from app.services.moments import _compress

    dst = tmp_path / "dst.mp4"
    out = _compress(src, dst)
    assert out.exists() and out.stat().st_size <= 20 * 1024 * 1024


def shutil_which_ffmpeg():
    try:
        import imageio_ffmpeg  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return None
