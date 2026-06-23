"""Cross-encoder reranking node — scores candidates against the original query."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from backend.config import settings

logger = logging.getLogger("derma6.rag.rerank")

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

    try:
        encoder = get_cross_encoder()
        pairs = [(original_query, doc.content) for doc in candidates]

        scores = encoder.predict(pairs)

        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: float(x[1]), reverse=True)

        top_k = settings.rerank_top_k
        reranked = []
        for doc, score in scored[:top_k]:
            from dataclasses import replace as dc_replace
            doc.rerank_score = float(score)
            reranked.append(doc)

        latencies["rerank"] = (time.monotonic() - t0) * 1000
        return {"reranked_docs": reranked, "rerank_error": False, "node_latencies": latencies}

    except Exception as exc:
        logger.error("CrossEncoder reranking failed: %s — falling back to RRF order", exc)
        fallback = list(candidates[: settings.rerank_top_k])
        latencies["rerank"] = (time.monotonic() - t0) * 1000
        return {"reranked_docs": fallback, "rerank_error": True, "node_latencies": latencies}
