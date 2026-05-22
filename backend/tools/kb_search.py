"""kb_search tool — general-purpose retrieval from the skincare knowledge base."""

import logging

from langchain_core.tools import tool

from backend.rag.retriever import Retriever

logger = logging.getLogger(__name__)


@tool
def kb_search(query: str) -> str:
    """Search the skincare knowledge base for information on ingredients, actives,
    routines, skin concepts, or skincare science.

    Use this for ANY question about skincare that requires factual grounding —
    ingredient properties, how-to advice, skin cycling, layering rules, etc.
    Always prefer this over answering from general knowledge.

    Input: the user's question or a concise search phrase.
    """
    try:
        retriever = Retriever()
        docs = retriever.query(query)

        if not docs:
            logger.info("kb_search: no docs above threshold for query=%r", query[:60])
            return "No relevant articles found in the knowledge base for this query."

        parts = []
        sources = []
        for doc in docs:
            if doc.content.strip():
                parts.append(doc.content.strip())
            if doc.source_name.strip() and doc.source_name not in sources:
                sources.append(doc.source_name)

        result = "\n\n---\n\n".join(parts)
        if sources:
            result += f"\n\nSources: {', '.join(sources)}"

        logger.info("kb_search: returned %d docs for query=%r", len(docs), query[:60])
        return result

    except Exception as exc:
        logger.error("kb_search failed: %s", exc)
        return "Sorry, I could not search the knowledge base right now."
