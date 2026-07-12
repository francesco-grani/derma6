"""Profile routes: GET /api/me/profile, PATCH /api/me/profile."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.deps import get_profile_store
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import ProfilePatch, UserProfile

router = APIRouter(prefix="/api/me", tags=["profile"])


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
    # security-remediation Req 23.1, 23.2: a single atomic call — see
    # ProfileStore.apply_patch's docstring for why this replaced a sequence
    # of independent per-field update_* calls.
    try:
        return store.apply_patch(user_id, patch)
    except ProfileStoreError as exc:
        detail = str(exc)
        status_code = 422 if "beard_style" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from exc
