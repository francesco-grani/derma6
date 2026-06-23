"""Tests for the generate node."""

import json

import pytest

from backend.rag.pipeline.nodes.generate import generate
from backend.rag.pipeline.state import RankedDoc, initial_state


def _doc(doc_id: str, source: str = "Skincare Guide") -> RankedDoc:
    return RankedDoc(doc_id=doc_id, content=f"content of {doc_id}", source_name=source,
                     source_file="f.md", rrf_score=0.5, rerank_score=0.9, retrieval_path="dense")


def _base_state(**kwargs) -> dict:
    s = dict(initial_state("test query"))
    s.update(kwargs)
    return s


def test_happy_path_generates_rag_context_json():
    docs = [_doc("d1"), _doc("d2")]
    state = _base_state(reranked_docs=docs, first_pass_score=0.9)
    result = generate(state)
    assert "__RAG_CONTEXT_JSON__:" in result["result_string"]
    assert "Sources:" in result["result_string"]
    assert result["final_routing"] == "generate"


def test_rag_pipeline_meta_appended():
    docs = [_doc("d1")]
    state = _base_state(reranked_docs=docs, first_pass_score=0.9)
    result = generate(state)
    assert "__RAG_PIPELINE_META__:" in result["result_string"]
    # Parse the meta block
    marker = "__RAG_PIPELINE_META__: "
    idx = result["result_string"].find(marker)
    meta = json.loads(result["result_string"][idx + len(marker):].split("\n")[0])
    assert "final_routing" in meta
    assert "rag_fallback_triggered" in meta


def test_llm_only_path_prepends_disclaimer():
    state = _base_state(llm_only_fallback=True)
    result = generate(state)
    assert "local knowledge base" in result["result_string"].lower() or "Note:" in result["result_string"]
    assert result["final_routing"] == "llm-only"


def test_local_retry_succeeded_routing():
    from unittest.mock import patch
    docs = [_doc("d1")]
    state = _base_state(retry_triggered=True, retry_docs=docs, retry_score=0.8, first_pass_score=0.2)
    with patch("backend.rag.pipeline.nodes.generate.settings") as ms:
        ms.crag_relevance_threshold = 0.5
        result = generate(state)
    assert result["final_routing"] == "local-retry-succeeded"


def test_web_search_routing():
    docs = [_doc("d1", source="https://example.com")]
    state = _base_state(fallback_docs=docs, fallback_strategy_used="web-search")
    result = generate(state)
    assert result["final_routing"] == "web-search"


def test_empty_no_docs_returns_disclaimer():
    state = _base_state(llm_only_fallback=True)
    result = generate(state)
    # Must still produce a result string
    assert len(result["result_string"]) > 0


def test_final_routing_set_in_state():
    state = _base_state(reranked_docs=[_doc("d1")], first_pass_score=0.9)
    result = generate(state)
    assert result["final_routing"] in ("generate", "local-retry-succeeded", "web-search", "llm-only")
