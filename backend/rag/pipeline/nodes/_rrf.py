"""Reciprocal Rank Fusion (RRF) merge utility."""

from __future__ import annotations

from backend.rag.pipeline.state import RankedDoc


def rrf_merge(lists: list[list[RankedDoc]], k: int = 60) -> list[RankedDoc]:
    """Merge multiple ranked lists into one using RRF.

    RRF_score(d) = Σ_i  1 / (k + rank(L_i, d) + 1)   (0-based rank)

    Documents absent from a list contribute 0 for that list.
    When the same doc_id appears in multiple lists, RRF scores are summed
    and retrieval_path is set to "both".
    """
    scores: dict[str, float] = {}
    best_doc: dict[str, RankedDoc] = {}
    paths: dict[str, set[str]] = {}

    for ranked_list in lists:
        for rank, doc in enumerate(ranked_list):
            contribution = 1.0 / (k + rank + 1)
            if doc.doc_id not in scores:
                scores[doc.doc_id] = 0.0
                best_doc[doc.doc_id] = doc
                paths[doc.doc_id] = set()
            scores[doc.doc_id] += contribution
            paths[doc.doc_id].add(doc.retrieval_path)

    result: list[RankedDoc] = []
    for doc_id, score in scores.items():
        doc = best_doc[doc_id]
        path_set = paths[doc_id]
        retrieval_path = "both" if len(path_set) > 1 else next(iter(path_set))
        merged = RankedDoc(
            doc_id=doc.doc_id,
            content=doc.content,
            source_name=doc.source_name,
            source_file=doc.source_file,
            rrf_score=score,
            rerank_score=doc.rerank_score,
            retrieval_path=retrieval_path,
        )
        result.append(merged)

    result.sort(key=lambda d: d.rrf_score, reverse=True)
    return result


def merge_sub_query_results(per_sub_query_lists: list[list[RankedDoc]], k: int = 60) -> list[RankedDoc]:
    """Merge RRF-merged lists from multiple sub-queries.

    Docs appearing in multiple sub-query results have their RRF scores summed,
    rewarding documents that are relevant across sub-topics.
    """
    scores: dict[str, float] = {}
    best_doc: dict[str, RankedDoc] = {}
    paths: dict[str, set[str]] = {}

    for sub_list in per_sub_query_lists:
        for doc in sub_list:
            if doc.doc_id not in scores:
                scores[doc.doc_id] = 0.0
                best_doc[doc.doc_id] = doc
                paths[doc.doc_id] = set()
            scores[doc.doc_id] += doc.rrf_score
            paths[doc.doc_id].add(doc.retrieval_path)

    result: list[RankedDoc] = []
    for doc_id, score in scores.items():
        doc = best_doc[doc_id]
        path_set = paths[doc_id]
        retrieval_path = "both" if len(path_set) > 1 else next(iter(path_set))
        merged = RankedDoc(
            doc_id=doc.doc_id,
            content=doc.content,
            source_name=doc.source_name,
            source_file=doc.source_file,
            rrf_score=score,
            rerank_score=doc.rerank_score,
            retrieval_path=retrieval_path,
        )
        result.append(merged)

    result.sort(key=lambda d: d.rrf_score, reverse=True)
    return result
