from fastapi import APIRouter, HTTPException

from ..database import SessionDep
from ..models import PlayerProfile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
def get_profile(session: SessionDep) -> dict:
    profile = session.get(PlayerProfile, "baseline")
    if profile is None:
        raise HTTPException(status_code=404, detail="画像未初始化")
    return {"key": profile.key, "data": profile.data, "updated_at": profile.updated_at.isoformat()}
