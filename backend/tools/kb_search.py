"""kb_search tool — general-purpose retrieval from the skincare knowledge base."""

import json
import logging

from langchain_core.tools import tool

from backend.rag.retriever import Retriever

logger = logging.getLogger(__name__)

# Shared singleton — ChromaDB PersistentClient must not be opened more than once
# per process. All tools that need retrieval should import this object.
retriever = Retriever()


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

        # Structured metadata for RAG visualisation (parsed by the agent, not for the LLM)
        rag_meta = [
            {
                "source": d.source_name,
                "score": round(d.score, 3),
                "snippet": d.content.strip()[:150],
            }
            for d in docs
        ]
        result += f"\n\n__RAG_CONTEXT_JSON__: {json.dumps(rag_meta)}"

        logger.info("kb_search: returned %d docs for query=%r", len(docs), query[:60])
        return result

    except Exception as exc:
        logger.error("kb_search failed: %s", exc)
        return "Sorry, I could not search the knowledge base right now."
