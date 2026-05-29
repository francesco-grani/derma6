"""Unit tests for backend/tools/kb_search.py"""

from unittest.mock import MagicMock, patch

import pytest

from backend.tools.kb_search import kb_search


def _make_doc(content: str, source: str, score: float = 0.85):
    doc = MagicMock()
    doc.content = content
    doc.source_name = source
    doc.score = score
    return doc


class TestKbSearchNormalPath:
    def test_returns_doc_content(self):
        doc = _make_doc("Retinol is a vitamin A derivative.", "Retinol Profile")
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = [doc]
            result = kb_search.invoke("what is retinol")
        assert "Retinol is a vitamin A derivative." in result

    def test_includes_source_line(self):
        doc = _make_doc("Niacinamide reduces pore size.", "Niacinamide Profile")
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = [doc]
            result = kb_search.invoke("niacinamide benefits")
        assert "Sources: Niacinamide Profile" in result

    def test_deduplicates_sources(self):
        docs = [
            _make_doc("Chunk one.", "Niacinamide Profile", 0.9),
            _make_doc("Chunk two.", "Niacinamide Profile", 0.8),
        ]
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = docs
            result = kb_search.invoke("niacinamide")
        # The "Sources:" line is deduplicated; the JSON footer has per-chunk entries
        sources_line = [l for l in result.splitlines() if l.startswith("Sources:")][0]
        assert sources_line.count("Niacinamide Profile") == 1

    def test_appends_rag_context_json_footer(self):
        doc = _make_doc("SPF protects against UV.", "SPF Actives Guide", 0.75)
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = [doc]
            result = kb_search.invoke("SPF")
        assert "__RAG_CONTEXT_JSON__:" in result

    def test_rag_context_json_contains_score_and_source(self):
        import json
        doc = _make_doc("AHA exfoliates.", "AHA Guide", 0.72)
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = [doc]
            result = kb_search.invoke("AHA")
        marker = "__RAG_CONTEXT_JSON__: "
        json_str = result[result.index(marker) + len(marker):]
        parsed = json.loads(json_str)
        assert parsed[0]["source"] == "AHA Guide"
        assert parsed[0]["score"] == 0.72
        assert "AHA exfoliates." in parsed[0]["snippet"]

    def test_separates_multiple_docs_with_divider(self):
        docs = [
            _make_doc("First chunk.", "Source A"),
            _make_doc("Second chunk.", "Source B"),
        ]
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = docs
            result = kb_search.invoke("query")
        assert "---" in result


class TestKbSearchEmptyDocs:
    def test_returns_no_results_message(self):
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = []
            result = kb_search.invoke("obscure query")
        assert "No relevant articles" in result


class TestKbSearchExceptionPath:
    def test_returns_error_message_on_exception(self):
        with patch("backend.tools.kb_search.Retriever") as MockRetriever:
            MockRetriever.return_value.query.side_effect = RuntimeError("DB unavailable")
            result = kb_search.invoke("retinol")
        assert "could not search" in result.lower()
