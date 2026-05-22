"""Tests for scripts/index_kb.py — no real network calls, no real API key required.

The test mocks OpenRouterEmbeddings.embed_documents to return fake vectors,
runs the indexing script's main() function directly, then verifies ChromaDB
contains 20 documents with correct metadata.
"""

from unittest.mock import patch

import pytest

# Skip entire module if chromadb native extension is unavailable (macOS Intel)
try:
    import chromadb_rust_bindings  # noqa: F401 — triggers the native extension load
    import chromadb
    _chromadb_ok = True
except Exception:
    _chromadb_ok = False

pytestmark = pytest.mark.skipif(
    not _chromadb_ok,
    reason="chromadb native extension unavailable on this platform",
)

# The number of .md files in knowledge_base/ (11 ingredients + 6 guides + 3 mens)
EXPECTED_DOC_COUNT = 20
FAKE_VECTOR = [0.1] * 256
COLLECTION_NAME = "skincare_kb"


def _fake_embed_documents(texts: list[str]) -> list[list[float]]:
    """Return one fake 256-dim vector per document — no network call."""
    return [FAKE_VECTOR for _ in texts]


class TestIndexKb:
    """End-to-end tests for the KB indexing pipeline (mocked embeddings)."""

    def test_all_documents_indexed(self, tmp_path):
        """Running main() indexes exactly 20 documents into ChromaDB."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        assert collection.count() == EXPECTED_DOC_COUNT, (
            f"Expected {EXPECTED_DOC_COUNT} documents but found {collection.count()}"
        )

    def test_metadata_fields_present_and_non_empty(self, tmp_path):
        """Each indexed document has non-empty source_name and topic_category."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)

        # Fetch all documents and verify metadata
        result = collection.get(include=["metadatas"])
        metadatas = result["metadatas"]

        assert len(metadatas) == EXPECTED_DOC_COUNT

        for meta in metadatas:
            assert "source_name" in meta, f"Missing source_name in {meta}"
            assert "topic_category" in meta, f"Missing topic_category in {meta}"
            assert "source_file" in meta, f"Missing source_file in {meta}"
            assert meta["source_name"], f"source_name is empty in {meta}"
            assert meta["topic_category"], f"topic_category is empty in {meta}"
            assert meta["source_file"], f"source_file is empty in {meta}"

    def test_topic_categories_are_valid(self, tmp_path):
        """All documents belong to one of the three expected topic categories."""
        expected_categories = {"ingredients", "guides", "mens"}

        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        result = collection.get(include=["metadatas"])

        actual_categories = {meta["topic_category"] for meta in result["metadatas"]}
        assert actual_categories == expected_categories, (
            f"Unexpected categories: {actual_categories}"
        )

    def test_idempotent_double_run(self, tmp_path):
        """Running main() twice does not duplicate documents (upsert is idempotent)."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))
            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        assert collection.count() == EXPECTED_DOC_COUNT, (
            f"After two runs expected {EXPECTED_DOC_COUNT} docs, found {collection.count()}"
        )

    def test_embed_documents_called_once_with_all_texts(self, tmp_path):
        """embed_documents is called exactly once with a list of 20 texts."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ) as mock_embed:
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        mock_embed.assert_called_once()
        call_args = mock_embed.call_args[0][0]  # first positional arg: list of texts
        assert len(call_args) == EXPECTED_DOC_COUNT, (
            f"embed_documents called with {len(call_args)} texts, expected {EXPECTED_DOC_COUNT}"
        )
