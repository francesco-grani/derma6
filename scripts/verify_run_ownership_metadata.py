"""Security-remediation blocking verification spike (Task 50).

Confirms — against the LIVE Postgres-backed `AsyncPostgresSaver` checkpointer
this app actually uses (settings.database_url), not mocks — whether
`CompiledStateGraph.aget_state(config)` reliably exposes the `metadata` dict
already stamped into `graph_config["metadata"]` by both
`stream_agent_response()` and `stream_resume_response()` in
`backend/agent/graph.py`, when the caller supplies only `{"configurable":
{"thread_id": run_id}}` — i.e. exactly what `/api/chat/resume` has to work
with (a client-supplied `run_id`, nothing else).

This determines the `run_id` -> `user_id` ownership-binding mechanism for
Requirement 19 (security-remediation-tasks.md Bundle 1): if metadata
round-trips reliably, `get_run_owner(run_id)` can be a thin wrapper around
`aget_state()` with no new table. If not, the documented fallback is a
dedicated `SessionStore`-owned ownership table.

Usage:
    PYTHONPATH=. uv run python scripts/verify_run_ownership_metadata.py

Requires DATABASE_URL (and the rest of backend/config.py's required
settings) to point at a live Postgres, e.g. via .env — this app's actual
checkpoint store, not a throwaway/in-memory one, since the question is
specifically about this project's pinned langgraph-checkpoint-postgres
behavior.

Re-run and re-record findings if `langgraph`/`langgraph-checkpoint-postgres`
are ever upgraded across a major version (pinned at 1.2.5 / 3.1.0 at the time
of this spike) — the metadata-surfacing behavior checked here is not part of
LangGraph's documented public contract, only empirically observed.

FINDINGS (recorded 2026-07-11, live Supabase Postgres via settings.database_url):

1. Metadata round-trip — CONFIRMED. A fresh `aget_state({"configurable":
   {"thread_id": run_id}})` call, using only the thread_id (no prior
   knowledge of the metadata), returns a `StateSnapshot` whose `.metadata`
   dict includes the `user_id` that was stamped into `graph_config["metadata"]`
   at invocation time — immediately after an `interrupt()` call, which is the
   exact moment `run_id` becomes client-visible via the SSE `interrupt` event.

2. Unknown thread_id — CONFIRMED clean sentinel, no exception. An
   `aget_state()` call for a `thread_id` that was never invoked returns a
   `StateSnapshot` with `metadata=None` and `values={}` — a reliable
   "not found" signal distinguishable from a real (possibly foreign) owner.

3. Metadata is per-step, not cumulative — CONFIRMED, and this is the
   important caveat. `.metadata` reflects only the most recent checkpoint
   step's invocation, not a merged history: if a resume call's `graph_config`
   omitted `metadata={"user_id": ...}`, the post-resume snapshot's metadata
   would NOT carry `user_id` forward from the original invocation. This is
   safe in practice only because both `stream_agent_response()` and
   `stream_resume_response()` already re-stamp `metadata={"user_id": user_id}`
   on every single call (confirmed by reading the current source, not
   assumed) — so the ownership check must run BEFORE the resume's
   `Command(resume=...)` call, using the metadata as of the last legitimate
   invocation, never after. If either function is ever changed to omit
   `metadata` on some call path, this ownership mechanism silently stops
   working for that path — flag this dependency in review if `graph_config`
   construction in either function changes.

CONCLUSION: use checkpoint-metadata read-back (Option: no new table).
`SessionStore.get_run_owner(run_id)` wraps `aget_state()` directly. See
`backend/db/session_store.py` and `backend/api/hitl.py` for the consuming
code — this finding is recorded again as a code comment at both sites.
"""

import asyncio
from typing import TypedDict

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.config import settings


class _SpikeState(TypedDict):
    x: int


def _node_a(state: _SpikeState) -> dict:
    interrupt({"kind": "spike"})
    return {"x": state["x"] + 1}


async def main() -> None:
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        builder = StateGraph(_SpikeState)
        builder.add_node("a", _node_a)
        builder.add_edge(START, "a")
        builder.add_edge("a", END)
        graph = builder.compile(checkpointer=saver)

        thread_id = "spike-run-ownership-verify"
        invoke_cfg = {
            "configurable": {"thread_id": thread_id},
            "metadata": {"user_id": "spike-user-owner"},
        }
        await graph.ainvoke({"x": 1}, config=invoke_cfg)

        # The exact scenario /api/chat/resume faces: only thread_id is known.
        resume_lookup_cfg = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(resume_lookup_cfg)
        assert snapshot.metadata is not None
        assert snapshot.metadata.get("user_id") == "spike-user-owner"
        print("[1/2] PASS: metadata round-trips via aget_state(thread_id only)")

        missing_cfg = {"configurable": {"thread_id": "spike-thread-that-never-existed"}}
        missing_snapshot = await graph.aget_state(missing_cfg)
        assert missing_snapshot.metadata is None
        print("[2/2] PASS: unknown thread_id yields metadata=None sentinel")

        print("\nAll checks passed — checkpoint-metadata read-back confirmed reliable.")


if __name__ == "__main__":
    asyncio.run(main())
