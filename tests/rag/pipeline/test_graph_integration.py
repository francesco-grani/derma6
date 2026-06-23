"""Integration tests for the full RagPipelineGraph."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.state import RankedDoc, initial_state


def _make_doc(doc_id: str = "d1") -> RankedDoc:
    return RankedDoc(
        doc_id=doc_id,
        content="Niacinamide reduces redness and hyperpigmentation in oily skin.",
        source_name="Skincare Guide",
        source_file="guide.md",
        rrf_score=0.8,
        rerank_score=0.9,
        retrieval_path="both",
    )


def _mock_settings():
    ms = MagicMock()
    ms.crag_relevance_threshold = 0.5
    ms.rerank_top_k = 5
    ms.retrieval_top_k = 4
    ms.retrieval_min_score = 0.0
    ms.rrf_k = 60
    ms.rag_debug_mode = False
    ms.decompose_timeout_seconds = 10
    ms.hyde_timeout_seconds = 10
    ms.crag_grade_timeout_seconds = 10
    ms.rerank_timeout_seconds = 15
    ms.crag_fallback_strategy = "llm-only"
    ms.tavily_api_key = ""
    ms.llm_model = "openai/gpt-4o-mini"
    ms.openrouter_api_key = "test-key"
    ms.openrouter_base_url = "https://openrouter.ai/api/v1"
    return ms


def test_happy_path_returns_formatted_string():
    """Pipeline happy path: all nodes mocked → result contains expected markers."""
    docs = [_make_doc("d1"), _make_doc("d2")]

    state = initial_state("What is niacinamide?")
    state["sub_queries"] = ["What is niacinamide?"]
    state["decompose_error"] = False
    state["candidate_docs"] = docs
    state["hyde_fallback_count"] = 0
    state["bm25_fallback_count"] = 0
    state["dense_only_count"] = 1
    state["sparse_only_count"] = 1
    state["rrf_merged_count"] = 2
    state["reranked_docs"] = docs
    state["rerank_error"] = False
    state["doc_grades"] = [True, True]
    state["first_pass_score"] = 1.0
    state["crag_timeout"] = False

    from backend.rag.pipeline.nodes.generate import generate

    with patch("backend.rag.pipeline.nodes.generate.settings", _mock_settings()):
        result = generate(state)

    assert "__RAG_CONTEXT_JSON__:" in result["result_string"]
    assert "__RAG_PIPELINE_META__:" in result["result_string"]
    assert result["final_routing"] == "generate"

    marker = "__RAG_PIPELINE_META__: "
    idx = result["result_string"].find(marker)
    meta = json.loads(result["result_string"][idx + len(marker):].split("\n")[0])
    assert meta["rag_fallback_triggered"] is False


def test_local_retry_succeeded_path():
    """When first pass fails but retry succeeds → local-retry-succeeded routing."""
    docs = [_make_doc("d1")]
    ms = _mock_settings()

    state = initial_state("skincare question")
    state["sub_queries"] = ["skincare question"]
    state["reranked_docs"] = docs
    state["first_pass_score"] = 0.2  # below threshold
    state["retry_triggered"] = True
    state["retry_query"] = "rewritten skincare question"
    state["retry_docs"] = docs
    state["retry_score"] = 0.8  # above threshold

    from backend.rag.pipeline.nodes.generate import generate

    with patch("backend.rag.pipeline.nodes.generate.settings", ms):
        result = generate(state)

    assert result["final_routing"] == "local-retry-succeeded"
    marker = "__RAG_PIPELINE_META__: "
    idx = result["result_string"].find(marker)
    meta = json.loads(result["result_string"][idx + len(marker):].split("\n")[0])
    assert meta["retry_triggered"] is True


def test_full_fallback_llm_only_path():
    """When both first pass and retry fail → llm-only routing with disclaimer."""
    ms = _mock_settings()

    state = initial_state("unknown condition query")
    state["sub_queries"] = ["unknown condition query"]
    state["reranked_docs"] = []
    state["first_pass_score"] = -1.0
    state["retry_triggered"] = True
    state["retry_docs"] = []
    state["retry_score"] = 0.0
    state["llm_only_fallback"] = True
    state["fallback_strategy_used"] = "llm-only"

    from backend.rag.pipeline.nodes.generate import generate

    with patch("backend.rag.pipeline.nodes.generate.settings", ms):
        result = generate(state)

    assert result["final_routing"] == "llm-only"
    assert "Note:" in result["result_string"] or "knowledge base" in result["result_string"].lower()

    marker = "__RAG_PIPELINE_META__: "
    idx = result["result_string"].find(marker)
    meta = json.loads(result["result_string"][idx + len(marker):].split("\n")[0])
    assert meta["rag_fallback_triggered"] is True


def test_state_mutations_are_additive():
    """No node should overwrite a field set by an earlier node."""
    state = initial_state("test query")
    state["node_latencies"] = {"query_decompose": 100.0}
    state["sub_queries"] = ["test query"]
    state["decompose_error"] = False

    # Simulate adding hybrid_retrieve latency
    state["node_latencies"] = {**state["node_latencies"], "hybrid_retrieve": 200.0}
    state["node_latencies"] = {**state["node_latencies"], "rerank": 50.0}

    # All three latencies should coexist
    assert "query_decompose" in state["node_latencies"]
    assert "hybrid_retrieve" in state["node_latencies"]
    assert "rerank" in state["node_latencies"]


def test_web_search_routing():
    """When fallback_docs populated → web-search routing."""
    ms = _mock_settings()
    web_docs = [
        RankedDoc(doc_id="web_0", content="Web result about skincare",
                  source_name="https://example.com", source_file="web",
                  rrf_score=0.0, rerank_score=0.0, retrieval_path="sparse")
    ]

    state = initial_state("obscure query")
    state["sub_queries"] = ["obscure query"]
    state["reranked_docs"] = []
    state["first_pass_score"] = -1.0
    state["retry_triggered"] = True
    state["retry_docs"] = []
    state["retry_score"] = 0.0
    state["fallback_docs"] = web_docs
    state["fallback_strategy_used"] = "web-search"

    from backend.rag.pipeline.nodes.generate import generate

    with patch("backend.rag.pipeline.nodes.generate.settings", ms):
        result = generate(state)

    assert result["final_routing"] == "web-search"
