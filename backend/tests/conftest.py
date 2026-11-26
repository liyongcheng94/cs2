"""共享夹具：DATA_DIR 指向临时目录（读取发生在调用时，保证每测试隔离）。"""
from __future__ import annotations

import os
import tempfile

# 模块导入前给一个兜底数据目录（真实每测试隔离在各 fixture 内 monkeypatch）
os.environ.setdefault("CS2HQ_DATA_DIR", tempfile.mkdtemp(prefix="cs2hq-test-"))
os.environ["CS2HQ_SCHEDULER"] = "0"  # 测试禁用错峰调度（防测试间互相触发任务）

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """每测试独立数据目录 + 独立 DB 的 TestClient（含 lifespan 建表与种子）。

    Phase 2（2026-11-26）起业务 API 需登录：夹具自动注册首个用户（即 admin），
    既有测试以 admin 身份运行（可见 legacy 无主数据）。
    """
    monkeypatch.setenv("CS2HQ_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CS2HQ_SECRET_KEY", raising=False)
    with TestClient(create_app()) as c:
        c.post("/api/auth/register", json={"username": "testadmin", "password": "pw123456"})
        yield c


@pytest.fixture
def anyio_backend():
    return "asyncio"
