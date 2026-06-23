"""Query decomposition node — splits complex queries into focused sub-queries."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from langchain_openai import ChatOpenAI

from backend.config import settings

logger = logging.getLogger("derma6.rag.decompose")

_DECOMPOSE_PROMPT = (
    "You are a query analyst. Decompose the user's skincare question into focused "
    "sub-queries. If the question is already simple and atomic, return it unchanged.\n"
    "Return ONLY a JSON array of strings, e.g. [\"sub-query 1\", \"sub-query 2\"].\n"
    "Do not include any explanation outside the JSON array.\n\n"
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
            temperature=0.0,
        )
    return _llm


async def query_decompose(state: dict) -> dict:
    """LangGraph node. Decomposes the original query into sub-queries."""
    t0 = time.monotonic()
    original = state["original_query"]
    latencies: dict = dict(state.get("node_latencies", {}))

    try:
        llm = _get_llm()
        prompt = _DECOMPOSE_PROMPT.format(query=original)

        async def _call() -> list[str]:
            response = await llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
            parsed = json.loads(text.strip())
            if not isinstance(parsed, list) or not parsed:
                raise ValueError("Empty or non-list response from decomposition LLM")
            return [str(q).strip() for q in parsed if str(q).strip()]

        sub_queries = await asyncio.wait_for(_call(), timeout=settings.decompose_timeout_seconds)

        if settings.rag_debug_mode:
            for i, q in enumerate(sub_queries):
                logger.debug("Decomposed sub-query[%d]: %r", i, q)

        latencies["query_decompose"] = (time.monotonic() - t0) * 1000
        return {
            "sub_queries": sub_queries,
            "decompose_error": False,
            "node_latencies": latencies,
        }

    except Exception as exc:
        logger.error("query_decompose failed (%s) — falling back to original query", exc)
        latencies["query_decompose"] = (time.monotonic() - t0) * 1000
        return {
            "sub_queries": [original],
            "decompose_error": True,
            "node_latencies": latencies,
        }
