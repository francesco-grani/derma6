"""Tests for the CRAG grading node and routing functions."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.crag import crag_grade, route_after_crag, route_after_retry
from backend.rag.pipeline.state import RankedDoc


def _doc(doc_id: str) -> RankedDoc:
    return RankedDoc(doc_id=doc_id, content=f"content {doc_id}", source_name="src",
                     source_file="f.md", rrf_score=0.5, rerank_score=0.8, retrieval_path="dense")


def _state(docs: list[RankedDoc]) -> dict:
    return {"original_query": "test query", "reranked_docs": docs, "node_latencies": {}}


@pytest.mark.asyncio
async def test_all_yes_routes_to_generate():
    docs = [_doc("d1"), _doc("d2")]
    mock_resp = MagicMock()
    mock_resp.content = "yes"

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm
        with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
            ms.crag_grade_timeout_seconds = 30
            ms.crag_relevance_threshold = 0.5
            ms.rag_debug_mode = False
            result = await crag_grade(_state(docs))

    assert result["first_pass_score"] == pytest.approx(1.0)
    assert route_after_crag({**_state(docs), **result}) == "generate"


@pytest.mark.asyncio
async def test_all_no_routes_to_local_retry():
    docs = [_doc("d1"), _doc("d2")]
    mock_resp = MagicMock()
    mock_resp.content = "no"

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm
        with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
            ms.crag_grade_timeout_seconds = 30
            ms.crag_relevance_threshold = 0.5
            ms.rag_debug_mode = False
            result = await crag_grade(_state(docs))

    assert result["first_pass_score"] == pytest.approx(0.0)
    assert route_after_crag({**_state(docs), **result}) == "local_retry"


@pytest.mark.asyncio
async def test_empty_docs_score_negative_one():
    result = await crag_grade(_state([]))
    assert result["first_pass_score"] == pytest.approx(-1.0)
    assert result["doc_grades"] == []
    assert route_after_crag({**_state([]), **result}) == "local_retry"


@pytest.mark.asyncio
async def test_timeout_routes_to_local_retry():
    docs = [_doc("d1")]

    async def _slow(*args, **kwargs):
        await asyncio.sleep(100)

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = _slow
        mock_llm_fn.return_value = mock_llm
        with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
            ms.crag_grade_timeout_seconds = 0.001
            ms.crag_relevance_threshold = 0.5
            ms.rag_debug_mode = False
            result = await crag_grade(_state(docs))

    assert result["crag_timeout"] is True
    assert result["first_pass_score"] == pytest.approx(0.0)
    assert route_after_crag({**_state(docs), **result}) == "local_retry"


@pytest.mark.asyncio
async def test_unparseable_response_treated_as_no():
    docs = [_doc("d1"), _doc("d2")]
    mock_resp = MagicMock()
    mock_resp.content = "I am not sure about this"

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm
        with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
            ms.crag_grade_timeout_seconds = 30
            ms.crag_relevance_threshold = 0.5
            ms.rag_debug_mode = False
            result = await crag_grade(_state(docs))

    assert result["first_pass_score"] == pytest.approx(0.0)
    assert all(g is False for g in result["doc_grades"])


def test_route_after_retry_above_threshold():
    state = {"retry_score": 0.8}
    with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
        ms.crag_relevance_threshold = 0.5
        assert route_after_retry(state) == "generate"


def test_route_after_retry_below_threshold():
    state = {"retry_score": 0.2}
    with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
        ms.crag_relevance_threshold = 0.5
        assert route_after_retry(state) == "external_fallback"
