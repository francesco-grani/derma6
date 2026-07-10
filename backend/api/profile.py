"""Profile routes: GET /api/me/profile, PATCH /api/me/profile."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.deps import get_profile_store
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import ProfilePatch, UserProfile

router = APIRouter(prefix="/api/me", tags=["profile"])

VALID_BEARD_STYLES = {"shave", "trim", "grow"}


@router.get("/profile", response_model=UserProfile)
def get_profile(
    user_id: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    try:
        return store.get_profile(user_id)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/profile", response_model=UserProfile)
def patch_profile(
    patch: ProfilePatch,
    user_id: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    try:
        if patch.skin_type is not None:
            store.update_skin_type(user_id, patch.skin_type.strip())
        if patch.beard_style is not None:
            if patch.beard_style not in VALID_BEARD_STYLES:
                raise HTTPException(status_code=422, detail=f"beard_style must be one of {VALID_BEARD_STYLES}")
            store.update_beard_style(user_id, patch.beard_style)
        if patch.location is not None:
            store.update_location(user_id, patch.location.strip())
        if patch.skin_concerns is not None:
            store.update_skin_concerns(user_id, [c.strip() for c in patch.skin_concerns if c.strip()])
        return store.get_profile(user_id)
    except HTTPException:
        raise
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
