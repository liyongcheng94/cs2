from fastapi import APIRouter

from . import bili_api, chat_api, health, matches_api, profile_api, settings_api, tasks_api, wanmei_api
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
api_router.include_router(settings_api.router)
api_router.include_router(tasks_api.router)
api_router.include_router(profile_api.router)
api_router.include_router(matches_api.router)
api_router.include_router(wanmei_api.router)
api_router.include_router(bili_api.router)
api_router.include_router(chat_api.router)
