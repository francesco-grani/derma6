"""BM25 sparse retrieval index — process-lifetime singleton over the ChromaDB corpus."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("derma6.rag.bm25")

_singleton: Optional["BM25Index"] = None


class BM25UnavailableError(Exception):
    """Raised when the BM25 index cannot be built or queried."""


class BM25Index:
    """In-memory BM25Okapi index built from the ChromaDB corpus at startup."""

    def __init__(self, collection) -> None:  # collection: chromadb.Collection
        from rank_bm25 import BM25Okapi

        t0 = time.monotonic()
        try:
            result = collection.get(include=["documents", "metadatas"])
        except Exception as exc:
            raise BM25UnavailableError(f"Failed to fetch corpus from ChromaDB: {exc}") from exc

        docs = result.get("documents") or []
        metas = result.get("metadatas") or []
        ids = result.get("ids") or []

        if not docs:
            raise BM25UnavailableError("ChromaDB collection is empty — cannot build BM25 index.")

        self._docs: list[str] = docs
        self._metas: list[dict] = metas
        self._ids: list[str] = ids

        tokenised = [d.lower().split() for d in docs]
        self._bm25 = BM25Okapi(tokenised)

        elapsed = time.monotonic() - t0
        logger.info("BM25 index built: %d documents in %.2fs", len(docs), elapsed)

    def query(self, text: str, k: int = 4) -> list:
        """Return top-k RankedDoc objects from sparse BM25 retrieval."""
        from backend.rag.pipeline.state import RankedDoc

        tokens = text.lower().split()
        scores = self._bm25.get_scores(tokens)

        # Pair (score, idx), sort descending, take top-k
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:k]

        results = []
        max_score = ranked[0][1] if ranked and ranked[0][1] > 0 else 1.0
        for idx, score in ranked:
            if score <= 0:
                continue
            meta = self._metas[idx] if idx < len(self._metas) else {}
            normalised = score / max_score if max_score > 0 else 0.0
            results.append(
                RankedDoc(
                    doc_id=self._ids[idx] if idx < len(self._ids) else f"bm25_{idx}",
                    content=self._docs[idx],
                    source_name=meta.get("source_name", ""),
                    source_file=meta.get("source_file", ""),
                    rrf_score=normalised,
                    rerank_score=0.0,
                    retrieval_path="sparse",
                )
            )
        return results


def get_bm25_index(collection=None) -> BM25Index:
    """Return the process-level singleton, building it on first call.

    Args:
        collection: chromadb.Collection — required only on the first call.
    """
    global _singleton
    if _singleton is None:
        if collection is None:
            raise BM25UnavailableError(
                "BM25 index has not been initialised. Pass the ChromaDB collection on first call."
            )
        _singleton = BM25Index(collection)
    return _singleton


def reset_bm25_index() -> None:
    """Reset the singleton — used in tests and after KB re-indexing."""
    global _singleton
    _singleton = None
