"""完美时刻：扫描用户导出目录 → ≤20MB 直推 / 超限 ffmpeg(-preset veryfast,720p) 压缩 → MindVault capture/videos。

获取方式与 demo 同构（客户端协作）：用户在完美客户端导出时刻 mp4 到 moments.dir（settings 配置），
本服务扫描推送；getPersonalMoments 端点未公开（404），抓包方案留待后续（不阻塞）。
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Callable

from loguru import logger
from sqlmodel import Session, select

from ..config import get_project_root
from ..database import session_factory
from ..models import Clip, Task, utcnow
from . import settings_service
from .mindvault_client import MindVaultClient

MAX_BYTES = 20 * 1024 * 1024
FFMPEG_EXE = get_project_root() / "backend" / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"


def moments_dir() -> Path:
    """用户导出时刻的目录（settings moments.dir，默认 data/moments）。"""
    from ..config import get_data_dir

    configured = settings_service.get_value(_session(), "moments.dir")
    d = Path(configured) if configured else get_data_dir() / "moments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session() -> Session:
    return session_factory()


def scan_moments_dir(d: Path | None = None) -> list[Path]:
    d = d or moments_dir()
    return sorted(d.glob("*.mp4"))


def _new_mv() -> MindVaultClient:
    with session_factory() as session:
        base = settings_service.get_value(session, "mv.base_url")
        pwd = settings_service.get_value(session, "mindvault.password")
    return MindVaultClient(base_url=base or "http://127.0.0.1:8001", password=pwd or None)


def _compress(src: Path, dst: Path) -> Path:
    """ffmpeg 压缩至 ≤20MB（720p/CRF28/-preset veryfast，评审约定；阻塞调用，须在 to_thread 中）。"""
    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        exe, "-y", "-i", str(src), "-vf", "scale=-2:720", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k", str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    if dst.stat().st_size > MAX_BYTES:
        raise ValueError(f"压缩后仍超 20MB：{dst.stat().st_size}")
    return dst


async def push_clip(mv: MindVaultClient, src: Path, moment_id: str, session: Session) -> dict:
    """单条时刻推送：直推或压缩后推；落 Clip 行；临时压缩文件用后即删。"""
    if session.exec(select(Clip).where(Clip.moment_id == moment_id)).first() is not None:
        return {"skipped": True, "moment_id": moment_id}

    tmp = Path(src).with_suffix(".compressed.mp4")
    preset = "raw"
    upload_path = Path(src)
    try:
        if src.stat().st_size > MAX_BYTES:
            preset = "720p"
            await asyncio.to_thread(_compress, src, tmp)
            upload_path = tmp
        body = await mv.capture_video(str(upload_path), title=src.stem, preset=preset)
        clip = Clip(
            moment_id=moment_id,
            title=src.stem,
            local_path=str(src),
            size_bytes=src.stat().st_size,
            push_status="pushed",
            mv_uuid=body.get("item_uuid") or body.get("uuid"),
        )
        session.add(clip)
        session.commit()
        return {"skipped": False, "moment_id": moment_id, "uuid": clip.mv_uuid, "preset": preset}
    finally:
        if tmp.exists():
            tmp.unlink()


async def moments_sync_handler(task: Task, session_factory_fn: Callable[[], Session]) -> dict:
    mv = _new_mv()
    pushed = skipped = failed = 0
    with session_factory_fn() as session:
        files = scan_moments_dir()
        for f in files:
            moment_id = f.stem
            try:
                out = await push_clip(mv, f, moment_id, session)
                if out.get("skipped"):
                    skipped += 1
                else:
                    pushed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning(f"[时刻] {f.name} 推送失败：{exc}")
    logger.info(f"[时刻] 同步完成 pushed={pushed} skipped={skipped} failed={failed}")
    return {"pushed": pushed, "skipped": skipped, "failed": failed}


def register() -> None:
    from . import task_manager

    task_manager.HANDLERS["moments_sync"] = moments_sync_handler
