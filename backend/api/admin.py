"""Admin routes: user list with cost, eval dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.config import settings
from backend.db.deps import get_db
from backend.db.models import ChatSession, User
from backend.schemas import UserSummary

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


# ── Auth guard ────────────────────────────────────────────────────────────────

def require_admin(user_id: str = Depends(get_current_user), db: Session = Depends(get_db)) -> str:
    user = db.get(User, user_id)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user_id


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserSummary])
def list_users(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    result: list[UserSummary] = []
    for u in users:
        agg = (
            db.query(
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
    # Req 26.1/26.2: flip status to "running" synchronously, right here, before
    # scheduling the background task — not inside _run_eval_background() after
    # it starts. Two near-simultaneous requests both run this coroutine on the
    # same event loop with no `await` between the status check and the flip
    # below, so the second request's check always observes the first
    # request's flip rather than a race window where both see "idle".
    if _eval_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Eval already running.")
    _eval_state["status"] = "running"
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


# ── Eval export ───────────────────────────────────────────────────────────────

class _EvalExportBody(dict):
    pass


@router.post("/eval/export/html")
def export_eval_html(body: dict[str, Any], _: str = Depends(require_admin)) -> Response:
    results: list[dict] = body.get("results") or []
    if not results:
        raise HTTPException(status_code=400, detail="No results provided.")
    completed_at: str = body.get("completed_at") or datetime.now(timezone.utc).isoformat()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=_render_eval_html(results, completed_at),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="eval_results_{ts}.html"'},
    )


def _render_eval_html(results: list[dict], completed_at: str) -> str:
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    pass_rate = round(passed / total * 100) if total else 0

    def score_color(score: float, passed: bool) -> str:
        if passed:
            return "#4CAF7D"
        if score >= 0.5:
            return "#F5A623"
        return "#E05252"

    rows_html = ""
    for r in results:
        metrics = r.get("metrics") or []
        metric_cells = "".join(
            f'<td style="padding:4px 8px;font-size:12px;color:{score_color(m.get("score",0), m.get("passed",False))}">'
            f'{m["name"]}: {m.get("score", 0):.2f}'
            f'{"✓" if m.get("passed") else "✗"}'
            f'</td>'
            for m in metrics
        )
        status_color = "#4CAF7D" if r.get("passed") else "#E05252"
        status_label = "PASS" if r.get("passed") else "FAIL"
        rows_html += (
            f'<tr>'
            f'<td style="padding:6px 8px;font-size:12px;color:#9DB09D">{r.get("category","")}</td>'
            f'<td style="padding:6px 8px;font-size:12px;color:#C8D8C8">{r.get("test_name","")}</td>'
            f'<td style="padding:6px 8px;font-size:12px;color:#9DB09D">{r.get("tool","")}</td>'
            f'<td style="padding:6px 8px;font-size:12px;color:#C8D8C8;max-width:300px;white-space:pre-wrap">{r.get("input","")}</td>'
            f'{metric_cells}'
            f'<td style="padding:6px 8px;font-size:12px;font-weight:700;color:{status_color}">{status_label}</td>'
            f'</tr>'
        )

    metric_headers = ""
    if results and results[0].get("metrics"):
        metric_headers = "".join(
            f'<th style="padding:6px 8px;text-align:left;color:#7A9A7A;font-weight:600;font-size:12px">{m["name"]}</th>'
            for m in results[0]["metrics"]
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Derma6 Eval Results</title>
<style>
  body {{ background:#1A2420; color:#C8D8C8; font-family: system-ui, sans-serif; margin: 0; padding: 24px; }}
  h1 {{ color:#E0F0E0; font-size:22px; margin-bottom:4px; }}
  .meta {{ color:#7A9A7A; font-size:13px; margin-bottom:24px; }}
  .stats {{ display:flex; gap:16px; margin-bottom:24px; }}
  .stat {{ background:#243028; border:1px solid #2E4035; border-radius:8px; padding:12px 20px; }}
  .stat-val {{ font-size:28px; font-weight:700; }}
  .stat-lbl {{ font-size:12px; color:#7A9A7A; margin-top:2px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ padding:6px 8px; text-align:left; background:#243028; color:#7A9A7A; font-weight:600; font-size:12px; }}
  tr:nth-child(even) {{ background:#1E2C28; }}
  tr:hover {{ background:#243028; }}
</style>
</head>
<body>
<h1>Derma6 Eval Results</h1>
<p class="meta">Run completed: {completed_at}</p>
<div class="stats">
  <div class="stat"><div class="stat-val">{total}</div><div class="stat-lbl">Total</div></div>
  <div class="stat"><div class="stat-val" style="color:#4CAF7D">{passed}</div><div class="stat-lbl">Passed</div></div>
  <div class="stat"><div class="stat-val" style="color:#E05252">{total - passed}</div><div class="stat-lbl">Failed</div></div>
  <div class="stat"><div class="stat-val" style="color:{"#4CAF7D" if pass_rate >= 80 else "#F5A623" if pass_rate >= 60 else "#E05252"}">{pass_rate}%</div><div class="stat-lbl">Pass Rate</div></div>
</div>
<table>
<thead><tr>
  <th>Category</th><th>Test</th><th>Tool</th><th>Input</th>
  {metric_headers}
  <th>Status</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body>
</html>"""
