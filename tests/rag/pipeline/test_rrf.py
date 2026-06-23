"""Tests for the RRF merge utility."""

import pytest

from backend.rag.pipeline.nodes._rrf import merge_sub_query_results, rrf_merge
from backend.rag.pipeline.state import RankedDoc


def _doc(doc_id: str, path: str = "dense") -> RankedDoc:
    return RankedDoc(doc_id=doc_id, content=f"content of {doc_id}", source_name="src",
                     source_file="f.md", rrf_score=0.0, rerank_score=0.0, retrieval_path=path)


def test_rrf_merge_no_overlap():
    a = [_doc("d1", "dense"), _doc("d2", "dense")]
    b = [_doc("d3", "sparse"), _doc("d4", "sparse")]
    result = rrf_merge([a, b], k=60)
    ids = [r.doc_id for r in result]
    assert set(ids) == {"d1", "d2", "d3", "d4"}
    # All scores positive
    for r in result:
        assert r.rrf_score > 0


def test_rrf_merge_overlap_sums_scores():
    a = [_doc("d1", "dense"), _doc("d2", "dense")]
    b = [_doc("d1", "sparse"), _doc("d3", "sparse")]
    result = rrf_merge([a, b], k=60)
    d1 = next(r for r in result if r.doc_id == "d1")
    d2 = next(r for r in result if r.doc_id == "d2")
    # d1 appears in both lists → higher score than d2 which only appears in one
    assert d1.rrf_score > d2.rrf_score
    assert d1.retrieval_path == "both"


def test_rrf_merge_empty_lists():
    result = rrf_merge([[], []], k=60)
    assert result == []


def test_rrf_merge_single_list():
    a = [_doc("d1"), _doc("d2"), _doc("d3")]
    result = rrf_merge([a], k=60)
    assert len(result) == 3
    # Rank 0 should have higher score than rank 1
    assert result[0].rrf_score > result[1].rrf_score


def test_rrf_k_smoothing():
    a = [_doc("d1")]
    b = [_doc("d2")]
    result_k60 = rrf_merge([a, b], k=60)
    result_k1 = rrf_merge([a, b], k=1)
    # With smaller k, rank-1 differences are amplified
    # Both should still produce positive scores
    for r in result_k60 + result_k1:
        assert r.rrf_score > 0


def test_merge_sub_query_results_sums_across_queries():
    sq1 = [_doc("d1"), _doc("d2")]
    sq1[0].rrf_score = 0.5
    sq1[1].rrf_score = 0.3

    sq2 = [_doc("d1"), _doc("d3")]
    sq2[0].rrf_score = 0.4
    sq2[1].rrf_score = 0.2

    result = merge_sub_query_results([sq1, sq2])
    d1 = next(r for r in result if r.doc_id == "d1")
    # d1 appears in both sub-queries → summed score 0.9
    assert abs(d1.rrf_score - 0.9) < 1e-9
    # Result sorted descending
    assert result[0].rrf_score >= result[1].rrf_score
