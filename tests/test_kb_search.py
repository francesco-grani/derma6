"""Unit tests for backend.tools.kb_search (patches module-level _retriever)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.rag.retriever import RetrievedDoc


# ── Helpers ───────────────────────────────────────────────────────────────────


def _doc(content: str, source: str, score: float = 0.85) -> RetrievedDoc:
    return RetrievedDoc(content=content, source_name=source, score=score)


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestKbSearch:
    def test_returns_content_and_sources(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.return_value = [
            _doc("Retinol boosts cell turnover.", "Paula's Choice", 0.88),
            _doc("Apply at night.", "INCIDecoder", 0.80),
        ]
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("retinol benefits")

        assert "Retinol boosts cell turnover." in result
        assert "Paula's Choice" in result
        assert "INCIDecoder" in result

    def test_no_docs_returns_not_found_message(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.return_value = []
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("completely unrelated query")
        assert "No relevant articles" in result

    def test_rag_context_json_appended(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.return_value = [
            _doc("Niacinamide content.", "AAD", 0.82),
        ]
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("niacinamide")
        assert "__RAG_CONTEXT_JSON__:" in result

        marker = "__RAG_CONTEXT_JSON__: "
        idx = result.find(marker)
        raw = result[idx + len(marker):].strip()
        parsed = json.loads(raw)
        assert isinstance(parsed, list)
        assert parsed[0]["source"] == "AAD"
        assert parsed[0]["score"] == 0.82

    def test_empty_content_doc_skipped(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.return_value = [
            _doc("   ", "Source A", 0.9),  # whitespace-only content
            _doc("Real content here.", "Source B", 0.8),
        ]
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("query")
        assert "Real content here." in result

    def test_duplicate_sources_deduplicated(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.return_value = [
            _doc("Content 1.", "Same Source", 0.9),
            _doc("Content 2.", "Same Source", 0.8),
        ]
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("query")
        # Source should appear only once in the Sources line
        sources_line = [l for l in result.splitlines() if l.startswith("Sources:")][0]
        assert sources_line.count("Same Source") == 1

    def test_retriever_exception_returns_error_message(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.side_effect = Exception("ChromaDB offline")
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("any query")
        assert "could not search" in result.lower() or "sorry" in result.lower()

    def test_sections_separated_by_divider(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        mock_r = MagicMock()
        mock_r.query.return_value = [
            _doc("First doc.", "Src A", 0.9),
            _doc("Second doc.", "Src B", 0.8),
        ]
        monkeypatch.setattr(kb_module, "retriever", mock_r)

        from backend.tools.kb_search import kb_search
        result = kb_search.invoke("query")
        assert "---" in result
