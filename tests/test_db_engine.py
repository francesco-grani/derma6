"""Unit tests for backend.db.models.make_engine's pool and driver settings.

These assert on the parameters SQLAlchemy actually hands psycopg (via the
`do_connect` event, the last hook before the DBAPI call), rather than on what we
passed to create_engine — an unsupported connect_arg would otherwise look fine
here and only fail against a real server.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from backend.db.models import make_engine

_TXN_POOLER = "postgresql+psycopg://u:p@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
_SESSION_POOLER = "postgresql+psycopg://u:p@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"


class _Intercepted(Exception):
    pass


def _connect_params(engine) -> dict:
    """Capture the kwargs destined for psycopg.connect without a live server."""
    captured: dict = {}

    @event.listens_for(engine, "do_connect")
    def _capture(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
        captured.update(cparams)
        raise _Intercepted

    with pytest.raises(_Intercepted):
        engine.connect()
    return captured


class TestPreparedStatementPlumbing:
    def test_passes_prepare_threshold_none_through_to_the_driver(self):
        """None disables prepared statements — required by the transaction pooler."""
        params = _connect_params(make_engine(_TXN_POOLER, None))

        assert "prepare_threshold" in params, "setting never reached psycopg"
        assert params["prepare_threshold"] is None

    def test_passes_prepare_threshold_zero_through_to_the_driver(self):
        """0 is not 'off' — it prepares on first execution. Fine off the txn pooler."""
        params = _connect_params(make_engine(_SESSION_POOLER, 0))

        assert params["prepare_threshold"] == 0


class TestPoolBounds:
    def test_bounds_postgres_connections_below_the_pooler_cap(self):
        pool = make_engine(_SESSION_POOLER, 0).pool

        assert pool.size() + pool._max_overflow < 15, "must not claim the whole pooler"
        assert pool._pre_ping is True
        assert pool._recycle == 300

    def test_leaves_sqlite_alone(self):
        """SQLite's pool classes reject max_overflow; the whole suite runs on it."""
        engine = make_engine("sqlite://", None)

        assert engine.dialect.name == "sqlite"
        assert not hasattr(engine.pool, "_max_overflow")
