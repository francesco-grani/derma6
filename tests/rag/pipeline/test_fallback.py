"""Tests for the external_fallback node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.fallback import external_fallback
from backend.rag.pipeline.state import RankedDoc, initial_state


def _state(**kwargs) -> dict:
    s = dict(initial_state("test query"))
    s.update(kwargs)
    return s


@pytest.mark.asyncio
async def test_llm_only_strategy():
    state = _state(fallback_strategy="llm-only")
    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.crag_fallback_strategy = "llm-only"
        ms.tavily_api_key = ""
        result = await external_fallback(state)

    assert result["llm_only_fallback"] is True
    assert result["fallback_docs"] == []
    assert result["fallback_strategy_used"] == "llm-only"


@pytest.mark.asyncio
async def test_web_search_no_tavily_uses_ddg():
    state = _state(fallback_strategy="web-search")

    mock_ddg = MagicMock()
    mock_ddg.run = MagicMock(return_value="DuckDuckGo result text about skincare")

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.crag_fallback_strategy = "web-search"
        ms.tavily_api_key = ""
        with patch("backend.rag.pipeline.nodes.fallback._web_search") as mock_ws:
            mock_ws.return_value = [
                RankedDoc(doc_id="web_0", content="DDG result", source_name="DDG",
                          source_file="web", rrf_score=0.0, rerank_score=0.0, retrieval_path="sparse")
            ]
            result = await external_fallback(state)

    assert result["fallback_docs"] != [] or result["llm_only_fallback"] is True


@pytest.mark.asyncio
async def test_web_search_failure_degrades_to_llm_only():
    state = _state(fallback_strategy="web-search")

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.crag_fallback_strategy = "web-search"
        ms.tavily_api_key = ""
        with patch("backend.rag.pipeline.nodes.fallback._web_search",
                   new_callable=AsyncMock, side_effect=RuntimeError("network error")):
            result = await external_fallback(state)

    assert result["llm_only_fallback"] is True
    assert result["fallback_strategy_used"] == "llm-only"


@pytest.mark.asyncio
async def test_web_search_empty_results_degrades():
    state = _state(fallback_strategy="web-search")

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.crag_fallback_strategy = "web-search"
        ms.tavily_api_key = ""
        with patch("backend.rag.pipeline.nodes.fallback._web_search",
                   new_callable=AsyncMock, return_value=[]):
            result = await external_fallback(state)

    assert result["llm_only_fallback"] is True
    assert result["fallback_strategy_used"] == "llm-only"
