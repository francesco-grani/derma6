"""RAG pipeline StateGraph — builds and compiles the agentic RAG graph."""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, END

from backend.config import settings
from backend.rag.pipeline.nodes.crag import (
    crag_grade,
    local_retry,
    route_after_crag,
    route_after_retry,
)
from backend.rag.pipeline.nodes.decompose import query_decompose
from backend.rag.pipeline.nodes.fallback import external_fallback
from backend.rag.pipeline.nodes.generate import generate
from backend.rag.pipeline.nodes.rerank import rerank
from backend.rag.pipeline.nodes.retrieve import hybrid_retrieve
from backend.rag.pipeline.state import RagState, initial_state

logger = logging.getLogger("derma6.rag.pipeline")


def _build_and_compile():
    graph: StateGraph = StateGraph(RagState)

    graph.add_node("query_decompose", query_decompose)
    graph.add_node("hybrid_retrieve", hybrid_retrieve)
    graph.add_node("rerank", rerank)
    graph.add_node("crag_grade", crag_grade)
    graph.add_node("local_retry", local_retry)
    graph.add_node("external_fallback", external_fallback)
    graph.add_node("generate", generate)

    graph.set_entry_point("query_decompose")
    graph.add_edge("query_decompose", "hybrid_retrieve")
    graph.add_edge("hybrid_retrieve", "rerank")
    graph.add_edge("rerank", "crag_grade")
    graph.add_conditional_edges(
        "crag_grade",
        route_after_crag,
        {"generate": "generate", "local_retry": "local_retry"},
    )
    graph.add_conditional_edges(
        "local_retry",
        route_after_retry,
        {"generate": "generate", "external_fallback": "external_fallback"},
    )
    graph.add_edge("external_fallback", "generate")
    graph.add_edge("generate", END)

    return graph.compile()


class RagPipelineGraph:
    """Stateless per-invocation RAG pipeline. Module-level singleton in kb_search.py."""

    def __init__(self) -> None:
        self._graph = _build_and_compile()
        logger.info("RagPipelineGraph compiled successfully")

    async def ainvoke(self, query: str) -> str:
        """Run the full agentic RAG pipeline for one query. Returns the formatted context string."""
        state = initial_state(query, fallback_strategy=settings.crag_fallback_strategy)
        try:
            final_state = await self._graph.ainvoke(state)
            result = final_state.get("result_string", "")
            if not result:
                logger.warning("RagPipelineGraph produced empty result_string for query=%r", query[:60])
                return "No relevant articles found in the knowledge base for this query."
            return result
        except Exception as exc:
            logger.error("RagPipelineGraph.ainvoke failed for query=%r: %s", query[:60], exc)
            raise
