"""Tests for the rerank node."""

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.rerank import rerank
from backend.rag.pipeline.state import RankedDoc


def _doc(doc_id: str, content: str = "content") -> RankedDoc:
    return RankedDoc(doc_id=doc_id, content=content, source_name="src",
                     source_file="f.md", rrf_score=0.5, rerank_score=0.0, retrieval_path="dense")


def _state(candidates: list[RankedDoc]) -> dict:
    return {"original_query": "test query", "candidate_docs": candidates, "node_latencies": {}}


def test_empty_candidates_passthrough():
    result = rerank(_state([]))
    assert result["reranked_docs"] == []
    assert result["rerank_error"] is False


def test_reranks_by_score_descending():
    docs = [_doc("d1"), _doc("d2"), _doc("d3")]
    # scores: d1=0.1, d2=0.9, d3=0.5 → expected order: d2, d3, d1
    mock_encoder = MagicMock()
    mock_encoder.predict.return_value = [0.1, 0.9, 0.5]

    with patch("backend.rag.pipeline.nodes.rerank.get_cross_encoder", return_value=mock_encoder):
        with patch("backend.rag.pipeline.nodes.rerank.settings") as ms:
            ms.rerank_top_k = 3
            result = rerank(_state(docs))

    reranked = result["reranked_docs"]
    assert [r.doc_id for r in reranked] == ["d2", "d3", "d1"]
    assert result["rerank_error"] is False


def test_truncates_to_top_k():
    docs = [_doc(f"d{i}") for i in range(10)]
    mock_encoder = MagicMock()
    mock_encoder.predict.return_value = list(range(10, 0, -1))

    with patch("backend.rag.pipeline.nodes.rerank.get_cross_encoder", return_value=mock_encoder):
        with patch("backend.rag.pipeline.nodes.rerank.settings") as ms:
            ms.rerank_top_k = 3
            result = rerank(_state(docs))

    assert len(result["reranked_docs"]) == 3


def test_cross_encoder_failure_falls_back():
    docs = [_doc("d1"), _doc("d2")]
    mock_encoder = MagicMock()
    mock_encoder.predict.side_effect = RuntimeError("model error")

    with patch("backend.rag.pipeline.nodes.rerank.get_cross_encoder", return_value=mock_encoder):
        with patch("backend.rag.pipeline.nodes.rerank.settings") as ms:
            ms.rerank_top_k = 5
            result = rerank(_state(docs))

    assert result["rerank_error"] is True
    assert len(result["reranked_docs"]) == 2  # original order preserved


def test_rerank_score_attached():
    docs = [_doc("d1"), _doc("d2")]
    mock_encoder = MagicMock()
    mock_encoder.predict.return_value = [0.8, 0.3]

    with patch("backend.rag.pipeline.nodes.rerank.get_cross_encoder", return_value=mock_encoder):
        with patch("backend.rag.pipeline.nodes.rerank.settings") as ms:
            ms.rerank_top_k = 2
            result = rerank(_state(docs))

    assert result["reranked_docs"][0].rerank_score == pytest.approx(0.8)
    assert result["reranked_docs"][1].rerank_score == pytest.approx(0.3)
