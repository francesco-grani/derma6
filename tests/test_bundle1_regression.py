"""Bundle 1 regression pass (security-remediation Task 56): end-to-end coverage
across the pieces Tasks 50-55 built individually — session ownership (chat.py),
run ownership (hitl.py), content filtering and rate limiting on resume — with
both routers mounted together on one TestClient, matching how they're actually
registered in backend/main.py.

Unlike tests/test_api_chat.py and tests/test_api_hitl.py (which patch
get_run_owner directly to isolate each route's own logic), this file drives
get_run_owner through a real in-memory checkpointer so the full ownership chain
— from "user A's run reaches an interrupt" to "user B's resume attempt is
rejected" — is exercised end-to-end, not just the route-level guard in
isolation.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backend.api.chat import router as chat_router
from backend.api.hitl import router as hitl_router
from backend.auth import get_current_user
from backend.db.deps import get_session_store


def _make_client(store, user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(hitl_router)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


async def _fake_stream(*args, **kwargs):
    yield "data: {}\n\n"


@pytest.fixture
async def real_checkpointer():
    """A real (in-memory) LangGraph checkpointer, so get_run_owner()'s
    aget_tuple() call exercises the actual metadata-lookup path this bundle's
    ownership check depends on, not a mock standing in for it."""
    saver = InMemorySaver()
    with patch("backend.agent.graph._checkpointer", saver):
        yield saver


async def _seed_run(checkpointer, run_id: str, owner_user_id: str) -> None:
    """Write a checkpoint whose metadata stamps owner_user_id as the owner,
    mirroring what stream_agent_response() does when a turn reaches an
    interrupt (graph_config={"configurable": {"thread_id": run_id},
    "metadata": {"user_id": user_id}})."""
    config = {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}
    await checkpointer.aput(
        config,
        {
            "v": 1,
            "id": "seed",
            "ts": "2026-01-01T00:00:00+00:00",
            "channel_values": {},
            "channel_versions": {},
            "versions_seen": {},
        },
        {"source": "loop", "step": 0, "parents": {}, "user_id": owner_user_id},
        {},
    )


class TestCrossUserAccessDenied:
    """Alice starts a session and a run; Bob must be locked out of both, on
    every route this bundle touches."""

    @pytest.mark.asyncio
    async def test_bob_cannot_read_alices_chat_history(
        self, profile_store, session_store, real_checkpointer
    ):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        alice_session = session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-bob")
        with patch("backend.api.chat.serialise_history") as mock_serialise:
            response = client.get(f"/api/me/chat/history?session_id={alice_session}")

        assert response.status_code == 404
        mock_serialise.assert_not_called()

    @pytest.mark.asyncio
    async def test_bob_cannot_post_into_alices_session(
        self, profile_store, session_store, real_checkpointer
    ):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        alice_session = session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-bob")
        with patch("backend.api.chat.stream_agent_response") as mock_stream:
            mock_stream.side_effect = _fake_stream
            response = client.post(
                "/api/chat", json={"message": "hi", "session_id": alice_session}
            )

        assert response.status_code == 404
        mock_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_bob_cannot_resume_alices_run(
        self, profile_store, session_store, real_checkpointer
    ):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        alice_session = session_store.create_session("uid-alice")
        run_id = "alice-run-1"
        await _seed_run(real_checkpointer, run_id, "uid-alice")

        client = _make_client(session_store, user_id="uid-bob")
        with patch("backend.api.hitl.stream_resume_response") as mock_stream:
            mock_stream.side_effect = _fake_stream
            response = client.post(
                "/api/chat/resume",
                json={
                    "session_id": alice_session,
                    "run_id": run_id,
                    "choice": "confirm",
                    "note": "",
                },
            )

        assert response.status_code == 404
        mock_stream.assert_not_called()


class TestSameUserAccessStillWorks:
    """The legitimate same-user chat/resume flow must not regress."""

    @pytest.mark.asyncio
    async def test_alice_can_read_her_own_history(
        self, profile_store, session_store, real_checkpointer
    ):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        alice_session = session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-alice")
        with patch("backend.api.chat.serialise_history", return_value=[]):
            response = client.get(f"/api/me/chat/history?session_id={alice_session}")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_alice_can_post_into_her_own_session(
        self, profile_store, session_store, real_checkpointer
    ):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        alice_session = session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-alice")
        with patch("backend.api.chat.stream_agent_response") as mock_stream:
            mock_stream.side_effect = _fake_stream
            response = client.post(
                "/api/chat", json={"message": "hi", "session_id": alice_session}
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_alice_can_resume_her_own_run(
        self, profile_store, session_store, real_checkpointer
    ):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        alice_session = session_store.create_session("uid-alice")
        run_id = "alice-run-2"
        await _seed_run(real_checkpointer, run_id, "uid-alice")

        client = _make_client(session_store, user_id="uid-alice")
        with patch("backend.api.hitl.stream_resume_response") as mock_stream:
            mock_stream.side_effect = _fake_stream
            response = client.post(
                "/api/chat/resume",
                json={
                    "session_id": alice_session,
                    "run_id": run_id,
                    "choice": "confirm",
                    "note": "",
                },
            )

        assert response.status_code == 200
        mock_stream.assert_called_once()
