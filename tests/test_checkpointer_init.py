"""Unit tests for backend.agent.graph.init_checkpointer's connection settings.

init_checkpointer deliberately bypasses AsyncPostgresSaver.from_conn_string(),
which hardcodes prepare_threshold=0 — i.e. "prepare on first execution", the
opposite of off. Against Supabase's transaction-mode pooler, which cannot
support prepared statements, that is unusable. These tests pin the settings we
must therefore pass ourselves, including the two (autocommit, dict_row) that
from_conn_string supplied for us and that the saver's cursors depend on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from psycopg.rows import dict_row

from backend.agent import graph as graph_module


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def connect_kwargs():
    """Run init_checkpointer against a stubbed driver; return the connect kwargs."""
    connect = AsyncMock(return_value=_FakeConn())
    saver = MagicMock()
    saver.setup = AsyncMock()

    async def _run(prepare_threshold: int | None):
        with (
            patch.object(graph_module.AsyncConnection, "connect", connect),
            patch.object(graph_module, "AsyncPostgresSaver", return_value=saver),
            patch.object(
                type(graph_module.settings),
                "db_prepare_threshold",
                property(lambda self: prepare_threshold),
            ),
        ):
            await graph_module.init_checkpointer()
            await graph_module.close_checkpointer()
        return connect.await_args.kwargs

    return _run


class TestCheckpointerConnectionSettings:
    async def test_disables_prepared_statements_on_the_transaction_pooler(
        self, connect_kwargs
    ):
        kwargs = await connect_kwargs(None)

        assert kwargs["prepare_threshold"] is None

    async def test_keeps_prepared_statements_elsewhere(self, connect_kwargs):
        kwargs = await connect_kwargs(0)

        assert kwargs["prepare_threshold"] == 0

    async def test_preserves_the_settings_the_saver_depends_on(self, connect_kwargs):
        """Lost from_conn_string's setup by bypassing it, so re-assert it here:
        the saver's cursors assume autocommit and dict rows."""
        kwargs = await connect_kwargs(None)

        assert kwargs["autocommit"] is True
        assert kwargs["row_factory"] is dict_row
