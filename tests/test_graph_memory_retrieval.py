"""Unit tests for `stream_agent_response()`'s memory-retrieval step (capstone-round
Bundle 3, Task 36): embeds the incoming message, calls `MemoryStore.search_facts()`,
and degrades to "no facts retrieved" (fail-open) on any retrieval failure rather than
blocking the turn (Req 11.1, 11.2, 11.4, 17.1).

`backend/agent/graph.py` is coverage-omitted (LangGraph streaming requires a live LLM
+ graph runtime, per pyproject.toml) — this file exercises just the retrieval step by
mocking every other dependency (`build_graph`, `get_history`, `_store`), rather than
attempting a full live agent run.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.graph import stream_agent_response
from backend.schemas import MemoryFactSchema, UserProfile


class _FakeCompiledGraph:
    """Stands in for the object build_graph() returns — astream yields nothing,
    aget_state reports no pending interrupts, matching a tool-free turn."""

    async def astream(self, *args, **kwargs):
        return
        yield  # pragma: no cover — makes this an async generator; never reached

    async def aget_state(self, *args, **kwargs):
        return MagicMock(tasks=[])


def _profile(user_id: str) -> UserProfile:
    return UserProfile(user_id=user_id, username="alice", onboarding_complete=True)


async def _consume(agen):
    return [chunk async for chunk in agen]


@pytest.fixture
def graph_test_doubles():
    """Patches every stream_agent_response dependency except memory retrieval,
    so the retrieval step's behaviour can be observed in isolation."""
    with (
        patch("backend.agent.graph._store") as mock_profile_store,
        patch("backend.agent.graph._memory_store") as mock_memory_store,
        patch("backend.agent.graph._memory_embeddings") as mock_embeddings,
        patch("backend.agent.graph.get_history") as mock_get_history,
        patch("backend.agent.graph._make_tools", return_value=[]),
        patch("backend.agent.graph.build_graph", return_value=_FakeCompiledGraph()),
        patch("backend.agent.graph.build_system_prompt", wraps=lambda *a, **kw: "") as mock_build_prompt,
    ):
        mock_profile_store.get_all_routines.return_value = []
        mock_history = MagicMock()
        mock_history.messages = [MagicMock()]  # non-empty: sidesteps first-message title generation
        mock_get_history.return_value = mock_history
        yield {
            "profile_store": mock_profile_store,
            "memory_store": mock_memory_store,
            "embeddings": mock_embeddings,
            "build_prompt": mock_build_prompt,
        }


class TestMemoryRetrievalSuccess:
    @pytest.mark.asyncio
    async def test_embeds_message_and_searches_facts(self, graph_test_doubles):
        user_id = "user-retrieval-1"
        graph_test_doubles["profile_store"].get_profile.return_value = _profile(user_id)
        graph_test_doubles["embeddings"].embed_query.return_value = [0.1] * 4096
        graph_test_doubles["memory_store"].search_facts.return_value = [
            MemoryFactSchema(id=1, fact_text="Uses well water", created_at=__import__("datetime").datetime.now())
        ]

        await _consume(stream_agent_response(user_id, "What moisturiser should I use?", "sess-1"))

        graph_test_doubles["embeddings"].embed_query.assert_called_once_with(
            "What moisturiser should I use?"
        )
        graph_test_doubles["memory_store"].search_facts.assert_called_once()
        call_args = graph_test_doubles["memory_store"].search_facts.call_args[0]
        assert call_args[0] == user_id
        assert call_args[1] == [0.1] * 4096

    @pytest.mark.asyncio
    async def test_retrieved_facts_passed_into_system_prompt(self, graph_test_doubles):
        user_id = "user-retrieval-2"
        graph_test_doubles["profile_store"].get_profile.return_value = _profile(user_id)
        graph_test_doubles["embeddings"].embed_query.return_value = [0.1] * 4096
        graph_test_doubles["memory_store"].search_facts.return_value = [
            MemoryFactSchema(id=1, fact_text="Uses well water", created_at=__import__("datetime").datetime.now())
        ]

        await _consume(stream_agent_response(user_id, "hello", "sess-1"))

        _profile_arg, _store_arg, memory_facts_arg = graph_test_doubles["build_prompt"].call_args[0]
        assert memory_facts_arg == ["Uses well water"]

    @pytest.mark.asyncio
    async def test_no_facts_found_passes_empty_list(self, graph_test_doubles):
        user_id = "user-retrieval-3"
        graph_test_doubles["profile_store"].get_profile.return_value = _profile(user_id)
        graph_test_doubles["embeddings"].embed_query.return_value = [0.1] * 4096
        graph_test_doubles["memory_store"].search_facts.return_value = []

        await _consume(stream_agent_response(user_id, "hello", "sess-1"))

        _profile_arg, _store_arg, memory_facts_arg = graph_test_doubles["build_prompt"].call_args[0]
        assert memory_facts_arg == []


class TestMemoryRetrievalDegradesGracefully:
    @pytest.mark.asyncio
    async def test_embedding_failure_degrades_to_no_facts(self, graph_test_doubles):
        user_id = "user-retrieval-4"
        graph_test_doubles["profile_store"].get_profile.return_value = _profile(user_id)
        graph_test_doubles["embeddings"].embed_query.side_effect = RuntimeError("embedding service down")

        chunks = await _consume(stream_agent_response(user_id, "hello", "sess-1"))

        # Turn completes normally (fail-open) — no error surfaced to the user, DONE still sent.
        assert any("[DONE]" in c for c in chunks)
        assert not any('"type": "error"' in c for c in chunks)
        graph_test_doubles["memory_store"].search_facts.assert_not_called()
        _profile_arg, _store_arg, memory_facts_arg = graph_test_doubles["build_prompt"].call_args[0]
        assert memory_facts_arg == []

    @pytest.mark.asyncio
    async def test_search_facts_failure_degrades_to_no_facts(self, graph_test_doubles):
        user_id = "user-retrieval-5"
        graph_test_doubles["profile_store"].get_profile.return_value = _profile(user_id)
        graph_test_doubles["embeddings"].embed_query.return_value = [0.1] * 4096
        graph_test_doubles["memory_store"].search_facts.side_effect = RuntimeError("DB unavailable")

        chunks = await _consume(stream_agent_response(user_id, "hello", "sess-1"))

        assert any("[DONE]" in c for c in chunks)
        assert not any('"type": "error"' in c for c in chunks)
        _profile_arg, _store_arg, memory_facts_arg = graph_test_doubles["build_prompt"].call_args[0]
        assert memory_facts_arg == []
