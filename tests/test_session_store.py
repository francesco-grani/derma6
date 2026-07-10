"""Unit tests for backend.db.session_store.SessionStore (in-memory-per-test SQLite).

Session creation/lookup is keyed by `user_id` (Supabase UUID) — same 1:1
rename pattern as backend/db/profile_store.py's Task 16 rekey (see design.md
Bundle 2, `backend/db/session_store.py` section).
"""

from datetime import datetime, timedelta

import pytest
from langchain_community.chat_message_histories import SQLChatMessageHistory
from sqlalchemy import text
from sqlalchemy.orm import Session as SASession

from backend.db.session_store import SessionStore, SessionStoreError


def _make_user(profile_store, username: str, user_id: str | None = None) -> str:
    """Create a user via ProfileStore (sharing the SessionStore's db, since both
    fixtures resolve to the same per-test tmp_path db file) and return its id."""
    uid = user_id or f"uid-{username}"
    profile_store.get_or_create_user_by_id(uid, f"{username}@example.com", username)
    return uid


def _set_updated_at(session_store, session_id: str, dt: datetime) -> None:
    """Force a ChatSession's updated_at to an explicit value.

    SQLite's CURRENT_TIMESTAMP default has second-level resolution, so two
    sessions created back-to-back in a test can land on the exact same
    timestamp — making 'ORDER BY updated_at DESC' genuinely ambiguous between
    them (not a bug in SessionStore, just a limitation of relying on
    real wall-clock time in a fast test). Tests that assert a specific
    ordering use this helper to make the ordering deterministic instead of
    depending on real elapsed time between calls.
    """
    with SASession(session_store._engine) as session:
        session.execute(
            text("UPDATE chat_sessions SET updated_at = :dt WHERE id = :sid"),
            {"dt": dt, "sid": session_id},
        )
        session.commit()


# ── create_session ──────────────────────────────────────────────────────────


class TestCreateSession:
    def test_creates_session_for_existing_user(self, profile_store, session_store):
        user_id = _make_user(profile_store, "alice")
        session_id = session_store.create_session(user_id)
        assert session_id
        sessions = session_store.get_sessions(user_id)
        assert sessions[0]["session_id"] == session_id

    def test_raises_for_unknown_user(self, session_store):
        with pytest.raises(SessionStoreError, match="not found"):
            session_store.create_session("nonexistent-uid")


# ── get_sessions / get_active_session_id ────────────────────────────────────


class TestGetSessions:
    def test_empty_for_new_user(self, profile_store, session_store):
        user_id = _make_user(profile_store, "bob")
        assert session_store.get_sessions(user_id) == []

    def test_returns_ordered_by_updated_at_desc(self, profile_store, session_store):
        user_id = _make_user(profile_store, "carol")
        first = session_store.create_session(user_id)
        second = session_store.create_session(user_id)
        # SQLite's CURRENT_TIMESTAMP has second-level resolution — force distinct
        # timestamps so the ordering assertion isn't racing real wall-clock time.
        now = datetime.utcnow()
        _set_updated_at(session_store, first, now - timedelta(seconds=1))
        _set_updated_at(session_store, second, now)
        sessions = session_store.get_sessions(user_id)
        assert [s["session_id"] for s in sessions] == [second, first]

    def test_different_users_are_independent(self, profile_store, session_store):
        alice_id = _make_user(profile_store, "alice")
        bob_id = _make_user(profile_store, "bob")
        session_store.create_session(alice_id)
        assert session_store.get_sessions(bob_id) == []

    def test_raises_for_unknown_user(self, session_store):
        with pytest.raises(SessionStoreError, match="not found"):
            session_store.get_sessions("nonexistent-uid")


class TestGetActiveSessionId:
    def test_returns_none_when_no_sessions(self, profile_store, session_store):
        user_id = _make_user(profile_store, "dave")
        assert session_store.get_active_session_id(user_id) is None

    def test_returns_most_recently_updated_session(self, profile_store, session_store):
        user_id = _make_user(profile_store, "erin")
        first = session_store.create_session(user_id)
        second = session_store.create_session(user_id)
        # SQLite's CURRENT_TIMESTAMP has second-level resolution — force distinct
        # timestamps so the ordering assertion isn't racing real wall-clock time.
        now = datetime.utcnow()
        _set_updated_at(session_store, first, now - timedelta(seconds=1))
        _set_updated_at(session_store, second, now)
        assert session_store.get_active_session_id(user_id) == second


# ── delete_session ───────────────────────────────────────────────────────────


class TestDeleteSession:
    def test_deletes_owned_session(self, profile_store, session_store):
        user_id = _make_user(profile_store, "frank")
        session_id = session_store.create_session(user_id)
        # Realistic usage always has chat_history create message_store before a
        # session is deleted; do the same here so the cascade delete has a table.
        SQLChatMessageHistory(
            session_id=session_id, connection=session_store._engine
        ).add_user_message("hi")

        session_store.delete_session(session_id, user_id)

        assert session_store.get_sessions(user_id) == []

    def test_raises_for_missing_session(self, profile_store, session_store):
        user_id = _make_user(profile_store, "grace")
        with pytest.raises(SessionStoreError, match="not found"):
            session_store.delete_session("nonexistent-session", user_id)

    def test_raises_for_unknown_user(self, session_store):
        with pytest.raises(SessionStoreError, match="not found"):
            session_store.delete_session("some-session", "nonexistent-uid")


# ── legacy migration (session_id == user_id rows in message_store) ─────────


class TestLegacyMigration:
    def test_migrates_legacy_history_keyed_by_user_id(self, profile_store, session_store):
        """Pre-multi-session installs stored messages with session_id equal to
        the user's key. get_sessions() lazily wraps any such rows into a
        'Previous conversations' session on first call (now keyed by user_id
        rather than username)."""
        user_id = _make_user(profile_store, "hank")
        legacy_history = SQLChatMessageHistory(
            session_id=user_id, connection=session_store._engine
        )
        legacy_history.add_user_message("hello")

        sessions = session_store.get_sessions(user_id)

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == user_id
        assert sessions[0]["title"] == "Previous conversations"

    def test_does_not_duplicate_migration_on_repeat_calls(self, profile_store, session_store):
        user_id = _make_user(profile_store, "ivy")
        legacy_history = SQLChatMessageHistory(
            session_id=user_id, connection=session_store._engine
        )
        legacy_history.add_user_message("hello")

        session_store.get_sessions(user_id)
        sessions = session_store.get_sessions(user_id)

        assert len(sessions) == 1
