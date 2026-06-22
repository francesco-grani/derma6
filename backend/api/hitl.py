"""HITL resume endpoint: POST /api/chat/resume."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.agent.graph import stream_resume_response
from backend.auth import get_current_user
from backend.schemas import ResumeRequest

router = APIRouter(tags=["hitl"])


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
