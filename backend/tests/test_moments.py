"""完美时刻契约：目录扫描 → 大文件 ffmpeg 压缩（veryfast）→ MindVault capture/videos 推送 → Clip 行。"""
import asyncio
from pathlib import Path

import pytest


@pytest.fixture()
def clips_env(client, monkeypatch, tmp_path):
    """伪造时刻目录：一个 ≤20MB 小文件、一个 >20MB 大文件、一个已推过（按文件名 source_hash 幂等）。"""
    import app.services.moments as mo

    d = tmp_path / "moments"
    d.mkdir()
    small = d / "clip_small.mp4"
    small.write_bytes(b"v" * (5 * 1024 * 1024))  # 5MB
    big = d / "clip_big.mp4"
    big.write_bytes(b"v" * (21 * 1024 * 1024))  # 21MB
    monkeypatch.setattr(mo, "moments_dir", lambda: d)

    pushed = []

    async def fake_capture(self, path, title, preset):
        pushed.append((Path(path).name, preset, Path(path).stat().st_size))
        return {"uuid": f"mv-{Path(path).stem}", "path": f"/api/blobs/x/{Path(path).name}"}

    from app.services.mindvault_client import MindVaultClient

    monkeypatch.setattr(MindVaultClient, "capture_video", fake_capture)
    monkeypatch.setattr(mo, "_new_mv", lambda: MindVaultClient(base_url="http://stub"))

    # 压缩桩：>20MB 输出 19MB 文件并记录调用
    ff_calls = []

    def fake_compress(src: Path, dst: Path):
        ff_calls.append(src.name)
        dst.write_bytes(b"c" * (19 * 1024 * 1024))
        return dst

    monkeypatch.setattr(mo, "_compress", fake_compress)
    return {"dir": d, "small": small, "big": big, "pushed": pushed, "ff_calls": ff_calls}


def test_scan_moments_lists_mp4(clips_env):
    """
    Given 时刻目录有 2 个 mp4
    When  scan_moments_dir()
    Then  返回两个文件路径
    """
    from app.services.moments import scan_moments_dir

    out = scan_moments_dir()
    assert {p.name for p in out} == {"clip_small.mp4", "clip_big.mp4"}


def test_push_clips_small_direct_big_compressed(client, clips_env):
    """
    Given 小于 20MB 直推；大于 20MB 先 ffmpeg 压缩（-preset veryfast）再推
    When  run moments_sync 任务
    Then  两份都推送成功且落 Clip 行；大文件走压缩分支
    """
    from app.database import session_factory
    from app.models import Clip, Task
    from app.services import task_manager

    task_id = client.post("/api/tasks", json={"type": "moments_sync"}).json()["id"]
    run = asyncio.run(task_manager.run_task(task_id))
    assert run.status == "success", run.error

    assert clips_env["ff_calls"] == ["clip_big.mp4"]  # 仅大文件压缩
    assert len(clips_env["pushed"]) == 2
    presets = {p[1] for p in clips_env["pushed"]}
    assert "raw" in presets and "720p" in presets

    with session_factory() as s:
        clips = s.query(Clip).all()
        assert {c.moment_id for c in clips} == {"clip_small", "clip_big"}
        assert all(c.push_status == "pushed" for c in clips)


def test_push_clips_idempotent(client, clips_env):
    """
    Given 同一文件已推过
    When  再跑 moments_sync
    Then  不重复推送（按 moment_id=文件名幂等）
    """
    from app.services import task_manager

    task_id = client.post("/api/tasks", json={"type": "moments_sync"}).json()["id"]
    asyncio.run(task_manager.run_task(task_id))
    task_id2 = client.post("/api/tasks", json={"type": "moments_sync"}).json()["id"]
    run2 = asyncio.run(task_manager.run_task(task_id2))
    assert run2.status == "success"
    assert run2.result["pushed"] == 0  # 二次无新增
