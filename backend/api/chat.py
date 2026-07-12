"""Chat endpoints: POST /api/chat (SSE stream) + GET /api/me/chat/history."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.agent.graph import stream_agent_response
from backend.auth import get_current_user
from backend.db.chat_history import serialise_history
from backend.db.deps import get_session_store
from backend.db.session_store import SessionStore
from backend.middleware.content_filter import check_chat_content
from backend.schemas import ChatHistoryMessage, ChatRequest

router = APIRouter(tags=["chat"])


def _require_session_owner(session_id: str, user_id: str, session_store: SessionStore) -> None:
    """Security-remediation Req 19.1/19.2: every session_id in this app is
    created up front via POST /api/me/sessions before it's ever used in a chat
    request (frontend/src/lib/sessionContext.tsx), so a missing or
    foreign-owned session_id here is never a legitimate not-yet-created one —
    404 either way, so a caller can't distinguish "doesn't exist" from
    "belongs to someone else"."""
    owner = session_store.get_session_owner(session_id)
    if owner is None or owner != user_id:
        raise HTTPException(status_code=404, detail="Session not found.")


@router.post("/api/chat")
async def chat(
    req: ChatRequest,
    user_id: str = Depends(get_current_user),
    _: None = Depends(check_chat_content),
    session_store: SessionStore = Depends(get_session_store),
):
    _require_session_owner(req.session_id, user_id, session_store)
    return StreamingResponse(
        stream_agent_response(user_id, req.message, req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/me/chat/history", response_model=list[ChatHistoryMessage])
def chat_history(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
):
    """Return persisted chat history for a session."""
    _require_session_owner(session_id, user_id, session_store)
    messages = serialise_history(session_id)
    return [
        ChatHistoryMessage(
            role="user" if m["role"] == "human" else "assistant",
            content=m["content"],
        )
        for m in messages
    ]
