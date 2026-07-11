"""Migration tests for `user_memory_facts` (capstone-round Bundle 3, Task 31).

Unlike `test_migration_uuid_pk.py` (plain-String columns, tested hermetically
against in-memory SQLite), this migration's `vector(4096)` column and HNSW
index have no SQLite equivalent — they require a live Postgres with the
`vector` extension available (Task 27 confirmed 0.8.2 is available on the
configured Supabase project). Gated behind `pytest --run-pgvector` (see root
conftest.py), matching the `eval` marker's opt-in convention.

Runs against a dedicated, disposable Postgres schema (not `public`) on the
configured `DATABASE_URL`, torn down after each test — never touches
pre-existing rows/tables in the target database's default schema.
"""
from __future__ import annotations

import importlib.util
import types
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from backend.config import settings

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_TEST_SCHEMA = "test_migration_memory_facts"


def _load_migration(filename: str) -> types.ModuleType:
    """Import a single Alembic revision file by path (it's not a package)."""
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_INITIAL = _load_migration("f154c79309d6_initial.py")
_UUID_PK = _load_migration("e73ee44b73c0_supabase_auth_uuid_pk.py")
_DROP_USERNAME_UNIQ = _load_migration("36703715277c_drop_username_uniqueness.py")
_MEMORY_FACTS = _load_migration("49aee1d01829_user_memory_facts.py")


@pytest.fixture
def connection():
    """Postgres connection scoped to a disposable, isolated schema carrying the
    full migration chain up to (not including) user_memory_facts."""
    engine = create_engine(settings.sqlalchemy_database_url)
    conn = engine.connect()
    conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
    conn.execute(text(f"CREATE SCHEMA {_TEST_SCHEMA}"))
    conn.execute(text(f"SET search_path TO {_TEST_SCHEMA}, public"))
    conn.commit()

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        _INITIAL.upgrade()
        _UUID_PK.upgrade()
        _DROP_USERNAME_UNIQ.upgrade()

    yield conn

    conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
    conn.commit()
    conn.close()
    engine.dispose()


def _run_upgrade(conn: sa.engine.Connection) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        _MEMORY_FACTS.upgrade()


def _run_downgrade(conn: sa.engine.Connection) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        _MEMORY_FACTS.downgrade()


@pytest.mark.pgvector
class TestUpgrade:
    def test_creates_table_with_expected_columns(self, connection):
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        columns = {c["name"]: c for c in inspector.get_columns("user_memory_facts")}
        assert set(columns) == {
            "id", "user_id", "fact_text", "embedding", "source_session_id", "created_at",
        }
        assert columns["fact_text"]["nullable"] is False
        assert columns["embedding"]["nullable"] is False
        assert columns["source_session_id"]["nullable"] is True

    def test_embedding_column_is_vector_4096(self, connection):
        _run_upgrade(connection)
        dim = connection.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'user_memory_facts'::regclass AND attname = 'embedding'"
            )
        ).scalar()
        assert dim == 4096

    def test_user_id_has_cascade_fk_and_index(self, connection):
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        fks = inspector.get_foreign_keys("user_memory_facts")
        user_fk = next(fk for fk in fks if fk["constrained_columns"] == ["user_id"])
        assert user_fk["referred_table"] == "users"
        assert user_fk["options"].get("ondelete") == "CASCADE"

        indexes = {ix["name"]: ix for ix in inspector.get_indexes("user_memory_facts")}
        assert "ix_user_memory_facts_user_id" in indexes

    def test_source_session_id_has_set_null_fk(self, connection):
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        fks = inspector.get_foreign_keys("user_memory_facts")
        session_fk = next(fk for fk in fks if fk["constrained_columns"] == ["source_session_id"])
        assert session_fk["referred_table"] == "chat_sessions"
        assert session_fk["options"].get("ondelete") == "SET NULL"

    def test_no_ann_index_on_embedding(self, connection):
        """pgvector's HNSW/ivfflat indexes cap at 2000 dimensions; this column
        is vector(4096) (Task 27) — building one fails outright ("column cannot
        have more than 2000 dimensions for hnsw index"), discovered running
        this bundle's live-Postgres regression pass. MemoryStore always filters
        by user_id before ordering by cosine distance, so an unindexed
        sequential scan over one user's handful of facts is fine at this scale."""
        _run_upgrade(connection)
        indexes = {
            ix["name"] for ix in sa.inspect(connection).get_indexes("user_memory_facts")
        }
        assert "ix_user_memory_facts_embedding_hnsw" not in indexes

    def test_can_insert_and_query_by_similarity(self, connection):
        _run_upgrade(connection)
        user_id = str(uuid.uuid4())
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, onboarding_complete, is_admin, "
                "created_at, updated_at) VALUES (:id, 'alice', :email, false, false, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        embedding_a = "[" + ",".join(["0.01"] * 4096) + "]"
        embedding_b = "[" + ",".join(["0.9"] * 4096) + "]"
        connection.execute(
            text(
                "INSERT INTO user_memory_facts (user_id, fact_text, embedding) "
                "VALUES (:user_id, 'fact a', :embedding)"
            ),
            {"user_id": user_id, "embedding": embedding_a},
        )
        connection.execute(
            text(
                "INSERT INTO user_memory_facts (user_id, fact_text, embedding) "
                "VALUES (:user_id, 'fact b', :embedding)"
            ),
            {"user_id": user_id, "embedding": embedding_b},
        )
        connection.commit()

        nearest = connection.execute(
            text(
                "SELECT fact_text FROM user_memory_facts "
                "ORDER BY embedding <=> :query LIMIT 1"
            ),
            {"query": embedding_a},
        ).scalar()
        assert nearest == "fact a"


@pytest.mark.pgvector
class TestDowngrade:
    def test_drops_table(self, connection):
        _run_upgrade(connection)
        _run_downgrade(connection)

        inspector = sa.inspect(connection)
        assert "user_memory_facts" not in inspector.get_table_names()
