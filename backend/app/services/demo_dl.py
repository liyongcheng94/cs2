"""demo 获取：扫描完美客户端本地缓存（%APPDATA%/Wmpvp/demo/{matchNum}_0.zip）→ 解压到 CS2HQ 缓存。

pwaweblogin 的 demo 下载 URL 纯逆向不可行（签名器为不公开编译产物，实测 404），
故采用客户端协作方案：用户在客户端点开 demo 观看即自动下载，本服务扫描+解压。
拿不到的场次由任务层标 pending_demo，面板提示用户去客户端点开。
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from loguru import logger


class DemoNotAvailableError(Exception):
    """客户端与本地缓存都没有该场 demo（提示用户在完美客户端里点开该场 demo 观看）。"""


def client_demo_dir() -> Path:
    """完美客户端 demo 缓存目录（Windows：%APPDATA%/Wmpvp/demo）。"""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Wmpvp" / "demo"


def match_id_to_client_name(match_id: str) -> str:
    """PVP@9215177922805569036 → 客户端缓存文件名前缀 9215177922805569036_0。"""
    num = match_id.split("@", 1)[-1]
    return f"{num}_0"


def scan_client_demos(demo_dir: Path | None = None) -> dict[str, Path]:
    """扫描客户端缓存：返回 {PVP@{num}: zip路径}（文件名格式 {纯数字matchId}_{cup_id}.zip）。"""
    d = demo_dir or client_demo_dir()
    out: dict[str, Path] = {}
    if not d.exists():
        return out
    for f in sorted(d.glob("*_*.zip")):
        stem = f.name[: -len(".zip")]
        num, _, cup = stem.rpartition("_")
        if num.isdigit() and cup.isdigit():
            out[f"PVP@{num}"] = f
    return out


def _extract(zip_path: Path, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        dem_names = [n for n in z.namelist() if n.lower().endswith(".dem")]
        if not dem_names:
            raise DemoNotAvailableError(f"zip 内没有 .dem：{zip_path.name}")
        name = dem_names[0]
        target = cache_dir / Path(name).name
        if not target.exists():
            with z.open(name) as src, open(target, "wb") as dst:
                dst.write(src.read())
        logger.info(f"[demo] 解压完成 {zip_path.name} -> {target}")
        return target


def acquire_demo(match_id: str, cache_dir: Path | None = None) -> Path:
    """获取指定场次的 .dem 本地路径；不可得时抛 DemoNotAvailableError。

    优先级：CS2HQ 缓存（幂等）> 客户端缓存 zip 解压。
    """
    from ..config import get_data_dir

    cache = cache_dir or (get_data_dir() / "demos")
    prefix = match_id_to_client_name(match_id)
    cached = cache / f"{prefix}.dem"
    if cached.exists():
        return cached
    client_dir = client_demo_dir()
    zip_path = client_dir / f"{prefix}.zip"
    if zip_path.exists():
        return _extract(zip_path, cache)
    raise DemoNotAvailableError(
        f"本地与客户端缓存都没有 {match_id} 的 demo；请在完美客户端「对局回放」里点开该场 demo 观看（客户端会自动下载），随后重试"
    )
