"""Tests for backend.api.sessions (capstone-round Bundle 2, Task 19, Req 7.1-7.3).

Route-level tests exercised through FastAPI's `TestClient`, mirroring
`tests/test_api_profile.py`'s pattern: `get_current_user` is overridden to
return a fixed `user_id` string directly, and `get_session_store` is
overridden to return a `SessionStore` backed by a per-test temporary SQLite
file. Since `SessionStore` requires the referenced user to already exist,
each user is provisioned via the `profile_store` fixture, which shares the
same underlying SQLite file as `session_store` (see tests/conftest.py).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_community.chat_message_histories import SQLChatMessageHistory

from backend.api.sessions import router as sessions_router
from backend.auth import get_current_user
from backend.db.deps import get_session_store


def _make_client(store, user_id: str = "uid-alice") -> TestClient:
    app = FastAPI()
    app.include_router(sessions_router)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


class TestListSessions:
    """Req 7.1-7.3: session listing is scoped to the authenticated user_id."""

    def test_returns_sessions_for_authenticated_user(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        session_store.create_session("uid-alice")
        client = _make_client(session_store, user_id="uid-alice")

        response = client.get("/api/me/sessions")

        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_scoped_to_user_id_not_shared_across_users(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-bob")
        response = client.get("/api/me/sessions")

        assert response.status_code == 200
        assert response.json() == []

    def test_missing_user_returns_500(self, session_store):
        client = _make_client(session_store, user_id="uid-ghost")

        response = client.get("/api/me/sessions")

        assert response.status_code == 500


class TestCreateSession:
    """Req 7.1-7.3: session creation is attributed to the authenticated user_id."""

    def test_creates_session(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(session_store, user_id="uid-alice")

        response = client.post("/api/me/sessions")

        assert response.status_code == 201
        body = response.json()
        assert "session_id" in body
        rows = session_store.get_sessions("uid-alice")
        assert any(r["session_id"] == body["session_id"] for r in rows)

    def test_missing_user_returns_500(self, session_store):
        client = _make_client(session_store, user_id="uid-ghost")

        response = client.post("/api/me/sessions")

        assert response.status_code == 500


class TestDeleteSession:
    """Req 7.1-7.3: session deletion is scoped to the authenticated user_id."""

    def test_deletes_session(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        session_id = session_store.create_session("uid-alice")
        # Realistic usage always has chat_history create message_store before a
        # session is deleted; do the same here so the cascade delete has a table.
        SQLChatMessageHistory(
            session_id=session_id, connection=session_store._engine
        ).add_user_message("hi")
        client = _make_client(session_store, user_id="uid-alice")

        response = client.delete(f"/api/me/sessions/{session_id}")

        assert response.status_code == 204
        assert session_store.get_sessions("uid-alice") == []

    def test_missing_session_returns_404(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(session_store, user_id="uid-alice")

        response = client.delete("/api/me/sessions/nonexistent-session-id")

        assert response.status_code == 404

    def test_cannot_delete_another_users_session(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        session_id = session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-bob")
        response = client.delete(f"/api/me/sessions/{session_id}")

        assert response.status_code == 404
        assert session_store.get_sessions("uid-alice") != []
