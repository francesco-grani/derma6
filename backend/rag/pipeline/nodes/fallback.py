"""External fallback node — web search (Tavily/DuckDuckGo) or LLM-only."""

from __future__ import annotations

import logging
import time

from backend.config import settings
from backend.rag.pipeline.state import RankedDoc

logger = logging.getLogger("derma6.rag.fallback")


async def external_fallback(state: dict) -> dict:
    """LangGraph node. Executes the configured external fallback strategy."""
    t0 = time.monotonic()
    strategy: str = state.get("fallback_strategy", settings.crag_fallback_strategy)
    latencies: dict = dict(state.get("node_latencies", {}))

    fallback_docs: list[RankedDoc] = []
    strategy_used = strategy
    llm_only_fallback = False

    if strategy == "web-search":
        try:
            query = state.get("retry_query") or state["original_query"]
            web_results = await _web_search(query)
            if web_results:
                fallback_docs = web_results
                strategy_used = "web-search"
            else:
                logger.warning("Web search returned no results — degrading to llm-only")
                strategy_used = "llm-only"
                llm_only_fallback = True
        except Exception as exc:
            logger.error("Web search fallback failed: %s — degrading to llm-only", exc)
            strategy_used = "llm-only"
            llm_only_fallback = True
    else:
        strategy_used = "llm-only"
        llm_only_fallback = True

    latencies["external_fallback"] = (time.monotonic() - t0) * 1000
    return {
        "fallback_docs": fallback_docs,
        "fallback_strategy_used": strategy_used,
        "llm_only_fallback": llm_only_fallback,
        "node_latencies": latencies,
    }


async def _web_search(query: str) -> list[RankedDoc]:
    """Run Tavily (preferred) or DuckDuckGo search, return top results as RankedDoc list."""
    import asyncio

    if settings.tavily_api_key:
        try:
            from langchain_community.tools.tavily_search import TavilySearchResults

            tool = TavilySearchResults(max_results=3, tavily_api_key=settings.tavily_api_key)
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, tool.invoke, query)
            return _parse_web_results(raw)
        except Exception as exc:
            logger.warning("Tavily search failed: %s — trying DuckDuckGo", exc)

    try:
        from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

        ddg = DuckDuckGoSearchAPIWrapper()
        loop = asyncio.get_event_loop()
        raw_text = await loop.run_in_executor(None, ddg.run, query)
        if raw_text:
            return [
                RankedDoc(
                    doc_id="web_ddg_0",
                    content=raw_text,
                    source_name="DuckDuckGo Search",
                    source_file="web",
                    rrf_score=0.0,
                    rerank_score=0.0,
                    retrieval_path="sparse",
                )
            ]
        return []
    except Exception as exc:
        logger.error("DuckDuckGo search also failed: %s", exc)
        return []


def _parse_web_results(raw) -> list[RankedDoc]:
    """Parse Tavily results (list of dicts) into RankedDoc objects."""
    if not isinstance(raw, list):
        return []
    docs: list[RankedDoc] = []
    for i, item in enumerate(raw[:3]):
        if not isinstance(item, dict):
            continue
        content = item.get("content", "")
        url = item.get("url", "web")
        if content:
            docs.append(
                RankedDoc(
                    doc_id=f"web_{i}",
                    content=content,
                    source_name=url,
                    source_file="web",
                    rrf_score=0.0,
                    rerank_score=0.0,
                    retrieval_path="sparse",
                )
            )
    return docs
