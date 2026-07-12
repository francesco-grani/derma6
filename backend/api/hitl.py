"""HITL resume endpoint: POST /api/chat/resume."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.agent.graph import get_run_owner, stream_resume_response
from backend.auth import get_current_user
from backend.db.deps import get_session_store
from backend.db.session_store import SessionStore
from backend.middleware.content_filter import check_resume_content
from backend.schemas import ResumeRequest

router = APIRouter(tags=["hitl"])


@router.post("/api/chat/resume")
async def resume_chat(
    req: ResumeRequest,
    user_id: str = Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
    _: None = Depends(check_resume_content),
):
    # Security-remediation Req 19.3/19.4: run_id is only ever surfaced to a
    # client via the SSE `interrupt` event stamped from this same user's own
    # graph_config metadata (see get_run_owner()'s docstring) — 404 (not 403)
    # for both "unknown" and "belongs to someone else" so a caller can't use
    # this endpoint to enumerate which run_ids exist.
    run_owner = await get_run_owner(req.run_id)
    if run_owner is None or run_owner != user_id:
        raise HTTPException(status_code=404, detail="Run not found.")

    # session_id is trusted separately from run_id below this point (graph.py's
    # stream_resume_response persists the resumed answer via
    # get_history(session_id).add_ai_message(...)) — a caller who owns a
    # legitimate run_id could otherwise still smuggle a foreign session_id and
    # have the resumed output appended to someone else's chat history.
    session_owner = session_store.get_session_owner(req.session_id)
    if session_owner is None or session_owner != user_id:
        raise HTTPException(status_code=404, detail="Session not found.")

    return StreamingResponse(
        stream_resume_response(user_id, req.session_id, req.run_id, req.choice, req.note),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
