"""Tests for OpenRouterEmbeddings — all HTTP calls are mocked via unittest.mock."""

import unittest
from unittest.mock import MagicMock, patch

import httpx
import pytest


class TestOpenRouterEmbeddings:
    """Tests for OpenRouterEmbeddings."""

    def _make_mock_response(self, vectors: list[list[float]]) -> MagicMock:
        """Build a mock httpx.Response whose .json() returns an OpenAI-style body."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"embedding": vec, "index": i} for i, vec in enumerate(vectors)]
        }
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    @patch("backend.rag.embeddings.httpx.Client")
    def test_embed_documents_calls_correct_endpoint(self, mock_client_cls):
        """POST must be sent to {base_url}/embeddings with the right body."""
        vectors = [[0.1, 0.2, 0.3]]
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._make_mock_response(vectors)
        mock_client_cls.return_value = mock_client

        from backend.config import settings
        from backend.rag.embeddings import OpenRouterEmbeddings

        emb = OpenRouterEmbeddings()
        emb.embed_documents(["hello world"])

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url") or call_args.args[0]
        assert url == f"{settings.openrouter_base_url}/embeddings"

        json_payload = call_args[1].get("json") or call_args.kwargs.get("json")
        assert json_payload["model"] == settings.embedding_model
        assert json_payload["input"] == ["hello world"]

    @patch("backend.rag.embeddings.httpx.Client")
    def test_embed_documents_parses_response(self, mock_client_cls):
        """embed_documents must return the correct float vectors from the response."""
        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._make_mock_response(vectors)
        mock_client_cls.return_value = mock_client

        from backend.rag.embeddings import OpenRouterEmbeddings

        emb = OpenRouterEmbeddings()
        result = emb.embed_documents(["doc1", "doc2"])

        assert result == vectors

    @patch("backend.rag.embeddings.httpx.Client")
    def test_embed_query_returns_single_vector(self, mock_client_cls):
        """embed_query must return a single flat list, not a list of lists."""
        vector = [0.7, 0.8, 0.9]
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._make_mock_response([vector])
        mock_client_cls.return_value = mock_client

        from backend.rag.embeddings import OpenRouterEmbeddings

        emb = OpenRouterEmbeddings()
        result = emb.embed_query("single query")

        assert result == vector
        # Must be a flat list of floats, not a list of lists
        assert isinstance(result[0], float)
