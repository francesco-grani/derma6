"""Cross-encoder reranking node — scores candidates against the original query."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from backend.config import settings
from backend.rag.actives import extract_actives

logger = logging.getLogger("derma6.rag.rerank")


def _actives_boost(doc, query_actives: set[str]) -> float:
    """Return the score bonus for *doc* given the query's actives.

    Adds settings.actives_rerank_boost per canonical active the chunk shares
    with the query, so an ingredient-specific question surfaces the chunks that
    actually discuss that ingredient even when the cross-encoder rates a generic
    passage slightly higher. Returns 0.0 when boosting is disabled or there is
    no overlap.
    """
    weight = settings.actives_rerank_boost
    if not weight or not query_actives:
        return 0.0
    overlap = query_actives & doc.actives
    return weight * len(overlap)

# ── CrossEncoder singleton ────────────────────────────────────────────────────

_cross_encoder = None
_encoder_lock = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rerank")


def _load_cross_encoder():
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder
    from sentence_transformers import CrossEncoder

    t0 = time.monotonic()
    _cross_encoder = CrossEncoder(settings.reranker_model)
    elapsed = time.monotonic() - t0
    logger.info("CrossEncoder loaded: %s in %.1fs", settings.reranker_model, elapsed)
    return _cross_encoder


def get_cross_encoder():
    """Return the process-level CrossEncoder singleton (loads on first call)."""
    return _load_cross_encoder()


# ── Rerank node ───────────────────────────────────────────────────────────────

def rerank(state: dict) -> dict:
    """LangGraph node. Synchronous. Reranks candidate_docs by cross-encoder score."""
    from backend.rag.pipeline.state import RagState

    t0 = time.monotonic()
    candidates = state.get("candidate_docs", [])
    original_query = state["original_query"]
    latencies: dict = dict(state.get("node_latencies", {}))

    if not candidates:
        latencies["rerank"] = (time.monotonic() - t0) * 1000
        return {"reranked_docs": [], "rerank_error": False, "node_latencies": latencies}

    query_actives = extract_actives(original_query)

    try:
        encoder = get_cross_encoder()
        pairs = [(original_query, doc.content) for doc in candidates]

        scores = encoder.predict(pairs)

        # Fold in the actives boost before sorting so the ingredient signal
        # actually influences the final top-k selection (the cross-encoder
        # otherwise discards the RRF ordering entirely).
        scored = []
        for doc, score in zip(candidates, scores):
            effective = float(score) + _actives_boost(doc, query_actives)
            scored.append((doc, effective))
        scored.sort(key=lambda x: x[1], reverse=True)

        top_k = settings.rerank_top_k
        reranked = []
        for doc, effective in scored[:top_k]:
            doc.rerank_score = effective
            reranked.append(doc)

        latencies["rerank"] = (time.monotonic() - t0) * 1000
        return {"reranked_docs": reranked, "rerank_error": False, "node_latencies": latencies}

    except Exception as exc:
        logger.error("CrossEncoder reranking failed: %s — falling back to RRF order", exc)
        # Even without the cross-encoder, honour the actives signal by ordering
        # the RRF candidates by their overlap with the query's actives (stable
        # sort preserves RRF order within each overlap tier).
        fallback = sorted(
            candidates,
            key=lambda d: _actives_boost(d, query_actives),
            reverse=True,
        )[: settings.rerank_top_k]
        latencies["rerank"] = (time.monotonic() - t0) * 1000
        return {"reranked_docs": fallback, "rerank_error": True, "node_latencies": latencies}
