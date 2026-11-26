from fastapi import APIRouter, Depends

from . import auth_api, bili_api, chat_api, health, matches_api, profile_api, settings_api, tasks_api, wanmei_api
from ..services import bili_learn, demo_analyze, demo_fetch, moments, training, wanmei_sync, weekly

wanmei_sync.register()
demo_analyze.register()
bili_learn.register()
moments.register()
weekly.register()
training.register()
demo_fetch.register()

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth_api.router)
# 业务路由统一登录门禁（Phase 2，2026-11-26）：health/auth 之外全部要求登录
_gated = [Depends(auth_api.get_current_user)]
api_router.include_router(settings_api.router, dependencies=_gated)
api_router.include_router(tasks_api.router, dependencies=_gated)
api_router.include_router(profile_api.router, dependencies=_gated)
api_router.include_router(matches_api.router, dependencies=_gated)
api_router.include_router(wanmei_api.router, dependencies=_gated)
api_router.include_router(bili_api.router, dependencies=_gated)
api_router.include_router(chat_api.router, dependencies=_gated)
