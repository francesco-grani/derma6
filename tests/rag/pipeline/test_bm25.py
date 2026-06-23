"""Tests for BM25Index singleton."""

import pytest

from backend.rag.pipeline.bm25_index import (
    BM25Index,
    BM25UnavailableError,
    get_bm25_index,
    reset_bm25_index,
)
from backend.rag.pipeline.state import RankedDoc


class _FakeCollection:
    def __init__(self, docs=None):
        self._docs = docs or [
            "Retinol is a vitamin A derivative used in anti-aging.",
            "Niacinamide reduces redness and hyperpigmentation.",
            "SPF protects skin from UV radiation.",
        ]

    def get(self, include=None):
        return {
            "documents": self._docs,
            "metadatas": [{"source_name": f"doc_{i}", "source_file": f"doc_{i}.md"}
                           for i in range(len(self._docs))],
            "ids": [f"id_{i}" for i in range(len(self._docs))],
        }


class _EmptyCollection:
    def get(self, include=None):
        return {"documents": [], "metadatas": [], "ids": []}


class _FailCollection:
    def get(self, include=None):
        raise RuntimeError("ChromaDB unavailable")


@pytest.fixture(autouse=True)
def reset():
    reset_bm25_index()
    yield
    reset_bm25_index()


def test_build_and_query():
    index = BM25Index(_FakeCollection())
    results = index.query("retinol aging", k=2)
    assert isinstance(results, list)
    assert all(isinstance(r, RankedDoc) for r in results)
    assert all(r.retrieval_path == "sparse" for r in results)


def test_query_returns_ranked_docs():
    index = BM25Index(_FakeCollection())
    results = index.query("niacinamide", k=3)
    # The niacinamide doc should be at the top
    assert len(results) >= 1
    assert "niacinamide" in results[0].content.lower()


def test_singleton_same_object():
    get_bm25_index(_FakeCollection())
    a = get_bm25_index()
    b = get_bm25_index()
    assert a is b


def test_singleton_requires_collection_on_first_call():
    with pytest.raises(BM25UnavailableError):
        get_bm25_index()


def test_error_on_empty_collection():
    with pytest.raises(BM25UnavailableError):
        BM25Index(_EmptyCollection())


def test_error_on_collection_failure():
    with pytest.raises(BM25UnavailableError):
        BM25Index(_FailCollection())
