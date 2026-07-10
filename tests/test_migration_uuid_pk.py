"""Migration tests for the UUID primary-key cutover (Bundle 2, Task 12).

Exercises `alembic/versions/e73ee44b73c0_supabase_auth_uuid_pk.py`'s
`upgrade()`/`downgrade()` directly against a throwaway in-memory SQLite
connection, bound via `alembic.operations.Operations.context()` — the
documented way to invoke a migration script's `op.*` calls outside of the
full `alembic.command`/`env.py` machinery. `env.py` always binds to the
process-wide `DATABASE_URL`, so driving migrations through it would either
hit the shared test database or require monkeypatching global settings;
binding a fresh `MigrationContext` per test keeps each test hermetically
isolated. Matches the project's SQLite-based migration/model test
convention (see `tests/test_models.py`) — plain `String` columns and FK
retyping have no SQLite incompatibility worth pulling in Postgres for.
"""
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


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

_DEPENDENT_TABLES = ["routines", "chat_sessions", "introduction_plans", "skin_analyses"]

# SQLAlchemy's SQLite FK reflection cross-checks a SQL-parsed constraint
# against PRAGMA foreign_key_list and warns on a benign mismatch that shows
# up after alembic's batch-mode table recreation; the FK itself reflects
# correctly (asserted throughout this module), so the warning is noise here.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*could not be located in PRAGMA foreign_keys.*:sqlalchemy.exc.SAWarning"
)


@pytest.fixture
def connection():
    """SQLite connection with the pre-cutover (initial migration) schema applied."""
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        _INITIAL.upgrade()
    yield conn
    conn.close()


def _run_upgrade(conn: sa.engine.Connection) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        _UUID_PK.upgrade()


def _run_downgrade(conn: sa.engine.Connection) -> None:
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        _UUID_PK.downgrade()


def _insert_legacy_user(conn: sa.engine.Connection) -> None:
    """Insert one row using the pre-cutover (integer id) schema shape."""
    conn.execute(
        sa.text(
            "INSERT INTO users (id, username, onboarding_complete, is_admin, "
            "created_at, updated_at) "
            "VALUES (1, 'legacy_user', 0, 0, datetime('now'), datetime('now'))"
        )
    )
    conn.commit()


class TestUpgradeOnEmptyDatabase:
    """Req 7.1, 7.2, 7.3: resulting column types/constraints after upgrade()."""

    def test_users_id_becomes_string_primary_key(self, connection):
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert columns["id"]["type"].python_type is str

        pk = inspector.get_pk_constraint("users")
        assert pk["constrained_columns"] == ["id"]

    def test_password_hash_dropped_and_email_added_unique_indexed(self, connection):
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert "password_hash" not in columns
        assert "email" in columns
        assert columns["email"]["nullable"] is False

        indexes = {ix["name"]: ix for ix in inspector.get_indexes("users")}
        assert indexes["ix_users_email"]["unique"]
        assert indexes["ix_users_email"]["column_names"] == ["email"]

    def test_username_remains_unique_and_indexed_secondary_attribute(self, connection):
        """Req 7.3: username is untouched by the cutover, just no longer the PK."""
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        indexes = {ix["name"]: ix for ix in inspector.get_indexes("users")}
        assert indexes["ix_users_username"]["unique"]
        assert indexes["ix_users_username"]["column_names"] == ["username"]

        pk = inspector.get_pk_constraint("users")
        assert "username" not in pk["constrained_columns"]

    @pytest.mark.parametrize("table_name", _DEPENDENT_TABLES)
    def test_dependent_table_user_id_becomes_string_with_fk(self, connection, table_name):
        _run_upgrade(connection)
        inspector = sa.inspect(connection)

        columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        assert columns["user_id"]["type"].python_type is str

        fks = [fk for fk in inspector.get_foreign_keys(table_name) if fk["referred_table"] == "users"]
        assert len(fks) == 1
        assert fks[0]["constrained_columns"] == ["user_id"]
        assert fks[0]["referred_columns"] == ["id"]

    def test_can_round_trip_string_ids_end_to_end(self, connection):
        """Reflected metadata plus an actual insert/select — belt and suspenders."""
        _run_upgrade(connection)

        user_id = "11111111-1111-1111-1111-111111111111"
        connection.execute(
            sa.text(
                "INSERT INTO users (id, username, email, onboarding_complete, "
                "is_admin, created_at, updated_at) "
                "VALUES (:id, 'alice', 'alice@example.com', 0, 0, "
                "datetime('now'), datetime('now'))"
            ),
            {"id": user_id},
        )
        connection.execute(
            sa.text(
                "INSERT INTO routines (user_id, name, created_at, updated_at) "
                "VALUES (:user_id, 'Morning', datetime('now'), datetime('now'))"
            ),
            {"user_id": user_id},
        )
        connection.commit()

        stored_user_id = connection.execute(
            sa.text("SELECT user_id FROM routines")
        ).scalar()
        assert stored_user_id == user_id


class TestUpgradeRefusesNonEmptyUsersTable:
    """Req 7.4: explicit, documented failure — never a silent delete."""

    def test_raises_runtime_error_with_actionable_truncate_instructions(self, connection):
        _insert_legacy_user(connection)

        with pytest.raises(RuntimeError, match="TRUNCATE"):
            _run_upgrade(connection)

    def test_error_message_names_all_affected_tables(self, connection):
        _insert_legacy_user(connection)

        with pytest.raises(RuntimeError) as exc_info:
            _run_upgrade(connection)

        message = str(exc_info.value)
        for table_name in ["users", *_DEPENDENT_TABLES, "routine_steps", "message_store"]:
            assert table_name in message

    def test_does_not_alter_schema_when_it_raises(self, connection):
        """The guard fires before any DDL runs — schema is left untouched."""
        _insert_legacy_user(connection)

        with pytest.raises(RuntimeError):
            _run_upgrade(connection)

        inspector = sa.inspect(connection)
        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert "password_hash" in columns
        assert "email" not in columns
        assert columns["id"]["type"].python_type is int

    def test_empty_table_after_delete_no_longer_raises(self, connection):
        """Sanity check that the guard is a live COUNT, not a one-shot latch."""
        _insert_legacy_user(connection)
        connection.execute(sa.text("DELETE FROM users"))
        connection.commit()

        _run_upgrade(connection)  # should not raise

        inspector = sa.inspect(connection)
        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert columns["id"]["type"].python_type is str


class TestDowngrade:
    """`downgrade()` assumes empty tables and inverts the column-type changes."""

    def test_reverts_users_to_integer_pk_and_password_hash(self, connection):
        _run_upgrade(connection)
        _run_downgrade(connection)

        inspector = sa.inspect(connection)
        columns = {c["name"]: c for c in inspector.get_columns("users")}
        assert columns["id"]["type"].python_type is int
        assert "password_hash" in columns
        assert "email" not in columns

    @pytest.mark.parametrize("table_name", _DEPENDENT_TABLES)
    def test_reverts_dependent_user_id_to_integer(self, connection, table_name):
        _run_upgrade(connection)
        _run_downgrade(connection)

        inspector = sa.inspect(connection)
        columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        assert columns["user_id"]["type"].python_type is int

        fks = [fk for fk in inspector.get_foreign_keys(table_name) if fk["referred_table"] == "users"]
        assert len(fks) == 1
