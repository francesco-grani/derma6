"""Tests for Retriever — all ChromaDB and embedding calls are mocked."""

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.retriever import EmptyCollectionError, RetrievedDoc


def _make_chroma_result(
    documents: list[str],
    source_names: list[str],
    distances: list[float],
) -> dict:
    """Build a ChromaDB-style query result dict."""
    return {
        "documents": [documents],
        "metadatas": [[{"source_name": sn} for sn in source_names]],
        "distances": [distances],
    }


class TestRetriever:
    """Tests for the Retriever class."""

    def _make_retriever(self, mock_collection, mock_embeddings):
        """Instantiate Retriever with both ChromaDB and embeddings fully mocked."""
        with patch("backend.rag.retriever.chromadb.PersistentClient") as mock_chroma_cls:
            mock_chroma_client = MagicMock()
            mock_chroma_cls.return_value = mock_chroma_client
            mock_chroma_client.get_or_create_collection.return_value = mock_collection

            from backend.rag.retriever import Retriever

            retriever = Retriever(embeddings=mock_embeddings)

        # Replace the collection after construction so we can control it in tests
        retriever._collection = mock_collection
        return retriever

    def test_query_returns_retrieved_docs(self):
        """Two results above the threshold → 2 RetrievedDoc objects returned."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        # distances of 0.5 and 0.6 → scores 0.5 and 0.4, both >= 0.3 threshold
        mock_collection.query.return_value = _make_chroma_result(
            documents=["doc A content", "doc B content"],
            source_names=["source_a", "source_b"],
            distances=[0.5, 0.6],
        )

        retriever = self._make_retriever(mock_collection, mock_embeddings)
        results = retriever.query("best cleanser for oily skin")

        assert len(results) == 2
        assert all(isinstance(r, RetrievedDoc) for r in results)
        assert results[0].content == "doc A content"
        assert results[0].source_name == "source_a"
        assert abs(results[0].score - 0.5) < 1e-9
        assert results[1].content == "doc B content"
        assert results[1].source_name == "source_b"
        assert abs(results[1].score - 0.4) < 1e-9

    def test_query_filters_below_threshold(self):
        """One result above threshold, one below → only 1 returned."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        # distance 0.5 → score 0.5 (above 0.3); distance 0.8 → score 0.2 (below 0.3)
        mock_collection.query.return_value = _make_chroma_result(
            documents=["doc A content", "doc B content"],
            source_names=["source_a", "source_b"],
            distances=[0.5, 0.8],
        )

        retriever = self._make_retriever(mock_collection, mock_embeddings)
        results = retriever.query("niacinamide benefits")

        assert len(results) == 1
        assert results[0].source_name == "source_a"
        assert results[0].score >= 0.3

    def test_empty_collection_raises_error(self):
        """EmptyCollectionError raised when collection.count() returns 0."""
        mock_embeddings = MagicMock()

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0

        retriever = self._make_retriever(mock_collection, mock_embeddings)

        with pytest.raises(EmptyCollectionError):
            retriever.query("anything")

        # embed_query must NOT be called if the collection is empty
        mock_embeddings.embed_query.assert_not_called()

    def test_embed_documents_called_with_text(self):
        """embed_query must be called with the exact query text."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.query.return_value = _make_chroma_result(
            documents=["some doc"],
            source_names=["src"],
            distances=[0.4],
        )

        retriever = self._make_retriever(mock_collection, mock_embeddings)
        query_text = "how to layer retinol and niacinamide"
        retriever.query(query_text)

        mock_embeddings.embed_query.assert_called_once_with(query_text)
