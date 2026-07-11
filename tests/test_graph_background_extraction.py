"""Unit tests for background fact-extraction scheduling in `stream_agent_response()`
(capstone-round Bundle 3, Task 37): the chat response must complete and return to
the caller without ever awaiting `extract_and_store_facts()` (Req 12.1, 12.2), and a
failure inside that background task must never surface through the chat response
path (Req 12.3).
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk

from backend.agent import graph as graph_module
from backend.agent.graph import stream_agent_response
from backend.schemas import UserProfile


class _FakeCompiledGraph:
    """Unlike test_graph_memory_retrieval.py's silent variant, this one streams a
    real text chunk so the resulting `answer` is non-empty — required for the
    finally block's `if answer:` gate to actually schedule a background task."""

    async def astream(self, *args, **kwargs):
        yield AIMessageChunk(content="Here's a routine you could try."), {"langgraph_node": "agent"}

    async def aget_state(self, *args, **kwargs):
        return MagicMock(tasks=[])


@pytest.fixture
def graph_test_doubles():
    with (
        patch("backend.agent.graph._store") as mock_profile_store,
        patch("backend.agent.graph._memory_store") as mock_memory_store,
        patch("backend.agent.graph._memory_embeddings") as mock_embeddings,
        patch("backend.agent.graph.get_history") as mock_get_history,
        patch("backend.agent.graph._make_tools", return_value=[]),
        patch("backend.agent.graph.build_graph", return_value=_FakeCompiledGraph()),
    ):
        mock_profile_store.get_profile.return_value = UserProfile(
            user_id="user-bg", username="alice", onboarding_complete=True
        )
        mock_profile_store.get_all_routines.return_value = []
        mock_embeddings.embed_query.return_value = [0.1] * 4096
        mock_memory_store.search_facts.return_value = []
        mock_history = MagicMock()
        mock_history.messages = [MagicMock()]  # non-empty: sidesteps title generation
        mock_get_history.return_value = mock_history
        yield


@pytest.mark.asyncio
async def test_slow_failing_extraction_does_not_block_or_leak_into_response(graph_test_doubles):
    async def _slow_and_failing(*args, **kwargs):
        await asyncio.sleep(0.2)
        raise RuntimeError("extraction blew up")

    with patch("backend.agent.graph.extract_and_store_facts", side_effect=_slow_and_failing) as mock_extract:
        chunks = [c async for c in stream_agent_response("user-bg-1", "hello", "sess-1")]

        # The stream already completed and returned to the caller — the 0.2s
        # extraction coroutine cannot possibly have finished yet, proving the
        # response was not awaited on it (Req 12.1, 12.2).
        assert len(graph_module._background_tasks) == 1
        bg_task = next(iter(graph_module._background_tasks))
        assert not bg_task.done()

        # Retrieve the task's exception explicitly (rather than letting it leak
        # as an unretrieved-task warning) — proving its failure never surfaced
        # through the chat response path above (Req 12.3).
        with pytest.raises(RuntimeError, match="extraction blew up"):
            await bg_task

    mock_extract.assert_called_once()
    assert mock_extract.call_args[0][0] == "user-bg-1"
    assert mock_extract.call_args[0][1] == "sess-1"
    assert mock_extract.call_args[0][2] == "hello"
    assert any("[DONE]" in c for c in chunks)
    assert not any('"type": "error"' in c for c in chunks)


@pytest.mark.asyncio
async def test_extraction_scheduled_with_user_message_and_final_answer(graph_test_doubles):
    completed = asyncio.Event()

    async def _fast(*args, **kwargs):
        completed.set()

    with patch("backend.agent.graph.extract_and_store_facts", side_effect=_fast) as mock_extract:
        chunks = [c async for c in stream_agent_response("user-bg-2", "What SPF should I use?", "sess-2")]
        await asyncio.wait_for(completed.wait(), timeout=1)

    assert any("[DONE]" in c for c in chunks)
    mock_extract.assert_called_once()
    call_args = mock_extract.call_args[0]
    assert call_args[0] == "user-bg-2"
    assert call_args[1] == "sess-2"
    assert call_args[2] == "What SPF should I use?"
    assert isinstance(call_args[3], str)  # the accumulated answer text
