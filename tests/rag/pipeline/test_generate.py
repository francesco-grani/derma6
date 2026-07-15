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


def _rag_meta(result: dict) -> list[dict]:
    marker = "__RAG_CONTEXT_JSON__: "
    s = result["result_string"]
    return json.loads(s[s.find(marker) + len(marker):].split("\n")[0])


@pytest.mark.parametrize("logit", [3.61, 1.92, -2.02, -3.88, -6.0, 11.0])
def test_display_score_is_a_probability_not_a_raw_logit(logit):
    """The cross-encoder emits a ~-11..+11 logit. The UI renders score*100 as a
    percentage, so anything outside 0..1 here surfaces as 361% / -388%."""
    doc = _doc("d1")
    doc.rerank_score = logit
    result = generate(_base_state(reranked_docs=[doc], first_pass_score=0.9))
    score = _rag_meta(result)[0]["score"]
    assert 0.0 <= score <= 1.0


def test_display_score_preserves_reranker_ordering():
    hi, lo = _doc("hi"), _doc("lo")
    hi.rerank_score, lo.rerank_score = 3.61, -3.88
    result = generate(_base_state(reranked_docs=[hi, lo], first_pass_score=0.9))
    scores = [e["score"] for e in _rag_meta(result)]
    assert scores[0] > scores[1]


def test_unscored_web_fallback_doc_reports_none_not_zero():
    """Web-fallback docs never reach the reranker (rerank_score=0.0); reporting
    0 would render as a confident '0%' rather than 'unscored'."""
    web = RankedDoc(doc_id="web_0", content="web content", source_name="https://example.com",
                    source_file="web", rrf_score=0.0, rerank_score=0.0, retrieval_path="sparse")
    result = generate(_base_state(fallback_docs=[web]))
    assert result["final_routing"] == "web-search"
    assert _rag_meta(result)[0]["score"] is None
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
