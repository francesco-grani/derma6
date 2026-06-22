"""HITL resume endpoint: POST /api/chat/resume."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent.graph import stream_resume_response
from backend.auth import get_current_user

router = APIRouter(tags=["hitl"])


class ResumeRequest(BaseModel):
    session_id: str
    run_id: str
    choice: str  # "confirm" | "rename" | "cancel"
    note: str = ""


@router.post("/api/chat/resume")
async def resume_chat(req: ResumeRequest, username: str = Depends(get_current_user)):
    return StreamingResponse(
        stream_resume_response(username, req.session_id, req.run_id, req.choice, req.note),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
