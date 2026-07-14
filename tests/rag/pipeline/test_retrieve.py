"""Tests for the hybrid_retrieve node (dense + sparse + RRF merge)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.retrieve import (
    _dense_retrieve,
    _get_llm,
    _get_retriever_collection,
    _sparse_retrieve,
    hybrid_retrieve,
)
from backend.rag.pipeline.state import RankedDoc


def _doc(doc_id: str, path: str = "dense") -> RankedDoc:
    return RankedDoc(doc_id=doc_id, content=f"content {doc_id}", source_name="src",
                     source_file="f.md", rrf_score=0.5, rerank_score=0.0, retrieval_path=path)


def _mock_settings(**overrides):
    ms = MagicMock()
    ms.hyde_timeout_seconds = 10
    ms.rag_debug_mode = False
    ms.retrieval_top_k = 4
    ms.retrieval_min_score = 0.0
    ms.rrf_k = 60
    ms.llm_model = "openai/gpt-4o-mini"
    ms.openrouter_api_key = "test-key"
    ms.openrouter_base_url = "https://openrouter.ai/api/v1"
    for k, v in overrides.items():
        setattr(ms, k, v)
    return ms


# ── _get_llm ──────────────────────────────────────────────────────────────────


def test_get_llm_is_a_singleton():
    import backend.rag.pipeline.nodes.retrieve as retrieve_module

    retrieve_module._llm = None
    with patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        first = _get_llm()
        second = _get_llm()

    assert first is second
    retrieve_module._llm = None


# ── _get_retriever_collection ────────────────────────────────────────────────


def test_get_retriever_collection_returns_underlying_collection():
    mock_retriever = MagicMock()
    mock_retriever._collection = "the-collection-sentinel"
    with patch("backend.rag.retriever.retriever", mock_retriever):
        assert _get_retriever_collection() == "the-collection-sentinel"


# ── _dense_retrieve ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dense_retrieve_happy_path_uses_hyde_embedding():
    collection = MagicMock()
    collection.query.return_value = {
        "documents": [["Retinol boosts turnover."]],
        "metadatas": [[{"source_name": "Src", "source_file": "f.md"}]],
        "distances": [[0.2]],
        "ids": [["d1"]],
    }
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

    mock_resp = MagicMock()
    mock_resp.content = "Hypothetical answer passage."

    with patch("backend.rag.pipeline.nodes.retrieve._get_llm") as mock_llm_fn, \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        docs, hyde_failed = await _dense_retrieve("what is retinol", collection, embeddings)

    assert hyde_failed is False
    assert len(docs) == 1
    assert docs[0].doc_id == "d1"
    assert docs[0].content == "Retinol boosts turnover."
    assert docs[0].retrieval_path == "dense"
    # HyDE's hypothetical passage was embedded, not the raw query
    embeddings.embed_query.assert_called_once_with("Hypothetical answer passage.")


@pytest.mark.asyncio
async def test_dense_retrieve_hyde_failure_falls_back_to_raw_query():
    collection = MagicMock()
    collection.query.return_value = {
        "documents": [["Some doc."]],
        "metadatas": [[{"source_name": "Src", "source_file": "f.md"}]],
        "distances": [[0.4]],
        "ids": [["d1"]],
    }
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1]

    with patch("backend.rag.pipeline.nodes.retrieve._get_llm") as mock_llm_fn, \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_llm_fn.return_value = mock_llm

        docs, hyde_failed = await _dense_retrieve("raw query text", collection, embeddings)

    assert hyde_failed is True
    embeddings.embed_query.assert_called_once_with("raw query text")
    assert len(docs) == 1


@pytest.mark.asyncio
async def test_dense_retrieve_hyde_timeout_falls_back_to_raw_query():
    collection = MagicMock()
    collection.query.return_value = {
        "documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]],
    }
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1]

    async def _slow(*args, **kwargs):
        await asyncio.sleep(100)

    with patch("backend.rag.pipeline.nodes.retrieve._get_llm") as mock_llm_fn, \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings(hyde_timeout_seconds=0.001)):
        mock_llm = MagicMock()
        mock_llm.ainvoke = _slow
        mock_llm_fn.return_value = mock_llm

        docs, hyde_failed = await _dense_retrieve("raw query", collection, embeddings)

    assert hyde_failed is True
    embeddings.embed_query.assert_called_once_with("raw query")


@pytest.mark.asyncio
async def test_dense_retrieve_filters_low_score_docs():
    collection = MagicMock()
    collection.query.return_value = {
        # distance 1.9 -> score = 1 - (1.9*1.9)/2 = 1 - 1.805 = -0.805 (below min_score 0.0)
        "documents": [["Low relevance doc.", "High relevance doc."]],
        "metadatas": [[{"source_name": "A", "source_file": "a.md"}, {"source_name": "B", "source_file": "b.md"}]],
        "distances": [[1.9, 0.1]],
        "ids": [["low", "high"]],
    }
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1]

    mock_resp = MagicMock()
    mock_resp.content = "hyde passage"

    with patch("backend.rag.pipeline.nodes.retrieve._get_llm") as mock_llm_fn, \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings(retrieval_min_score=0.0)):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        docs, _ = await _dense_retrieve("query", collection, embeddings)

    doc_ids = [d.doc_id for d in docs]
    assert "high" in doc_ids
    assert "low" not in doc_ids


# ── _sparse_retrieve ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sparse_retrieve_happy_path():
    from backend.rag.pipeline.bm25_index import BM25UnavailableError  # noqa: F401

    docs = [_doc("s1", "sparse")]
    mock_index = MagicMock()
    mock_index.query.return_value = docs

    with patch("backend.rag.pipeline.bm25_index.get_bm25_index", return_value=mock_index), \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        result_docs, bm25_failed = await _sparse_retrieve("query", collection=MagicMock())

    assert result_docs == docs
    assert bm25_failed is False


@pytest.mark.asyncio
async def test_sparse_retrieve_bm25_unavailable_returns_empty():
    from backend.rag.pipeline.bm25_index import BM25UnavailableError

    with patch("backend.rag.pipeline.bm25_index.get_bm25_index",
               side_effect=BM25UnavailableError("no corpus")):
        docs, bm25_failed = await _sparse_retrieve("query", collection=MagicMock())

    assert docs == []
    assert bm25_failed is True


@pytest.mark.asyncio
async def test_sparse_retrieve_generic_exception_returns_empty():
    with patch("backend.rag.pipeline.bm25_index.get_bm25_index",
               side_effect=RuntimeError("boom")):
        docs, bm25_failed = await _sparse_retrieve("query", collection=MagicMock())

    assert docs == []
    assert bm25_failed is True


# ── hybrid_retrieve (full node) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hybrid_retrieve_merges_dense_and_sparse_single_sub_query():
    dense_docs = [_doc("d1", "dense")]
    sparse_docs = [_doc("s1", "sparse")]

    with patch("backend.rag.pipeline.nodes.retrieve._get_retriever_collection", return_value=MagicMock()), \
         patch("backend.rag.embeddings.OpenRouterEmbeddings", return_value=MagicMock()), \
         patch("backend.rag.pipeline.nodes.retrieve._dense_retrieve",
               new_callable=AsyncMock, return_value=(dense_docs, False)), \
         patch("backend.rag.pipeline.nodes.retrieve._sparse_retrieve",
               new_callable=AsyncMock, return_value=(sparse_docs, False)), \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        state = {"original_query": "test query", "node_latencies": {}}
        result = await hybrid_retrieve(state)

    assert result["hyde_fallback_count"] == 0
    assert result["bm25_fallback_count"] == 0
    assert result["dense_only_count"] == 1
    assert result["sparse_only_count"] == 1
    assert result["rrf_merged_count"] == 2
    assert {d.doc_id for d in result["candidate_docs"]} == {"d1", "s1"}
    assert "hybrid_retrieve" in result["node_latencies"]


@pytest.mark.asyncio
async def test_hybrid_retrieve_counts_fallbacks_across_sub_queries():
    with patch("backend.rag.pipeline.nodes.retrieve._get_retriever_collection", return_value=MagicMock()), \
         patch("backend.rag.embeddings.OpenRouterEmbeddings", return_value=MagicMock()), \
         patch("backend.rag.pipeline.nodes.retrieve._dense_retrieve",
               new_callable=AsyncMock, side_effect=[([], True), ([], False)]), \
         patch("backend.rag.pipeline.nodes.retrieve._sparse_retrieve",
               new_callable=AsyncMock, side_effect=[([], False), ([], True)]), \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        state = {
            "original_query": "test query",
            "sub_queries": ["sub query one", "sub query two"],
            "node_latencies": {},
        }
        result = await hybrid_retrieve(state)

    assert result["hyde_fallback_count"] == 1
    assert result["bm25_fallback_count"] == 1
    assert result["candidate_docs"] == []


@pytest.mark.asyncio
async def test_hybrid_retrieve_defaults_sub_queries_to_original_query():
    with patch("backend.rag.pipeline.nodes.retrieve._get_retriever_collection", return_value=MagicMock()), \
         patch("backend.rag.embeddings.OpenRouterEmbeddings", return_value=MagicMock()), \
         patch("backend.rag.pipeline.nodes.retrieve._dense_retrieve",
               new_callable=AsyncMock, return_value=([], False)) as mock_dense, \
         patch("backend.rag.pipeline.nodes.retrieve._sparse_retrieve",
               new_callable=AsyncMock, return_value=([], False)), \
         patch("backend.rag.pipeline.nodes.retrieve.settings", _mock_settings()):
        state = {"original_query": "only this query", "node_latencies": {}}
        await hybrid_retrieve(state)

    mock_dense.assert_awaited_once()
    assert mock_dense.await_args.args[0] == "only this query"
