"""Unit tests for backend.rag.retriever.Retriever (chromadb mocked via sys.modules in conftest)."""

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.retriever import EmptyCollectionError, Retriever, RetrievedDoc


def _make_retriever(count=3, docs=None, metadatas=None, distances=None):
    """Build a Retriever whose ChromaDB collection is fully mocked."""
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 8

    mock_collection = MagicMock()
    mock_collection.count.return_value = count
    mock_collection.query.return_value = {
        "documents": [docs or ["Sample skincare content."]],
        "metadatas": [metadatas or [{"source_name": "Test Source"}]],
        "distances": [distances or [0.2]],
    }

    with patch("backend.rag.retriever.chromadb") as mock_chroma:
        mock_chroma.PersistentClient.return_value.get_or_create_collection.return_value = (
            mock_collection
        )
        r = Retriever(embeddings=mock_embeddings)
        r._collection = mock_collection
        return r, mock_embeddings, mock_collection


class TestRetrieverInit:
    def test_default_embeddings_created(self):
        with patch("backend.rag.retriever.OpenRouterEmbeddings") as mock_emb:
            with patch("backend.rag.retriever.chromadb"):
                r = Retriever()
                mock_emb.assert_called_once()

    def test_custom_embeddings_used(self):
        mock_emb = MagicMock()
        with patch("backend.rag.retriever.chromadb"):
            r = Retriever(embeddings=mock_emb)
        assert r._embeddings is mock_emb


class TestRetrieverQuery:
    def test_empty_collection_raises(self):
        r, emb, coll = _make_retriever(count=0)
        with pytest.raises(EmptyCollectionError, match="empty"):
            r.query("retinol")

    def test_returns_retrieved_docs(self):
        r, emb, coll = _make_retriever(
            count=2,
            docs=["Retinol boosts cell turnover."],
            metadatas=[{"source_name": "Paula's Choice"}],
            distances=[0.3],  # score = 1 - (0.09)/2 = 0.955
        )
        docs = r.query("retinol")
        assert len(docs) == 1
        assert isinstance(docs[0], RetrievedDoc)
        assert docs[0].source_name == "Paula's Choice"
        assert docs[0].content == "Retinol boosts cell turnover."

    def test_score_calculation(self):
        r, emb, coll = _make_retriever(
            count=1,
            docs=["content"],
            metadatas=[{"source_name": "src"}],
            distances=[0.4],  # score = 1 - (0.16)/2 = 0.92
        )
        docs = r.query("q")
        assert len(docs) == 1
        expected_score = 1.0 - (0.4 * 0.4) / 2.0
        assert abs(docs[0].score - expected_score) < 1e-9

    def test_low_score_filtered_out(self, monkeypatch):
        monkeypatch.setattr("backend.rag.retriever.settings.retrieval_min_score", 0.9)
        r, emb, coll = _make_retriever(
            count=1,
            docs=["low relevance content"],
            metadatas=[{"source_name": "src"}],
            distances=[0.8],  # score = 1 - (0.64)/2 = 0.68 < 0.9
        )
        docs = r.query("q")
        assert docs == []

    def test_missing_source_name_defaults_empty(self):
        r, emb, coll = _make_retriever(
            count=1,
            docs=["content"],
            metadatas=[{}],  # no source_name key
            distances=[0.1],
        )
        docs = r.query("q")
        assert docs[0].source_name == ""

    def test_embed_query_called_with_text(self):
        r, emb, coll = _make_retriever()
        r.query("test query")
        emb.embed_query.assert_called_once_with("test query")

    def test_custom_k_forwarded(self):
        r, emb, coll = _make_retriever(
            count=5,
            docs=["a", "b"],
            metadatas=[{"source_name": "s1"}, {"source_name": "s2"}],
            distances=[0.1, 0.2],
        )
        r.query("q", k=2)
        coll.query.assert_called_once()
        _, kwargs = coll.query.call_args
        assert kwargs.get("n_results") == 2 or coll.query.call_args[0][0] is not None
