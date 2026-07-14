"""kb_search tool — general-purpose retrieval from the skincare knowledge base."""

import logging

from langchain_core.tools import tool

from backend.rag.pipeline.graph import RagPipelineGraph
from backend.rag.retriever import retriever  # noqa: F401 (re-exported for callers that patch this name)
from backend.security_patterns import sanitise_retrieved

logger = logging.getLogger(__name__)

# Agentic RAG pipeline singleton — triggers BM25 index build and CrossEncoder load on import.
_rag_pipeline = RagPipelineGraph()


@tool
async def kb_search(query: str) -> str:
    """Search the skincare knowledge base for information on ingredients, actives,
    routines, skin concepts, or skincare science.

    Use this for ANY question about skincare that requires factual grounding —
    ingredient properties, how-to advice, skin cycling, layering rules, etc.
    Always prefer this over answering from general knowledge.

    Input: the user's question or a concise search phrase.
    """
    try:
        result = await _rag_pipeline.ainvoke(query)
        logger.info("kb_search: agentic RAG pipeline returned result for query=%r", query[:60])
        return sanitise_retrieved(result)
    except Exception as exc:
        logger.error("kb_search failed: %s", exc)
        return "Sorry, I could not search the knowledge base right now."
