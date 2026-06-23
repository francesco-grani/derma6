"""Hybrid retrieval node — dense (HyDE + ChromaDB) + sparse (BM25) merged via RRF."""

from __future__ import annotations

import asyncio
import logging
import time

from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.rag.pipeline.nodes._rrf import merge_sub_query_results, rrf_merge
from backend.rag.pipeline.state import RankedDoc

logger = logging.getLogger("derma6.rag.retrieve")

_HYDE_PROMPT = (
    "You are a skincare knowledge base. Write a short, factual passage (3-5 sentences) "
    "that would appear in a professional skincare reference and directly answer the question below. "
    "Use specific ingredient names, mechanisms, and concentrations where relevant.\n\n"
    "Human question: {query}"
)

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0.1,
        )
    return _llm


def _get_retriever_collection():
    """Access the ChromaDB collection via the existing Retriever singleton."""
    from backend.tools.kb_search import retriever
    return retriever._collection


async def _dense_retrieve(sub_query: str, collection, embeddings) -> tuple[list[RankedDoc], bool]:
    """Run HyDE → embed → ChromaDB for one sub-query. Returns (docs, hyde_failed)."""
    hyde_failed = False

    try:
        llm = _get_llm()
        prompt = _HYDE_PROMPT.format(query=sub_query)

        async def _call_hyde() -> str:
            resp = await llm.ainvoke(prompt)
            return resp.content if hasattr(resp, "content") else str(resp)

        hypothetical = await asyncio.wait_for(_call_hyde(), timeout=settings.hyde_timeout_seconds)

        if settings.rag_debug_mode:
            logger.debug("HyDE doc for %r: %.300s", sub_query, hypothetical)

        embed_text = hypothetical

    except Exception as exc:
        logger.warning("HyDE generation failed for %r (%s) — embedding raw sub-query", sub_query, exc)
        embed_text = sub_query
        hyde_failed = True

    def _embed_and_query() -> list[RankedDoc]:
        vector = embeddings.embed_query(embed_text)
        results = collection.query(
            query_embeddings=[vector],
            n_results=settings.retrieval_top_k,
            include=["documents", "metadatas", "distances", "ids"],
        )
        docs_raw = results["documents"][0]
        metas_raw = results["metadatas"][0]
        distances_raw = results["distances"][0]
        ids_raw = results.get("ids", [[]])[0]

        out: list[RankedDoc] = []
        for i, (doc, meta, dist) in enumerate(zip(docs_raw, metas_raw, distances_raw)):
            score = 1.0 - (dist * dist) / 2.0
            if score < settings.retrieval_min_score:
                continue
            doc_id = ids_raw[i] if i < len(ids_raw) else f"dense_{i}"
            out.append(
                RankedDoc(
                    doc_id=doc_id,
                    content=doc,
                    source_name=meta.get("source_name", ""),
                    source_file=meta.get("source_file", ""),
                    rrf_score=score,
                    rerank_score=0.0,
                    retrieval_path="dense",
                )
            )
        return out

    loop = asyncio.get_event_loop()
    dense_docs = await loop.run_in_executor(None, _embed_and_query)
    return dense_docs, hyde_failed


async def _sparse_retrieve(sub_query: str, collection) -> tuple[list[RankedDoc], bool]:
    """Run BM25 retrieval for one sub-query. Returns (docs, bm25_failed)."""
    from backend.rag.pipeline.bm25_index import BM25UnavailableError, get_bm25_index

    try:
        index = get_bm25_index(collection)
        docs = index.query(sub_query, k=settings.retrieval_top_k)
        return docs, False
    except BM25UnavailableError as exc:
        logger.warning("BM25 unavailable for %r: %s", sub_query, exc)
        return [], True
    except Exception as exc:
        logger.warning("BM25 query failed for %r: %s", sub_query, exc)
        return [], True


async def hybrid_retrieve(state: dict) -> dict:
    """LangGraph node. Runs dense + sparse retrieval for each sub-query, merges via RRF."""
    from backend.rag.embeddings import OpenRouterEmbeddings

    t0 = time.monotonic()
    sub_queries: list[str] = state.get("sub_queries", [state["original_query"]])
    latencies: dict = dict(state.get("node_latencies", {}))

    collection = _get_retriever_collection()
    embeddings = OpenRouterEmbeddings()

    hyde_fallback_count = 0
    bm25_fallback_count = 0
    per_sub_query_merged: list[list[RankedDoc]] = []

    for sub_query in sub_queries:
        dense_task = asyncio.create_task(_dense_retrieve(sub_query, collection, embeddings))
        sparse_task = asyncio.create_task(_sparse_retrieve(sub_query, collection))

        (dense_docs, hyde_failed), (sparse_docs, bm25_failed) = await asyncio.gather(
            dense_task, sparse_task
        )

        if hyde_failed:
            hyde_fallback_count += 1
        if bm25_failed:
            bm25_fallback_count += 1

        merged = rrf_merge([dense_docs, sparse_docs], k=settings.rrf_k)
        per_sub_query_merged.append(merged)

    # Merge across sub-queries and deduplicate
    candidate_docs = merge_sub_query_results(per_sub_query_merged, k=settings.rrf_k)

    # Compute observability counters
    doc_ids_dense = {d.doc_id for sq_list in per_sub_query_merged for d in sq_list if d.retrieval_path in ("dense", "both")}
    doc_ids_sparse = {d.doc_id for sq_list in per_sub_query_merged for d in sq_list if d.retrieval_path in ("sparse", "both")}
    dense_only_count = len(doc_ids_dense - doc_ids_sparse)
    sparse_only_count = len(doc_ids_sparse - doc_ids_dense)
    rrf_merged_count = len(candidate_docs)

    latencies["hybrid_retrieve"] = (time.monotonic() - t0) * 1000
    return {
        "candidate_docs": candidate_docs,
        "hyde_fallback_count": hyde_fallback_count,
        "bm25_fallback_count": bm25_fallback_count,
        "dense_only_count": dense_only_count,
        "sparse_only_count": sparse_only_count,
        "rrf_merged_count": rrf_merged_count,
        "node_latencies": latencies,
    }
