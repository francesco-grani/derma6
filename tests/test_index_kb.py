"""Tests for scripts/index_kb.py — no real network calls, no real API key required.

The test mocks OpenRouterEmbeddings.embed_documents to return fake vectors,
runs the indexing script's main() function directly, then verifies ChromaDB
contains the expected chunks with correct metadata.

After the chunking refactor (TB4) the collection holds one chunk per
CHUNK_SIZE window, not one document per file. The exact count depends on
file length and CHUNK_SIZE, so tests use a lower-bound (>= 20, one per file)
rather than an exact count.
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

# Lower bound: at least one chunk per source file (20 files)
MIN_DOC_COUNT = 20
FAKE_VECTOR = [0.1] * 256
COLLECTION_NAME = "skincare_kb"


def _fake_embed_documents(texts: list[str]) -> list[list[float]]:
    """Return one fake 256-dim vector per chunk — no network call."""
    return [FAKE_VECTOR for _ in texts]


class TestIndexKb:
    """End-to-end tests for the KB indexing pipeline (mocked embeddings)."""

    def test_all_documents_indexed(self, tmp_path):
        """Running main() indexes at least one chunk per source file."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        assert collection.count() >= MIN_DOC_COUNT, (
            f"Expected at least {MIN_DOC_COUNT} chunks but found {collection.count()}"
        )

    def test_metadata_fields_present_and_non_empty(self, tmp_path):
        """Each indexed chunk has non-empty source_name, topic_category, source_file,
        and a non-negative chunk_index."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)

        result = collection.get(include=["metadatas"])
        metadatas = result["metadatas"]

        assert len(metadatas) >= MIN_DOC_COUNT

        for meta in metadatas:
            assert "source_name" in meta, f"Missing source_name in {meta}"
            assert "topic_category" in meta, f"Missing topic_category in {meta}"
            assert "source_file" in meta, f"Missing source_file in {meta}"
            assert "chunk_index" in meta, f"Missing chunk_index in {meta}"
            assert meta["source_name"], f"source_name is empty in {meta}"
            assert meta["topic_category"], f"topic_category is empty in {meta}"
            assert meta["source_file"], f"source_file is empty in {meta}"
            assert meta["chunk_index"] >= 0, f"chunk_index is negative in {meta}"

    def test_topic_categories_are_valid(self, tmp_path):
        """All chunks belong to one of the three expected topic categories."""
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
        """Running main() twice does not duplicate chunks (upsert is idempotent)."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))
            first_count = chromadb.PersistentClient(path=str(tmp_path)) \
                .get_or_create_collection(name=COLLECTION_NAME).count()
            main(chroma_dir=str(tmp_path))

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        assert collection.count() == first_count, (
            f"After two runs expected {first_count} chunks, found {collection.count()}"
        )

    def test_embed_documents_called_once_with_all_chunks(self, tmp_path):
        """embed_documents is called exactly once with all chunk texts (>= 20)."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ) as mock_embed:
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))

        mock_embed.assert_called_once()
        call_args = mock_embed.call_args[0][0]
        assert len(call_args) >= MIN_DOC_COUNT, (
            f"embed_documents called with {len(call_args)} texts, expected >= {MIN_DOC_COUNT}"
        )

    def test_reset_clears_collection(self, tmp_path):
        """Running main(reset=True) removes stale entries from a previous index."""
        with patch(
            "backend.rag.embeddings.OpenRouterEmbeddings.embed_documents",
            side_effect=_fake_embed_documents,
        ):
            from scripts.index_kb import main

            main(chroma_dir=str(tmp_path))
            first_count = chromadb.PersistentClient(path=str(tmp_path)) \
                .get_or_create_collection(name=COLLECTION_NAME).count()
            main(chroma_dir=str(tmp_path), reset=True)

        client = chromadb.PersistentClient(path=str(tmp_path))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        assert collection.count() == first_count, (
            f"After reset+reindex expected {first_count} chunks, found {collection.count()}"
        )
