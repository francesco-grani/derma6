"""Routines routes: GET / DELETE / PATCH /api/me/routines."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import RoutineSchema

router = APIRouter(prefix="/api/me", tags=["routines"])


class RenameRequest(BaseModel):
    new_name: str


@router.get("/routines", response_model=list[RoutineSchema])
def list_routines(username: str = Depends(get_current_user)):
    try:
        return ProfileStore().get_all_routines(username)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/routines/{name}", status_code=204)
def delete_routine(name: str, username: str = Depends(get_current_user)):
    try:
        ProfileStore().delete_routine(username, name)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/routines/{name}")
def rename_routine(name: str, body: RenameRequest, username: str = Depends(get_current_user)):
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="New name must not be empty.")
    try:
        ProfileStore().rename_routine(username, name, new_name)
        return {"name": new_name}
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
