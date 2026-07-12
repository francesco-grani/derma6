"""Tests for the CRAG grading node and routing functions."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.crag import crag_grade, local_retry, route_after_crag, route_after_retry
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


# ── _get_llm ──────────────────────────────────────────────────────────────────


def test_get_llm_is_a_singleton():
    import backend.rag.pipeline.nodes.crag as crag_module

    crag_module._llm = None
    first = crag_module._get_llm()
    second = crag_module._get_llm()

    assert first is second
    crag_module._llm = None


# ── _grade_doc ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grade_doc_exception_treated_as_not_relevant():
    from backend.rag.pipeline.nodes.crag import _grade_doc

    doc = _doc("d1")
    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))
        mock_llm_fn.return_value = mock_llm

        result = await _grade_doc("query", doc)

    assert result is False


# ── crag_grade debug logging ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crag_grade_debug_mode_logs_without_error():
    docs = [_doc("d1")]
    mock_resp = MagicMock()
    mock_resp.content = "yes"

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm
        with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
            ms.crag_grade_timeout_seconds = 30
            ms.crag_relevance_threshold = 0.5
            ms.rag_debug_mode = True
            result = await crag_grade(_state(docs))

    assert result["first_pass_score"] == pytest.approx(1.0)


# ── local_retry ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_retry_reformulates_retrieves_reranks_and_regrades():
    retry_docs = [_doc("retry1"), _doc("retry2")]
    reformulate_resp = MagicMock()
    reformulate_resp.content = "reformulated query text"
    grade_resp_yes = MagicMock()
    grade_resp_yes.content = "yes"

    state = {"original_query": "original question", "reranked_docs": [_doc("orig1")], "node_latencies": {}}

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[reformulate_resp, grade_resp_yes, grade_resp_yes])
        mock_llm_fn.return_value = mock_llm

        with patch("backend.rag.pipeline.nodes.retrieve.hybrid_retrieve",
                   new_callable=AsyncMock,
                   return_value={"candidate_docs": retry_docs, "node_latencies": {}}):
            with patch("backend.rag.pipeline.nodes.rerank.rerank",
                       return_value={"reranked_docs": retry_docs, "rerank_error": False}):
                with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
                    ms.crag_grade_timeout_seconds = 30
                    ms.crag_relevance_threshold = 0.5
                    result = await local_retry(state)

    assert result["retry_triggered"] is True
    assert result["retry_query"] == "reformulated query text"
    assert result["retry_docs"] == retry_docs
    assert result["retry_score"] == pytest.approx(1.0)
    assert "local_retry" in result["node_latencies"]


@pytest.mark.asyncio
async def test_local_retry_reformulation_failure_uses_original_query():
    retry_docs = [_doc("retry1")]
    grade_resp_no = MagicMock()
    grade_resp_no.content = "no"

    state = {"original_query": "original question", "reranked_docs": [], "node_latencies": {}}

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=[RuntimeError("reformulate failed"), grade_resp_no])
        mock_llm_fn.return_value = mock_llm

        with patch("backend.rag.pipeline.nodes.retrieve.hybrid_retrieve",
                   new_callable=AsyncMock,
                   return_value={"candidate_docs": retry_docs, "node_latencies": {}}):
            with patch("backend.rag.pipeline.nodes.rerank.rerank",
                       return_value={"reranked_docs": retry_docs, "rerank_error": False}):
                with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
                    ms.crag_grade_timeout_seconds = 30
                    ms.crag_relevance_threshold = 0.5
                    result = await local_retry(state)

    assert result["retry_query"] == "original question"
    assert result["retry_score"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_local_retry_empty_reformulation_uses_original_query():
    empty_resp = MagicMock()
    empty_resp.content = "   "
    state = {"original_query": "original question", "reranked_docs": [], "node_latencies": {}}

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=empty_resp)
        mock_llm_fn.return_value = mock_llm

        with patch("backend.rag.pipeline.nodes.retrieve.hybrid_retrieve",
                   new_callable=AsyncMock,
                   return_value={"candidate_docs": [], "node_latencies": {}}):
            with patch("backend.rag.pipeline.nodes.rerank.rerank",
                       return_value={"reranked_docs": [], "rerank_error": False}):
                result = await local_retry(state)

    assert result["retry_query"] == "original question"
    assert result["retry_docs"] == []
    assert result["retry_score"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_local_retry_regrade_timeout_returns_zero_score():
    retry_docs = [_doc("retry1")]
    reformulate_resp = MagicMock()
    reformulate_resp.content = "reformulated"
    call_count = {"n": 0}

    async def _ainvoke(prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return reformulate_resp
        await asyncio.sleep(100)

    state = {"original_query": "original question", "reranked_docs": [], "node_latencies": {}}

    with patch("backend.rag.pipeline.nodes.crag._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = _ainvoke
        mock_llm_fn.return_value = mock_llm

        with patch("backend.rag.pipeline.nodes.retrieve.hybrid_retrieve",
                   new_callable=AsyncMock,
                   return_value={"candidate_docs": retry_docs, "node_latencies": {}}):
            with patch("backend.rag.pipeline.nodes.rerank.rerank",
                       return_value={"reranked_docs": retry_docs, "rerank_error": False}):
                with patch("backend.rag.pipeline.nodes.crag.settings") as ms:
                    ms.crag_grade_timeout_seconds = 0.001
                    ms.crag_relevance_threshold = 0.5
                    result = await local_retry(state)

    assert result["retry_score"] == pytest.approx(0.0)
    assert result["retry_docs"] == retry_docs
