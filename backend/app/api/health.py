from fastapi import APIRouter

from ..config import APP_VERSION

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}
