"""Unit tests for backend.tools.kb_search (patches module-level _rag_pipeline).

kb_search is a thin async wrapper around RagPipelineGraph.ainvoke — the actual
retrieval/formatting behavior (dedup, dividers, __RAG_CONTEXT_JSON__, etc.) is
covered by tests/rag/pipeline/test_generate.py against the pipeline's generate
node directly.
"""

from unittest.mock import AsyncMock

import pytest


class TestKbSearch:
    async def test_returns_pipeline_result(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        monkeypatch.setattr(
            kb_module._rag_pipeline, "ainvoke", AsyncMock(return_value="Retinol boosts cell turnover.\nSources: Paula's Choice")
        )

        result = await kb_module.kb_search.ainvoke("retinol benefits")

        assert result == "Retinol boosts cell turnover.\nSources: Paula's Choice"
        kb_module._rag_pipeline.ainvoke.assert_awaited_once_with("retinol benefits")

    async def test_pipeline_exception_returns_error_message(self, monkeypatch):
        from backend.tools import kb_search as kb_module

        monkeypatch.setattr(
            kb_module._rag_pipeline, "ainvoke", AsyncMock(side_effect=Exception("ChromaDB offline"))
        )

        result = await kb_module.kb_search.ainvoke("any query")

        assert "could not search" in result.lower() or "sorry" in result.lower()
