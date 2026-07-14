"""Generate node — formats the final result string in kb_search-compatible format."""

from __future__ import annotations

import json
import logging
import time

from backend.config import settings
from backend.rag.pipeline.state import RankedDoc

logger = logging.getLogger("derma6.rag")

_DISCLAIMER = (
    "Note: The local knowledge base did not contain sufficient relevant information "
    "for this query. The following response is based on general knowledge and should "
    "be verified with authoritative skincare sources.\n\n"
)


def _keep_relevant(docs: list, grades: list) -> list:
    """Drop the docs the CRAG grader marked non-relevant.

    When grades are missing/misaligned, or none of the docs cleared the grader,
    the docs are returned unchanged — this prunes noise (e.g. a Ceramides chunk
    retrieved for a sunscreen query) without ever emptying a non-empty set.
    """
    if not docs or not grades or len(grades) != len(docs):
        return docs
    kept = [d for d, g in zip(docs, grades) if g]
    return kept or docs


def generate(state: dict) -> dict:
    """LangGraph node. Formats the context string and emits the observability log."""
    t0 = time.monotonic()
    latencies: dict = dict(state.get("node_latencies", {}))

    retry_triggered: bool = state.get("retry_triggered", False)
    retry_score: float = state.get("retry_score", 0.0)
    llm_only: bool = state.get("llm_only_fallback", False)
    fallback_docs: list[RankedDoc] = state.get("fallback_docs", [])
    reranked_docs: list[RankedDoc] = state.get("reranked_docs", [])
    retry_docs: list[RankedDoc] = state.get("retry_docs", [])
    doc_grades: list[bool] = state.get("doc_grades", [])
    retry_grades: list[bool] = state.get("retry_grades", [])
    first_pass_score: float = state.get("first_pass_score", 0.0)
    fallback_strategy_used: str = state.get("fallback_strategy_used", "")

    # Determine source docs and routing label. Each KB path drops the chunks the
    # grader flagged as non-relevant so only on-topic context reaches the answer.
    if fallback_docs:
        docs: list[RankedDoc] = fallback_docs
        final_routing = "web-search"
    elif retry_triggered and retry_score >= settings.crag_relevance_threshold:
        docs = _keep_relevant(retry_docs, retry_grades)
        final_routing = "local-retry-succeeded"
    elif not llm_only:
        docs = _keep_relevant(reranked_docs, doc_grades)
        final_routing = "generate"
    else:
        # Web search yielded nothing and the KB grades stayed below threshold.
        # Prefer the closest local chunks we did retrieve over a bare "we don't
        # know"; only emit the pure disclaimer when retrieval was truly empty.
        salvaged = _keep_relevant(reranked_docs, doc_grades)
        if salvaged:
            docs = salvaged
            final_routing = "llm-only-salvaged"
        else:
            docs = []
            final_routing = "llm-only"

    # Format result string matching existing kb_search output format
    parts: list[str] = []
    sources: list[str] = []
    for doc in docs:
        if doc.content.strip():
            parts.append(doc.content.strip())
        if doc.source_name.strip() and doc.source_name not in sources:
            sources.append(doc.source_name)

    if not parts:
        result = _DISCLAIMER
    else:
        result = "\n\n---\n\n".join(parts)
        if sources:
            result += f"\n\nSources: {', '.join(sources)}"

    # RAG context JSON marker (same format as original kb_search)
    rag_meta = [
        {
            "source": d.source_name,
            "score": round(d.rerank_score if d.rerank_score else d.rrf_score, 3),
            "snippet": d.content.strip()[:150],
        }
        for d in docs
    ]
    result += f"\n\n__RAG_CONTEXT_JSON__: {json.dumps(rag_meta)}"

    # Pipeline metadata marker (separate, does not disturb extract_rag_context)
    pipeline_meta = {
        "final_routing": final_routing,
        "rag_fallback_triggered": final_routing not in ("generate", "local-retry-succeeded"),
        "retry_triggered": retry_triggered,
    }
    result += f"\n\n__RAG_PIPELINE_META__: {json.dumps(pipeline_meta)}"

    latencies["generate"] = (time.monotonic() - t0) * 1000
    total_ms = sum(latencies.values())

    # Structured observability log
    logger.info(
        "rag_pipeline_complete",
        extra={
            "event": "rag_pipeline_complete",
            "sub_query_count": len(state.get("sub_queries", [])),
            "hyde_fallback_count": state.get("hyde_fallback_count", 0),
            "bm25_fallback_count": state.get("bm25_fallback_count", 0),
            "dense_only_count": state.get("dense_only_count", 0),
            "sparse_only_count": state.get("sparse_only_count", 0),
            "rrf_merged_count": state.get("rrf_merged_count", 0),
            "chunk_count_after_rerank": len(docs),
            "first_pass_score": round(first_pass_score, 3),
            "retry_triggered": retry_triggered,
            "retry_score": round(retry_score, 3) if retry_triggered else None,
            "final_routing": final_routing,
            "total_latency_ms": round(total_ms),
            "node_latencies_ms": {k: round(v) for k, v in latencies.items()},
        },
    )

    return {
        "final_routing": final_routing,
        "result_string": result,
        "final_docs": docs,
        "node_latencies": latencies,
    }
