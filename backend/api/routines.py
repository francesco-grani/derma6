"""Routines routes: GET / DELETE / PATCH /api/me/routines."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.deps import get_profile_store
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import RenameRequest, RoutineSchema

router = APIRouter(prefix="/api/me", tags=["routines"])


@router.get("/routines", response_model=list[RoutineSchema])
def list_routines(
    user_id: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    try:
        return store.get_all_routines(user_id)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/routines/{name}", status_code=204)
def delete_routine(
    name: str,
    user_id: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    try:
        store.delete_routine(user_id, name)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/routines/{name}")
def rename_routine(
    name: str,
    body: RenameRequest,
    user_id: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="New name must not be empty.")
    try:
        store.rename_routine(user_id, name, new_name)
        return {"name": new_name}
    except ProfileStoreError as exc:
        # security-remediation Req 25.3: a name collision is a structured,
        # distinguishable 409 rather than a generic 500 — RoutinesPage.tsx
        # (Req 25.4) branches on this to show a specific message.
        detail = str(exc)
        status_code = 409 if "already exists" in detail else 500
        raise HTTPException(status_code=status_code, detail=detail) from exc
