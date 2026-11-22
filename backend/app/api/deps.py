"""共享依赖：MindVault 客户端按 settings 构建（每次请求新建，生命周期由调用方管理）。"""
from __future__ import annotations

from ..database import SessionDep
from ..services import settings_service
from ..services.mindvault_client import MindVaultClient


def get_mv_client(session: SessionDep) -> MindVaultClient:
    base = settings_service.get_value(session, "mv.base_url") or "http://127.0.0.1:8001"
    pwd = settings_service.get_value(session, "mindvault.password")
    return MindVaultClient(base_url=base, password=pwd or None)
