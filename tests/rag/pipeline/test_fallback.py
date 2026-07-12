"""Tests for the external_fallback node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.fallback import _parse_web_results, _web_search, external_fallback
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


# ── _parse_web_results ────────────────────────────────────────────────────────


def test_parse_web_results_non_list_returns_empty():
    assert _parse_web_results("not a list") == []
    assert _parse_web_results(None) == []


def test_parse_web_results_converts_dicts_with_content():
    raw = [
        {"content": "Retinol info", "url": "https://a.example"},
        {"content": "Niacinamide info", "url": "https://b.example"},
    ]
    docs = _parse_web_results(raw)
    assert len(docs) == 2
    assert docs[0].doc_id == "web_0"
    assert docs[0].content == "Retinol info"
    assert docs[0].source_name == "https://a.example"
    assert docs[0].retrieval_path == "sparse"


def test_parse_web_results_skips_non_dict_and_empty_content_items():
    raw = ["not a dict", {"url": "https://a.example"}, {"content": "", "url": "https://b.example"}]
    assert _parse_web_results(raw) == []


def test_parse_web_results_limits_to_first_three():
    raw = [{"content": f"doc {i}", "url": f"https://{i}.example"} for i in range(5)]
    docs = _parse_web_results(raw)
    assert len(docs) == 3
    assert [d.doc_id for d in docs] == ["web_0", "web_1", "web_2"]


# ── _web_search ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_uses_tavily_when_key_configured():
    tavily_raw = [{"content": "Tavily result about retinol", "url": "https://tavily.example"}]
    mock_tool = MagicMock()
    mock_tool.invoke.return_value = tavily_raw

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.tavily_api_key = "fake-tavily-key"
        with patch("langchain_community.tools.tavily_search.TavilySearchResults", return_value=mock_tool):
            docs = await _web_search("retinol benefits")

    assert len(docs) == 1
    assert docs[0].content == "Tavily result about retinol"


@pytest.mark.asyncio
async def test_web_search_tavily_failure_falls_back_to_ddg():
    mock_ddg = MagicMock()
    mock_ddg.run.return_value = "DDG fallback text"

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.tavily_api_key = "fake-tavily-key"
        with patch("langchain_community.tools.tavily_search.TavilySearchResults",
                   side_effect=RuntimeError("tavily broken")):
            with patch("langchain_community.utilities.DuckDuckGoSearchAPIWrapper", return_value=mock_ddg):
                docs = await _web_search("retinol benefits")

    assert len(docs) == 1
    assert docs[0].content == "DDG fallback text"
    assert docs[0].source_name == "DuckDuckGo Search"


@pytest.mark.asyncio
async def test_web_search_no_tavily_key_goes_straight_to_ddg():
    mock_ddg = MagicMock()
    mock_ddg.run.return_value = "DDG only result"

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.tavily_api_key = ""
        with patch("langchain_community.utilities.DuckDuckGoSearchAPIWrapper", return_value=mock_ddg):
            docs = await _web_search("some query")

    assert len(docs) == 1
    assert docs[0].content == "DDG only result"


@pytest.mark.asyncio
async def test_web_search_ddg_empty_result_returns_empty_list():
    mock_ddg = MagicMock()
    mock_ddg.run.return_value = ""

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.tavily_api_key = ""
        with patch("langchain_community.utilities.DuckDuckGoSearchAPIWrapper", return_value=mock_ddg):
            docs = await _web_search("some query")

    assert docs == []


@pytest.mark.asyncio
async def test_web_search_ddg_also_fails_returns_empty_list():
    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.tavily_api_key = ""
        with patch("langchain_community.utilities.DuckDuckGoSearchAPIWrapper",
                   side_effect=RuntimeError("ddg broken too")):
            docs = await _web_search("some query")

    assert docs == []


# ── external_fallback (real _web_search, not mocked) ─────────────────────────


@pytest.mark.asyncio
async def test_external_fallback_web_search_uses_retry_query_when_present():
    web_docs = [
        RankedDoc(doc_id="web_0", content="result", source_name="https://x.example",
                  source_file="web", rrf_score=0.0, rerank_score=0.0, retrieval_path="sparse")
    ]
    state = _state(fallback_strategy="web-search", retry_query="the retry query")

    with patch("backend.rag.pipeline.nodes.fallback.settings") as ms:
        ms.crag_fallback_strategy = "web-search"
        ms.tavily_api_key = ""
        with patch("backend.rag.pipeline.nodes.fallback._web_search",
                   new_callable=AsyncMock, return_value=web_docs) as mock_ws:
            result = await external_fallback(state)

    mock_ws.assert_awaited_once_with("the retry query")
    assert result["fallback_docs"] == web_docs
    assert result["fallback_strategy_used"] == "web-search"
    assert result["llm_only_fallback"] is False


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
