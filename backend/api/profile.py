"""Profile routes: GET /api/me/profile."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import UserProfile

router = APIRouter(prefix="/api/me", tags=["profile"])


@router.get("/profile", response_model=UserProfile)
def get_profile(username: str = Depends(get_current_user)):
    try:
        store = ProfileStore()
        store.get_or_create_user(username)
        return store.get_profile(username)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
