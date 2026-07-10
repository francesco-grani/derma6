"""Session management — GET/POST/DELETE /api/me/sessions."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.db.deps import get_session_store
from backend.db.session_store import SessionStore, SessionStoreError
from backend.schemas import ChatSessionInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["sessions"])


@router.get("/sessions", response_model=list[ChatSessionInfo])
def list_sessions(
    user_id: str = Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    try:
        rows = session_store.get_sessions(user_id)
        return [ChatSessionInfo(**r) for r in rows]
    except SessionStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sessions", response_model=ChatSessionInfo, status_code=201)
def create_session(
    user_id: str = Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    try:
        session_id = session_store.create_session(user_id)
        rows = session_store.get_sessions(user_id)
        row = next((r for r in rows if r["session_id"] == session_id), None)
        if row is None:
            raise SessionStoreError("Session not found after creation.")
        return ChatSessionInfo(**row)
    except SessionStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    try:
        session_store.delete_session(session_id, user_id)
    except SessionStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
