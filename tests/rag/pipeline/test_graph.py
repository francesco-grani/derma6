"""Tests for RagPipelineGraph.ainvoke (the class wraps the compiled StateGraph)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.graph import RagPipelineGraph


def _pipeline_with_mock_graph(mock_graph) -> RagPipelineGraph:
    """Build an instance without re-running _build_and_compile (already
    exercised at import time via kb_search.py's module-level singleton)."""
    instance = RagPipelineGraph.__new__(RagPipelineGraph)
    instance._graph = mock_graph
    return instance


@pytest.mark.asyncio
async def test_ainvoke_returns_result_string():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"result_string": "Formatted RAG output"})
    pipeline = _pipeline_with_mock_graph(mock_graph)

    with patch("backend.rag.pipeline.graph.settings") as ms:
        ms.crag_fallback_strategy = "llm-only"
        result = await pipeline.ainvoke("what is niacinamide?")

    assert result == "Formatted RAG output"
    mock_graph.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_ainvoke_empty_result_string_returns_fallback_message():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"result_string": ""})
    pipeline = _pipeline_with_mock_graph(mock_graph)

    with patch("backend.rag.pipeline.graph.settings") as ms:
        ms.crag_fallback_strategy = "llm-only"
        result = await pipeline.ainvoke("obscure query")

    assert "No relevant articles found" in result


@pytest.mark.asyncio
async def test_ainvoke_missing_result_string_key_returns_fallback_message():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    pipeline = _pipeline_with_mock_graph(mock_graph)

    with patch("backend.rag.pipeline.graph.settings") as ms:
        ms.crag_fallback_strategy = "llm-only"
        result = await pipeline.ainvoke("obscure query")

    assert "No relevant articles found" in result


@pytest.mark.asyncio
async def test_ainvoke_exception_is_logged_and_reraised():
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph exploded"))
    pipeline = _pipeline_with_mock_graph(mock_graph)

    with patch("backend.rag.pipeline.graph.settings") as ms:
        ms.crag_fallback_strategy = "llm-only"
        with pytest.raises(RuntimeError, match="graph exploded"):
            await pipeline.ainvoke("some query")
