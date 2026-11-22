"""demo 获取链路契约：客户端 demo 目录扫描 → 解压到本地缓存 → 不可得时 pending_demo 降级。

背景（2026-11-22 实测）：pwaweblogin demo URL 纯逆向不可行（404 + 编译签名器不公开），
改用客户端本地缓存方案：完美客户端把看过的 demo 存为 %APPDATA%/Wmpvp/demo/{纯数字matchId}_0.zip，
zip 内为同名 .dem；用户在客户端点开 demo 即自动下载，CS2HQ 扫描+解压即可。
"""
from __future__ import annotations

import zipfile

import pytest

from app.services.demo_dl import (
    DemoNotAvailableError,
    acquire_demo,
    match_id_to_client_name,
    scan_client_demos,
)


@pytest.fixture()
def client_demo_dir(tmp_path, monkeypatch):
    """伪造客户端 demo 目录：一个可用 zip + 一个无关文件。"""
    d = tmp_path / "wmpvp-demo"
    d.mkdir()
    zip_path = d / "9215177922805569036_0.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("9215177922805569036_0.dem", b"fake-dem-bytes-here")
    (d / "not-a-demo.txt").write_text("noise")
    monkeypatch.setattr("app.services.demo_dl.client_demo_dir", lambda: d)
    return d


def test_match_id_to_client_name():
    """
    Given 完美平台 matchId（PVP@9215...）
    When  match_id_to_client_name
    Then  得到客户端缓存文件名前缀（纯数字 _0）
    """
    assert match_id_to_client_name("PVP@9215177922805569036") == "9215177922805569036_0"


def test_scan_client_demos_maps_match_ids(client_demo_dir):
    """
    Given 客户端 demo 目录有 9215177922805569036_0.zip
    When  scan_client_demos()
    Then  返回 {PVP@9215177922805569036: zip路径}，忽略无关文件
    """
    out = scan_client_demos()
    assert set(out.keys()) == {"PVP@9215177922805569036"}
    assert out["PVP@9215177922805569036"].name == "9215177922805569036_0.zip"


def test_acquire_demo_extracts_to_cache(client_demo_dir, tmp_path, monkeypatch):
    """
    Given 客户端目录有该场的 zip，CS2HQ 缓存目录为空
    When  acquire_demo("PVP@9215177922805569036", cache_dir)
    Then  解压出 .dem 到缓存目录并返回路径；内容与原 zip 一致
    """
    cache = tmp_path / "cs2hq-demos"
    out = acquire_demo("PVP@9215177922805569036", cache_dir=cache)
    assert out.exists() and out.suffix == ".dem"
    assert out.read_bytes() == b"fake-dem-bytes-here"


def test_acquire_demo_idempotent_second_call(client_demo_dir, tmp_path):
    """
    Given 已解压过一次
    When  再次 acquire_demo
    Then  直接返回缓存路径（不重复解压，行为幂等）
    """
    cache = tmp_path / "cs2hq-demos"
    first = acquire_demo("PVP@9215177922805569036", cache_dir=cache)
    second = acquire_demo("PVP@9215177922805569036", cache_dir=cache)
    assert first == second


def test_acquire_demo_missing_raises(client_demo_dir, tmp_path):
    """
    Given 客户端与缓存都没有该场的 demo
    When  acquire_demo("PVP@9999999999999999999")
    Then  抛 DemoNotAvailableError（任务层标 pending_demo，提示用户在客户端点开 demo）
    """
    with pytest.raises(DemoNotAvailableError):
        acquire_demo("PVP@9999999999999999999", cache_dir=tmp_path / "cache")
