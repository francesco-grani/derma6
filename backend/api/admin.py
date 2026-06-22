"""Admin routes: user list with cost, eval dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.config import settings
from backend.db.models import ChatSession, User, engine

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_EVAL_DATASET_PATH = _PROJECT_ROOT / "eval" / "golden_dataset.json"
_EVAL_RUNNER_PATH = _PROJECT_ROOT / "eval" / "run_eval_json.py"

_eval_state: dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "completed_at": None,
    "results": None,
    "error": None,
    "progress": [],
}


# ── Models ────────────────────────────────────────────────────────────────────

class UserSummary(BaseModel):
    id: int
    username: str
    skin_type: Optional[str]
    skin_concerns: Optional[str]
    has_shaving_routine: Optional[bool]
    medical_flags: Optional[str]
    onboarding_complete: bool
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float

    model_config = {"from_attributes": True}


# ── Auth guard ────────────────────────────────────────────────────────────────

def require_admin(username: str = Depends(get_current_user)) -> str:
    if username != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return username


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserSummary])
def list_users(_: str = Depends(require_admin)):
    with Session(engine) as session:
        users = session.query(User).order_by(User.id).all()
        result: list[UserSummary] = []
        for u in users:
            agg = (
                session.query(
                    func.coalesce(func.sum(ChatSession.total_prompt_tokens), 0),
                    func.coalesce(func.sum(ChatSession.total_completion_tokens), 0),
                    func.coalesce(func.sum(ChatSession.total_cost_usd), 0.0),
                )
                .filter(ChatSession.user_id == u.id)
                .one()
            )
            result.append(
                UserSummary(
                    id=u.id,
                    username=u.username,
                    skin_type=u.skin_type,
                    skin_concerns=u.skin_concerns,
                    has_shaving_routine=u.has_shaving_routine,
                    medical_flags=u.medical_flags,
                    onboarding_complete=u.onboarding_complete,
                    total_prompt_tokens=int(agg[0]),
                    total_completion_tokens=int(agg[1]),
                    total_cost_usd=float(agg[2]),
                )
            )
        return result


# ── Eval dashboard ────────────────────────────────────────────────────────────

@router.get("/eval/golden")
def get_golden_dataset(_: str = Depends(require_admin)):
    if not _EVAL_DATASET_PATH.exists():
        raise HTTPException(status_code=404, detail="Golden dataset not found.")
    with _EVAL_DATASET_PATH.open() as f:
        return json.load(f)


@router.get("/eval/status")
def get_eval_status(_: str = Depends(require_admin)) -> dict[str, Any]:
    return _eval_state


@router.post("/eval/run", status_code=202)
async def run_eval(
    background_tasks: BackgroundTasks,
    _: str = Depends(require_admin),
):
    if _eval_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Eval already running.")
    background_tasks.add_task(_run_eval_background)
    return {"message": "Eval started."}


async def _run_eval_background() -> None:
    _eval_state.update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "results": None,
        "error": None,
        "progress": [],
    })

    # pydantic-settings reads .env into the model but does NOT write to os.environ,
    # so the subprocess wouldn't see OPENROUTER_API_KEY without this explicit injection.
    env = {**os.environ, "OPENAI_API_KEY": settings.openrouter_api_key, "OPENAI_BASE_URL": settings.openrouter_base_url}

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_EVAL_RUNNER_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout_buf: list[bytes] = []

        async def _drain_stdout() -> None:
            data = await proc.stdout.read()
            stdout_buf.append(data)

        async def _stream_stderr() -> None:
            async for raw_line in proc.stderr:
                line = raw_line.decode(errors="replace").strip()
                if line:
                    _eval_state["progress"].append(line)
                    logger.info("eval: %s", line)

        await asyncio.gather(_drain_stdout(), _stream_stderr())
        await proc.wait()

        if proc.returncode != 0:
            last_lines = "\n".join(_eval_state["progress"][-10:])
            raise RuntimeError(f"Runner exited {proc.returncode}:\n{last_lines}")

        results = json.loads(stdout_buf[0].decode())
        _eval_state.update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "error": None,
        })
        logger.info("Eval completed: %d test cases", len(results))

    except Exception as exc:
        logger.error("Eval run failed: %s", exc)
        _eval_state.update({
            "status": "error",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "results": None,
            "error": str(exc)[:600],
        })
