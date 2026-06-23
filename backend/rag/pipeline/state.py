"""State schema for the agentic RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TypedDict


@dataclass
class RankedDoc:
    """A retrieved document with all retrieval scores attached."""

    doc_id: str
    content: str
    source_name: str
    source_file: str
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    retrieval_path: str = "dense"  # "dense" | "sparse" | "both"


class RagState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────
    original_query: str

    # ── Decomposition ────────────────────────────────────────────────
    sub_queries: list[str]
    decompose_error: bool

    # ── Retrieval ────────────────────────────────────────────────────
    candidate_docs: list[RankedDoc]
    hyde_fallback_count: int
    bm25_fallback_count: int
    dense_only_count: int
    sparse_only_count: int
    rrf_merged_count: int

    # ── Reranking ────────────────────────────────────────────────────
    reranked_docs: list[RankedDoc]
    rerank_error: bool

    # ── CRAG first pass ──────────────────────────────────────────────
    doc_grades: list[bool]
    first_pass_score: float  # -1.0 if no docs; 0.0–1.0 otherwise
    crag_timeout: bool

    # ── Local retry ──────────────────────────────────────────────────
    retry_triggered: bool
    retry_query: Optional[str]
    retry_docs: list[RankedDoc]
    retry_score: float

    # ── External fallback ────────────────────────────────────────────
    fallback_strategy: str          # configured value: "web-search" | "llm-only"
    fallback_strategy_used: str     # actual value used (may differ if web degraded)
    fallback_docs: list[RankedDoc]
    llm_only_fallback: bool

    # ── Output ───────────────────────────────────────────────────────
    final_routing: str  # "generate" | "local-retry-succeeded" | "web-search" | "llm-only"
    result_string: str

    # ── Observability ────────────────────────────────────────────────
    node_latencies: dict[str, float]


def initial_state(query: str, fallback_strategy: str = "llm-only") -> RagState:
    """Return a fully initialised RagState for a new pipeline invocation."""
    return RagState(
        original_query=query,
        sub_queries=[],
        decompose_error=False,
        candidate_docs=[],
        hyde_fallback_count=0,
        bm25_fallback_count=0,
        dense_only_count=0,
        sparse_only_count=0,
        rrf_merged_count=0,
        reranked_docs=[],
        rerank_error=False,
        doc_grades=[],
        first_pass_score=0.0,
        crag_timeout=False,
        retry_triggered=False,
        retry_query=None,
        retry_docs=[],
        retry_score=0.0,
        fallback_strategy=fallback_strategy,
        fallback_strategy_used="",
        fallback_docs=[],
        llm_only_fallback=False,
        final_routing="",
        result_string="",
        node_latencies={},
    )
