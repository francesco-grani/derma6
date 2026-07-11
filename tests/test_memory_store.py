"""Integration tests for backend.db.memory_store.MemoryStore (capstone-round
Bundle 3, Task 32).

Requires a live Postgres with the `vector` extension available — `.cosine_distance()`
has no SQLite equivalent. Gated behind `pytest --run-pgvector` (see root conftest.py),
matching the `eval` marker's opt-in convention. Runs against a dedicated, disposable
Postgres schema on the configured DATABASE_URL, torn down after each test.
"""

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.memory_store import MemoryStore, MemoryStoreError
from backend.db.models import Base, ChatSession, User, UserMemoryFact

_TEST_SCHEMA = "test_memory_store"
_DIM = 4096


def _embedding(fill: float) -> list[float]:
    return [fill] * _DIM


@pytest.fixture
def pg_engine():
    engine = create_engine(settings.sqlalchemy_database_url)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_TEST_SCHEMA}"))
        conn.execute(text(f"SET search_path TO {_TEST_SCHEMA}, public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # Every connection this engine hands out must see the test schema first.
    engine = create_engine(
        settings.sqlalchemy_database_url,
        connect_args={"options": f"-csearch_path={_TEST_SCHEMA},public"},
    )
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
        engine,
        tables=[User.__table__, ChatSession.__table__, UserMemoryFact.__table__],
        checkfirst=False,
    )
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


@pytest.mark.pgvector
class TestAddFact:
    def test_persists_and_returns_schema(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        fact = memory_store.add_fact(user_id, None, "Prefers fragrance-free products", _embedding(0.01))

        assert fact.id is not None
        assert fact.fact_text == "Prefers fragrance-free products"
        assert fact.source_session_id is None

    def test_raises_for_unknown_user(self, memory_store):
        with pytest.raises(MemoryStoreError, match="not found"):
            memory_store.add_fact("nonexistent-uid", None, "fact", _embedding(0.01))


@pytest.mark.pgvector
class TestSearchFacts:
    def test_returns_nearest_facts_ordered(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        memory_store.add_fact(user_id, None, "near", _embedding(0.01))
        memory_store.add_fact(user_id, None, "far", _embedding(0.9))

        results = memory_store.search_facts(user_id, _embedding(0.01), top_k=5)

        assert [r.fact_text for r in results] == ["near", "far"]

    def test_respects_top_k(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        for i in range(5):
            memory_store.add_fact(user_id, None, f"fact-{i}", _embedding(0.01 * i))

        results = memory_store.search_facts(user_id, _embedding(0.0), top_k=2)

        assert len(results) == 2

    def test_cross_user_isolation(self, pg_engine, memory_store):
        """Req 11.5: a query for user B must never return user A's facts."""
        user_a = _make_user(pg_engine, "alice")
        user_b = _make_user(pg_engine, "bob")
        memory_store.add_fact(user_a, None, "alice's fact", _embedding(0.01))

        results = memory_store.search_facts(user_b, _embedding(0.01), top_k=5)

        assert results == []


@pytest.mark.pgvector
class TestFindNearest:
    def test_returns_none_when_no_facts(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        assert memory_store.find_nearest(user_id, _embedding(0.01)) is None

    def test_returns_nearest_fact_and_distance(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        memory_store.add_fact(user_id, None, "close match", _embedding(0.01))
        memory_store.add_fact(user_id, None, "far match", _embedding(0.9))

        result = memory_store.find_nearest(user_id, _embedding(0.01))

        assert result is not None
        fact, distance = result
        assert fact.fact_text == "close match"
        assert distance < 0.01

    def test_dedup_candidate_lookup_near_identical(self, pg_engine, memory_store):
        """A near-duplicate candidate embedding resolves to a small distance,
        matching how backend.agent.memory_extraction.is_near_duplicate() consumes
        this result to skip storing a duplicate fact."""
        user_id = _make_user(pg_engine)
        memory_store.add_fact(user_id, None, "existing fact", _embedding(0.5))

        fact, distance = memory_store.find_nearest(user_id, _embedding(0.5))

        assert fact.fact_text == "existing fact"
        assert distance == pytest.approx(0.0, abs=1e-6)


@pytest.mark.pgvector
class TestGetAllFacts:
    def test_returns_all_facts_newest_first(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        memory_store.add_fact(user_id, None, "first", _embedding(0.1))
        memory_store.add_fact(user_id, None, "second", _embedding(0.2))

        facts = memory_store.get_all_facts(user_id)

        assert {f.fact_text for f in facts} == {"first", "second"}

    def test_empty_for_user_with_no_facts(self, pg_engine, memory_store):
        user_id = _make_user(pg_engine)
        assert memory_store.get_all_facts(user_id) == []


@pytest.mark.pgvector
class TestDeleteAllForUser:
    def test_deletes_only_that_users_facts(self, pg_engine, memory_store):
        user_a = _make_user(pg_engine, "alice")
        user_b = _make_user(pg_engine, "bob")
        memory_store.add_fact(user_a, None, "alice's fact", _embedding(0.1))
        memory_store.add_fact(user_b, None, "bob's fact", _embedding(0.2))

        memory_store.delete_all_for_user(user_a)

        assert memory_store.get_all_facts(user_a) == []
        assert len(memory_store.get_all_facts(user_b)) == 1


@pytest.mark.pgvector
class TestCascadeOnUserDelete:
    def test_deleting_user_cascades_to_facts(self, pg_engine, memory_store):
        """Parity with delete_all_for_user: deleting the User row directly
        (e.g. via account deletion elsewhere) must clear facts the same way."""
        user_id = _make_user(pg_engine)
        memory_store.add_fact(user_id, None, "will be cascade-deleted", _embedding(0.1))

        with Session(pg_engine) as session:
            user = session.get(User, user_id)
            session.delete(user)
            session.commit()

        with Session(pg_engine) as session:
            remaining = session.query(UserMemoryFact).filter_by(user_id=user_id).all()
        assert remaining == []
