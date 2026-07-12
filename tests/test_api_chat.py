"""Tests for backend.api.chat (security-remediation Task 52, Req 19.1, 19.2).

Route-level tests via FastAPI's `TestClient`, mirroring `tests/test_api_sessions.py`'s
pattern: `get_current_user`/`get_session_store` are overridden via
`app.dependency_overrides`, and `stream_agent_response`/`serialise_history` are
patched at their `backend.api.chat` import site so no live LLM/DB call happens —
these tests exercise the session-ownership guard, not the streaming/history
machinery itself.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.chat import router as chat_router
from backend.auth import get_current_user
from backend.db.deps import get_session_store
from backend.middleware.content_filter import check_chat_content


def _make_client(store, user_id: str = "uid-alice") -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: user_id
    app.dependency_overrides[check_chat_content] = lambda: None
    return TestClient(app)


async def _fake_stream(*args, **kwargs):
    yield "data: {}\n\n"


class TestChatSessionOwnership:
    def test_own_session_allows_posting(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        session_id = session_store.create_session("uid-alice")
        client = _make_client(session_store, user_id="uid-alice")

        with patch("backend.api.chat.stream_agent_response", _fake_stream):
            response = client.post(
                "/api/chat", json={"message": "hi", "session_id": session_id}
            )

        assert response.status_code == 200

    def test_cross_user_session_rejected(self, profile_store, session_store):
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

    def test_unknown_session_id_rejected(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(session_store, user_id="uid-alice")

        with patch("backend.api.chat.stream_agent_response") as mock_stream:
            mock_stream.side_effect = _fake_stream
            response = client.post(
                "/api/chat", json={"message": "hi", "session_id": "nonexistent-session"}
            )

        assert response.status_code == 404
        mock_stream.assert_not_called()


class TestChatHistoryOwnership:
    def test_own_session_returns_history(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        session_id = session_store.create_session("uid-alice")
        client = _make_client(session_store, user_id="uid-alice")

        with patch("backend.api.chat.serialise_history", return_value=[]) as mock_serialise:
            response = client.get(f"/api/me/chat/history?session_id={session_id}")

        assert response.status_code == 200
        assert response.json() == []
        mock_serialise.assert_called_once_with(session_id)

    def test_cross_user_session_returns_404_not_empty_history(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        alice_session = session_store.create_session("uid-alice")

        client = _make_client(session_store, user_id="uid-bob")
        with patch("backend.api.chat.serialise_history") as mock_serialise:
            response = client.get(f"/api/me/chat/history?session_id={alice_session}")

        assert response.status_code == 404
        mock_serialise.assert_not_called()

    def test_unowned_session_id_returns_404_not_empty_history(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(session_store, user_id="uid-alice")

        with patch("backend.api.chat.serialise_history") as mock_serialise:
            response = client.get("/api/me/chat/history?session_id=nonexistent-session")

        assert response.status_code == 404
        mock_serialise.assert_not_called()
