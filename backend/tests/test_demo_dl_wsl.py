"""RED: demo 获取支持 WSL 跨系统扫描（Linux 容器读 Windows 完美客户端缓存）。

背景（2026-11-24 实测）：CS2HQ 后端跑在 WSL2 Linux Docker，完美客户端在 Windows
（/mnt/c/Users/will.li/AppData/Roaming/Wmpvp/demo）。原实现只扫 APPDATA（Windows 语义），
容器内该目录不存在 → 永远 pending_demo。本次配置：
1. 新环境变量 CS2HQ_CLIENT_DEMO_DIR 指定客户端缓存目录（优先级最高）
2. client_demo_dir() 依次探测：显式配置 → Windows APPDATA → WSL /mnt/c 默认路径
3. docker-compose 挂载 Windows 客户端缓存为只读卷
"""
from __future__ import annotations

import zipfile

import pytest

from app.services.demo_dl import (
    DemoNotAvailableError,
    acquire_demo,
    client_demo_dir,
)


@pytest.fixture()
def wsl_demo_dir(tmp_path, monkeypatch):
    """伪造 WSL 挂载的 Windows 客户端目录。"""
    d = tmp_path / "wsl-wmpvp-demo"
    d.mkdir()
    return d


def test_client_demo_dir_env_override(wsl_demo_dir, monkeypatch):
    """
    Given 环境变量 CS2HQ_CLIENT_DEMO_DIR 指向目录 X
    When  client_demo_dir()
    Then  返回 X（显式配置优先级最高）
    """
    monkeypatch.setenv("CS2HQ_CLIENT_DEMO_DIR", str(wsl_demo_dir))
    assert client_demo_dir() == wsl_demo_dir


def test_client_demo_dir_wsl_default_when_no_appdata(wsl_demo_dir, monkeypatch):
    """
    Given APPDATA 未设置（Linux 容器）且显式配置未设
    When  client_demo_dir()
    Then  依次探测 WSL 常见挂载路径（/mnt/c/Users/*/AppData/Roaming/Wmpvp/demo），
          存在的第一个胜出；都不存在时回退 ~/AppData/Roaming/Wmpvp/demo（保持原语义）
    """
    monkeypatch.delenv("CS2HQ_CLIENT_DEMO_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(
        "app.services.demo_dl._WSL_DEMO_GLOBS",
        [wsl_demo_dir, wsl_demo_dir.parent / "nope"],
    )
    assert client_demo_dir() == wsl_demo_dir


def test_client_demo_dir_falls_back_home_semantics(wsl_demo_dir, monkeypatch, tmp_path):
    """
    Given 显式配置与 WSL 挂载都不存在
    When  client_demo_dir()
    Then  回退原语义（APPDATA 或 ~/AppData/Roaming/Wmpvp/demo），不抛错
    """
    monkeypatch.delenv("CS2HQ_CLIENT_DEMO_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr("app.services.demo_dl._WSL_DEMO_GLOBS", [])
    monkeypatch.setenv("HOME", str(tmp_path))
    out = client_demo_dir()
    assert out == tmp_path / "AppData" / "Roaming" / "Wmpvp" / "demo"


def test_acquire_demo_from_wsl_mount(wsl_demo_dir, tmp_path, monkeypatch):
    """
    Given WSL 挂载目录里有该场 zip（Windows 客户端下载）
    When  acquire_demo
    Then  正常解压到 CS2HQ 缓存（跨系统扫描行为与本地目录一致）
    """
    zip_path = wsl_demo_dir / "9215177922805569036_0.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("9215177922805569036_0.dem", b"wsl-fake-dem")
    monkeypatch.setenv("CS2HQ_CLIENT_DEMO_DIR", str(wsl_demo_dir))
    out = acquire_demo("PVP@9215177922805569036", cache_dir=tmp_path / "cache")
    assert out.read_bytes() == b"wsl-fake-dem"
