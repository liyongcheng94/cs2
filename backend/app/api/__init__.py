from fastapi import APIRouter

from . import health, matches_api, mock, profile_api, settings_api, tasks_api

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(settings_api.router)
api_router.include_router(tasks_api.router)
api_router.include_router(profile_api.router)
api_router.include_router(matches_api.router)
api_router.include_router(mock.router)
