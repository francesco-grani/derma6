"""Routines routes: GET / DELETE / PATCH /api/me/routines."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.deps import get_profile_store
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import RenameRequest, RoutineSchema

router = APIRouter(prefix="/api/me", tags=["routines"])


@router.get("/routines", response_model=list[RoutineSchema])
def list_routines(
    username: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    try:
        return store.get_all_routines(username)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/routines/{name}", status_code=204)
def delete_routine(
    name: str,
    username: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    try:
        store.delete_routine(username, name)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/routines/{name}")
def rename_routine(
    name: str,
    body: RenameRequest,
    username: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="New name must not be empty.")
    try:
        store.rename_routine(username, name, new_name)
        return {"name": new_name}
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
