"""Bundle 3 regression pass (capstone-round Task 38): end-to-end coverage across
the pieces Tasks 27-37 built individually — extraction → dedup → storage →
retrieval, exercised against a real Postgres with `vector` enabled rather than
each piece's own mocked-store unit tests.

Gated behind `pytest --run-pgvector` (see root conftest.py), matching the `eval`
marker's opt-in convention. Runs against a dedicated, disposable Postgres schema
on the configured DATABASE_URL, torn down after each test.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.agent.memory_extraction import extract_and_store_facts
from backend.config import settings
from backend.db.memory_store import MemoryStore
from backend.db.models import Base, ChatSession, User
from backend.schemas import MemoryExtractionResult

_TEST_SCHEMA = "test_bundle3_regression"
_DIM = 4096


def _embedding(fill: float) -> list[float]:
    return [fill] * _DIM


@pytest.fixture
def pg_engine():
    bootstrap = create_engine(settings.sqlalchemy_database_url)
    with bootstrap.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_TEST_SCHEMA}"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    bootstrap.dispose()

    engine = create_engine(
        settings.sqlalchemy_database_url,
        connect_args={"options": f"-csearch_path={_TEST_SCHEMA},public"},
    )
    from backend.db.models import UserMemoryFact
    # checkfirst=False is required, not just an optimisation: with `public` on
    # the search_path (needed only so the `vector` type name resolves — it
    # lives in `public` from CREATE EXTENSION), checkfirst=True's reflection
    # can find same-named tables already in `public` and skip creating them
    # here — silently routing inserts into the real public.users/chat_sessions
    # tables instead of this schema's fresh ones. Discovered running this
    # bundle's live-Postgres regression pass (Task 38) — caught, no data lost,
    # but confirm with a reflection check below rather than trusting
    # search_path alone.
    Base.metadata.create_all(
        engine, tables=[User.__table__, ChatSession.__table__], checkfirst=False
    )
    Base.metadata.create_all(engine, tables=[UserMemoryFact.__table__], checkfirst=False)
    with engine.begin() as conn:
        created_here = set(inspect(conn).get_table_names(schema=_TEST_SCHEMA))
    assert {"users", "chat_sessions", "user_memory_facts"} <= created_here, (
        f"Expected tables were not created inside {_TEST_SCHEMA} — refusing to run "
        "this test rather than risk operating against the wrong schema."
    )
    yield engine
    with create_engine(settings.sqlalchemy_database_url).begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
    engine.dispose()


@pytest.fixture
def memory_store(pg_engine) -> MemoryStore:
    return MemoryStore(engine=pg_engine)


def _make_user(pg_engine, username: str = "alice") -> str:
    uid = str(uuid.uuid4())
    with Session(pg_engine) as session:
        session.add(User(id=uid, username=username, email=f"{uid}@example.com"))
        session.commit()
    return uid


def _make_session(pg_engine, user_id: str) -> str:
    sid = str(uuid.uuid4())
    with Session(pg_engine) as session:
        session.add(ChatSession(id=sid, user_id=user_id))
        session.commit()
    return sid


@pytest.mark.pgvector
class TestDedupAcrossTwoTurns:
    """A fact repeated (in substance) across two separate conversation turns
    must be stored only once — the second turn's near-identical extraction is
    recognised as a duplicate via MemoryStore.find_nearest() and skipped."""

    @pytest.mark.asyncio
    async def test_repeated_fact_across_two_turns_stored_once(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        session_id = _make_session(pg_engine, user_id)

        with (
            patch("backend.agent.memory_extraction.get_memory_store", return_value=memory_store),
            patch("backend.agent.memory_extraction._embeddings") as mock_embeddings,
            patch("backend.agent.memory_extraction.structured_completion") as mock_completion,
        ):
            mock_embeddings.embed_documents.side_effect = lambda texts: [_embedding(0.5) for _ in texts]
            mock_completion.return_value = (
                MemoryExtractionResult(facts=["Uses well water at home"]), False,
            )

            # Turn 1: user mentions the fact for the first time.
            await extract_and_store_facts(
                user_id, session_id, "I use well water", "Noted, that can affect product residue."
            )
            # Turn 2, later in the same or a different session: user mentions
            # essentially the same fact again — the extraction LLM re-extracts
            # it (as it has no memory of what's already stored).
            await extract_and_store_facts(
                user_id, session_id, "Just a reminder, I'm on well water",
                "Got it, already noted.",
            )

        facts = memory_store.get_all_facts(user_id)
        assert len(facts) == 1
        assert facts[0].fact_text == "Uses well water at home"


@pytest.mark.pgvector
class TestCrossSessionRetrieval:
    """A fact extracted from session A must be retrievable when the same user
    starts a new session B (Req 11.1) — memory is scoped to the user, not the
    session it originated from."""

    def test_fact_from_session_a_retrieved_in_session_b(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        session_a = _make_session(pg_engine, user_id)
        session_b = _make_session(pg_engine, user_id)

        memory_store.add_fact(user_id, session_a, "Travels frequently for work", _embedding(0.3))

        # A fresh query as if issued from session B's first turn — search_facts
        # takes no session_id parameter, so it is inherently session-agnostic.
        results = memory_store.search_facts(user_id, _embedding(0.3), top_k=5)

        assert any(f.fact_text == "Travels frequently for work" for f in results)
        assert results[0].source_session_id == session_a
        assert results[0].source_session_id != session_b


@pytest.mark.pgvector
class TestCrossUserIsolationRegression:
    """Req 11.5, re-verified at the bundle level (unit-level coverage already
    lives in test_memory_store.py::TestSearchFacts.test_cross_user_isolation):
    a query for one user must never surface another user's facts, even when
    both users have near-identical embeddings stored."""

    def test_user_b_query_never_returns_user_a_facts(self, pg_engine, memory_store):
        user_a = _make_user(pg_engine, "alice")
        user_b = _make_user(pg_engine, "bob")
        memory_store.add_fact(user_a, None, "Alice's private fact", _embedding(0.42))

        results = memory_store.search_facts(user_b, _embedding(0.42), top_k=5)

        assert results == []
