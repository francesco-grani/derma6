"""Chat endpoints: POST /api/chat (SSE stream) + GET /api/me/chat/history."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent.graph import stream_agent_response
from backend.auth import get_current_user
from backend.db.chat_history import serialise_history

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str


@router.post("/api/chat")
async def chat(req: ChatRequest, username: str = Depends(get_current_user)):
    return StreamingResponse(
        stream_agent_response(username, req.message, req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/me/chat/history")
def chat_history(session_id: str, username: str = Depends(get_current_user)):
    """Return persisted chat history for a session."""
    messages = serialise_history(session_id)
    return [
        {
            "role": "user" if m["role"] == "human" else "assistant",
            "content": m["content"],
        }
        for m in messages
    ]
