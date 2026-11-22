from fastapi import APIRouter

from ..database import SessionDep
from ..services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def list_settings(session: SessionDep) -> dict[str, str]:
    """设置列表（secret 脱敏）。"""
    return settings_service.get_all_masked(session)


@router.get("/detail")
def settings_detail(session: SessionDep) -> dict[str, str]:
    """明文设置（仅供面板编辑回显；不暴露给公网匿名访问场景）。"""
    return settings_service.get_detail(session)


@router.put("")
def update_settings(body: dict[str, str], session: SessionDep) -> dict[str, str]:
    for key, value in body.items():
        if value is None:
            continue
        settings_service.set_value(session, key, str(value))
    return settings_service.get_all_masked(session)
