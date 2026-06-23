"""CRAG grading, local retry, and routing functions."""

from __future__ import annotations

import asyncio
import logging
import time

from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.rag.pipeline.state import RankedDoc

logger = logging.getLogger("derma6.rag.crag")

_GRADE_PROMPT = (
    'You are a relevance grader. Answer only "yes" or "no", no other text.\n\n'
    "Human question: {query}\n"
    "Document: {snippet}\n\n"
    "Is this document relevant to answering the question? Answer yes or no."
)

_REWRITE_PROMPT = (
    "You are a search query optimiser. Rewrite the skincare question below to improve "
    "retrieval from a knowledge base. Use more precise ingredient names, condition terminology, "
    "or alternative phrasings. Return only the rewritten question, no explanation.\n\n"
    "Original question: {query}"
)

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0.0,
        )
    return _llm


async def _grade_doc(query: str, doc: RankedDoc) -> bool:
    """Grade a single document for relevance. Returns True if relevant."""
    llm = _get_llm()
    prompt = _GRADE_PROMPT.format(query=query, snippet=doc.content[:500])
    try:
        resp = await llm.ainvoke(prompt)
        text = (resp.content if hasattr(resp, "content") else str(resp)).strip().lower()
        return text.startswith("yes")
    except Exception as exc:
        logger.warning("Grade call failed for doc %r: %s — treating as not relevant", doc.doc_id, exc)
        return False


async def crag_grade(state: dict) -> dict:
    """LangGraph node. Grades reranked docs for relevance; computes first_pass_score."""
    t0 = time.monotonic()
    reranked: list[RankedDoc] = state.get("reranked_docs", [])
    original_query: str = state["original_query"]
    latencies: dict = dict(state.get("node_latencies", {}))

    if not reranked:
        latencies["crag_grade"] = (time.monotonic() - t0) * 1000
        return {
            "doc_grades": [],
            "first_pass_score": -1.0,
            "crag_timeout": False,
            "node_latencies": latencies,
        }

    try:
        grade_tasks = [_grade_doc(original_query, doc) for doc in reranked]
        grades: list[bool] = await asyncio.wait_for(
            asyncio.gather(*grade_tasks),
            timeout=settings.crag_grade_timeout_seconds,
        )
        score = sum(grades) / len(grades)

        if settings.rag_debug_mode:
            for doc, grade in zip(reranked, grades):
                logger.debug(
                    "CRAG grade: doc_id=%r source=%r relevant=%s",
                    doc.doc_id, doc.source_name, grade,
                )

        latencies["crag_grade"] = (time.monotonic() - t0) * 1000
        return {
            "doc_grades": list(grades),
            "first_pass_score": score,
            "crag_timeout": False,
            "node_latencies": latencies,
        }

    except asyncio.TimeoutError:
        logger.warning("CRAG grading timed out after %ds", settings.crag_grade_timeout_seconds)
        latencies["crag_grade"] = (time.monotonic() - t0) * 1000
        return {
            "doc_grades": [],
            "first_pass_score": 0.0,
            "crag_timeout": True,
            "node_latencies": latencies,
        }


def route_after_crag(state: dict) -> str:
    """Conditional edge: 'generate' if above threshold, else 'local_retry'."""
    score = state.get("first_pass_score", 0.0)
    if score < 0 or state.get("crag_timeout", False):
        return "local_retry"
    if score >= settings.crag_relevance_threshold:
        return "generate"
    return "local_retry"


async def local_retry(state: dict) -> dict:
    """LangGraph node. Reformulates query, re-retrieves, re-reranks, re-grades."""
    from backend.rag.pipeline.nodes.retrieve import hybrid_retrieve
    from backend.rag.pipeline.nodes.rerank import rerank

    t0 = time.monotonic()
    original_query: str = state["original_query"]
    latencies: dict = dict(state.get("node_latencies", {}))

    # 1. Reformulate query
    try:
        llm = _get_llm()
        prompt = _REWRITE_PROMPT.format(query=original_query)
        resp = await llm.ainvoke(prompt)
        retry_query = (resp.content if hasattr(resp, "content") else str(resp)).strip()
        if not retry_query:
            retry_query = original_query
    except Exception as exc:
        logger.warning("Query reformulation failed: %s — using original query", exc)
        retry_query = original_query

    logger.info("local_retry: reformulated query=%r", retry_query)

    # 2. Re-retrieve with retry query (inject as single sub-query)
    retry_state = dict(state)
    retry_state["sub_queries"] = [retry_query]
    retry_state["node_latencies"] = {}

    retrieve_result = await hybrid_retrieve(retry_state)
    retry_state.update(retrieve_result)
    retry_state["candidate_docs"] = retrieve_result.get("candidate_docs", [])

    # 3. Re-rerank
    rerank_result = rerank(retry_state)
    retry_state.update(rerank_result)
    retry_docs: list[RankedDoc] = rerank_result.get("reranked_docs", [])

    # 4. Re-grade
    if not retry_docs:
        retry_score = 0.0
        retry_grades: list[bool] = []
    else:
        try:
            grade_tasks = [_grade_doc(original_query, doc) for doc in retry_docs]
            retry_grades = await asyncio.wait_for(
                asyncio.gather(*grade_tasks),
                timeout=settings.crag_grade_timeout_seconds,
            )
            retry_score = sum(retry_grades) / len(retry_grades)
        except Exception:
            retry_score = 0.0
            retry_grades = []

    latencies["local_retry"] = (time.monotonic() - t0) * 1000
    return {
        "retry_triggered": True,
        "retry_query": retry_query,
        "retry_docs": retry_docs,
        "retry_score": retry_score,
        "node_latencies": latencies,
    }


def route_after_retry(state: dict) -> str:
    """Conditional edge: 'generate' if retry above threshold, else 'external_fallback'."""
    retry_score = state.get("retry_score", 0.0)
    if retry_score >= settings.crag_relevance_threshold:
        return "generate"
    return "external_fallback"
