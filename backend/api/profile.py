"""Profile routes: GET /api/me/profile, PATCH /api/me/profile."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import UserProfile

router = APIRouter(prefix="/api/me", tags=["profile"])

VALID_BEARD_STYLES = {"shave", "trim", "grow"}


class ProfilePatch(BaseModel):
    skin_type: str | None = None
    beard_style: str | None = None
    location: str | None = None
    skin_concerns: list[str] | None = None


@router.get("/profile", response_model=UserProfile)
def get_profile(username: str = Depends(get_current_user)):
    try:
        store = ProfileStore()
        store.get_or_create_user(username)
        return store.get_profile(username)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/profile", response_model=UserProfile)
def patch_profile(patch: ProfilePatch, username: str = Depends(get_current_user)):
    try:
        store = ProfileStore()
        if patch.skin_type is not None:
            store.update_skin_type(username, patch.skin_type.strip())
        if patch.beard_style is not None:
            if patch.beard_style not in VALID_BEARD_STYLES:
                raise HTTPException(status_code=422, detail=f"beard_style must be one of {VALID_BEARD_STYLES}")
            store.update_beard_style(username, patch.beard_style)
        if patch.location is not None:
            store.update_location(username, patch.location.strip())
        if patch.skin_concerns is not None:
            store.update_skin_concerns(username, [c.strip() for c in patch.skin_concerns if c.strip()])
        return store.get_profile(username)
    except HTTPException:
        raise
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
