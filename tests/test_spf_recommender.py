"""Unit tests for backend.tools.spf_recommender."""

from unittest.mock import MagicMock, patch

import pytest

from backend.tools.spf_recommender import (
    _detect_low_spf_request,
    _format_recommendation,
    spf_recommender,
)
from backend.rag.retriever import RetrievedDoc


class TestDetectLowSpfRequest:
    @pytest.mark.parametrize("query", [
        "recommend SPF 30",
        "which spf30 sunscreen",
        "I want SPF 15",
        "spf 20 for daily use",
        "SPF 20 sunscreen recommendation",
        "SPF 15 is fine right?",
    ])
    def test_low_spf_detected(self, query):
        assert _detect_low_spf_request(query) is True

    @pytest.mark.parametrize("query", [
        "recommend SPF 50",
        "best SPF 50+ sunscreen",
        "PA+++ rated sunscreen",
        "what sunscreen should I use",
        "protect from UV rays",
        "SPF 300 is too high",  # 300, not 30
    ])
    def test_low_spf_not_detected(self, query):
        assert _detect_low_spf_request(query) is False

    def test_case_insensitive(self):
        assert _detect_low_spf_request("USE SPF 30") is True
        assert _detect_low_spf_request("use spf 30") is True


class TestFormatRecommendation:
    def test_empty_docs_returns_default(self):
        result = _format_recommendation([])
        assert "SPF 50+" in result
        assert "PA+++" in result

    def test_with_docs_includes_content(self):
        docs = [
            RetrievedDoc(content="Apply SPF 50 as the final step.", source_name="Guide A", score=0.9),
        ]
        result = _format_recommendation(docs)
        assert "SPF 50" in result
        assert "Guide A" in result

    def test_duplicate_sources_deduplicated(self):
        docs = [
            RetrievedDoc(content="Content 1", source_name="Guide A", score=0.9),
            RetrievedDoc(content="Content 2", source_name="Guide A", score=0.8),
        ]
        result = _format_recommendation(docs)
        assert result.count("Guide A") == 1

    def test_multiple_sources_listed(self):
        docs = [
            RetrievedDoc(content="C1", source_name="Source 1", score=0.9),
            RetrievedDoc(content="C2", source_name="Source 2", score=0.8),
        ]
        result = _format_recommendation(docs)
        assert "Source 1" in result
        assert "Source 2" in result

    def test_empty_content_skipped(self):
        docs = [
            RetrievedDoc(content="   ", source_name="Guide", score=0.9),
            RetrievedDoc(content="Real content", source_name="Real Source", score=0.8),
        ]
        result = _format_recommendation(docs)
        assert "Real content" in result


class TestSpfRecommenderTool:
    @patch("backend.tools.spf_recommender.Retriever")
    def test_low_spf_query_intercepted(self, mock_retriever_cls):
        result = spf_recommender.invoke("recommend SPF 30 for me")
        assert "SPF 50+" in result
        assert "SPF 30" in result
        mock_retriever_cls.assert_not_called()  # should not reach retriever

    @patch("backend.tools.spf_recommender.Retriever")
    def test_normal_query_calls_retriever(self, mock_retriever_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = [
            RetrievedDoc(content="SPF 50+ recommended daily.", source_name="WHO", score=0.85),
        ]
        mock_retriever_cls.return_value = mock_r

        result = spf_recommender.invoke("What sunscreen should I use?")
        mock_r.query.assert_called_once()
        assert "SPF" in result

    @patch("backend.tools.spf_recommender.Retriever")
    def test_retriever_returns_empty_uses_default(self, mock_retriever_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = []
        mock_retriever_cls.return_value = mock_r

        result = spf_recommender.invoke("sunscreen recommendation")
        assert "SPF 50+" in result
        assert "PA+++" in result

    @patch("backend.tools.spf_recommender.Retriever")
    def test_retriever_exception_returns_error(self, mock_retriever_cls):
        mock_retriever_cls.side_effect = Exception("DB offline")
        result = spf_recommender.invoke("what SPF to use?")
        assert "could not" in result.lower() or "sorry" in result.lower()

    @patch("backend.tools.spf_recommender.Retriever")
    def test_spf15_request_intercepted(self, mock_retriever_cls):
        result = spf_recommender.invoke("is SPF 15 enough?")
        assert "SPF 50+" in result
        mock_retriever_cls.assert_not_called()

    @patch("backend.tools.spf_recommender.Retriever")
    def test_output_includes_sources_from_docs(self, mock_retriever_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = [
            RetrievedDoc(content="Use broad-spectrum SPF 50+", source_name="Dermatology Today", score=0.9),
        ]
        mock_retriever_cls.return_value = mock_r

        result = spf_recommender.invoke("sunscreen advice")
        assert "Dermatology Today" in result
