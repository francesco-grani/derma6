"""Unit tests for backend.db.chat_history's connection handling.

Regression cover for a production incident (2026-07-15): get_history() passed a
URL *string* to SQLChatMessageHistory, which makes LangChain call create_engine()
per instance. Each engine brought its own connection pool, so a single export
request (which serialises every session a user owns) opened engines by the
dozen and exhausted Supabase's session-mode pooler — capped project-wide at 15
client connections — leaving /api/chat throwing OperationalError.
"""

import pytest
from sqlalchemy.engine import Engine

from backend.db.chat_history import _history_for, get_history, serialise_history
from backend.db.models import engine


@pytest.fixture(autouse=True)
def _clear_history_cache():
    """get_history memoises per session_id at module level; keep tests independent."""
    _history_for.cache_clear()
    yield
    _history_for.cache_clear()


class TestGetHistoryConnectionReuse:
    def test_binds_to_the_shared_engine(self):
        assert get_history("some-session").engine is engine

    def test_never_creates_a_per_call_engine(self):
        """The invariant that actually bounds our connection count: N calls, 1 engine.

        Passing a URL string instead of `engine` would make this 25.
        """
        engines = {id(get_history(f"session-{i}").engine) for i in range(25)}
        assert engines == {id(engine)}

    def test_shared_engine_is_a_sync_engine(self):
        """SQLChatMessageHistory silently switches to async_mode on an AsyncEngine,
        which would strand the sync callers in graph.py and export.py."""
        assert isinstance(engine, Engine)
        assert get_history("some-session").async_mode is False


class TestGetHistoryCaching:
    """Each construction costs a CREATE TABLE IF NOT EXISTS round trip, so
    repeat calls for a session must reuse the instance rather than rebuild it."""

    def test_reuses_the_instance_for_a_session(self):
        assert get_history("session-a") is get_history("session-a")

    def test_constructs_once_per_session_across_repeat_calls(self):
        for _ in range(10):
            get_history("session-a")
            get_history("session-b")

        info = _history_for.cache_info()
        assert info.misses == 2, "one construction per distinct session_id"
        assert info.hits == 18

    def test_keeps_sessions_isolated(self):
        a, b = get_history("session-a"), get_history("session-b")

        assert a is not b
        assert (a.session_id, b.session_id) == ("session-a", "session-b")


class TestCachedInstanceStaysLiveAgainstTheDb:
    """The cache is only safe because the instance holds no message state."""

    def test_cached_instance_sees_writes_made_after_it_was_built(self, tmp_path):
        history = get_history("live-session")
        history.clear()
        history.add_user_message("first")

        # Same cached object, re-read: must reflect the write, not a stale list.
        assert [m.content for m in get_history("live-session").messages] == ["first"]

        history.add_ai_message("second")
        assert [m["content"] for m in serialise_history("live-session")] == [
            "first",
            "second",
        ]

        history.clear()
        assert serialise_history("live-session") == []
