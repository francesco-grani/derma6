"""Session management — GET/POST/DELETE /api/me/sessions."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.profile_store import ProfileStore
from backend.db.session_store import SessionStore, SessionStoreError
from backend.schemas import ChatSessionInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["sessions"])


@router.get("/sessions", response_model=list[ChatSessionInfo])
def list_sessions(username: str = Depends(get_current_user)):
    ProfileStore().get_or_create_user(username)
    try:
        rows = SessionStore().get_sessions(username)
        return [ChatSessionInfo(**r) for r in rows]
    except SessionStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sessions", response_model=ChatSessionInfo, status_code=201)
def create_session(username: str = Depends(get_current_user)):
    ProfileStore().get_or_create_user(username)
    try:
        store = SessionStore()
        session_id = store.create_session(username)
        rows = store.get_sessions(username)
        row = next((r for r in rows if r["session_id"] == session_id), None)
        if row is None:
            raise SessionStoreError("Session not found after creation.")
        return ChatSessionInfo(**row)
    except SessionStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, username: str = Depends(get_current_user)):
    try:
        SessionStore().delete_session(session_id, username)
    except SessionStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
