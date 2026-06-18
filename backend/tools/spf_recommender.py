"""SPF recommender tool: recommends sunscreen based on the SPF 50+ / PA+++ standard."""

import logging
import re

from langchain_core.tools import tool

from backend.rag.retriever import Retriever

logger = logging.getLogger(__name__)


def _detect_low_spf_request(query: str) -> bool:
    """Check if the query requests a lower SPF level (SPF 30, 15, 20, etc.).

    Returns True if low SPF is detected, False otherwise.
    """
    query_lower = query.lower()
    # Pattern to match "spf" followed by optional whitespace and a number
    low_spf_patterns = [
        r"spf\s*30(?!\+|\d)",  # SPF 30 (not SPF 300+)
        r"spf\s*15(?!\+|\d)",  # SPF 15
        r"spf\s*20(?!\+|\d)",  # SPF 20
    ]
    for pattern in low_spf_patterns:
        if re.search(pattern, query_lower):
            return True
    return False


def _format_recommendation(docs) -> str:
    """Format the recommendation from retrieved documents."""
    if not docs:
        return (
            "SPF Recommendation: Always use SPF 50+ with broad-spectrum UVA protection "
            "(PA+++ or higher). Apply as the last step in your morning routine, "
            "15 minutes before sun exposure."
        )

    # Build recommendation from retrieved docs
    content_parts = []
    source_names = []

    for doc in docs:
        if doc.content.strip():
            content_parts.append(doc.content.strip())
        if doc.source_name.strip():
            source_names.append(doc.source_name)

    # Remove duplicates while preserving order
    unique_sources = []
    seen = set()
    for source in source_names:
        if source not in seen:
            unique_sources.append(source)
            seen.add(source)

    content_summary = " ".join(content_parts)

    recommendation = f"SPF Recommendation (SPF 50+ / PA+++ standard):\n\n{content_summary}"

    if unique_sources:
        sources_str = ", ".join(unique_sources)
        recommendation += f"\n\nSources: {sources_str}"

    return recommendation


@tool
def spf_recommender(query: str) -> str:
    """Recommend an SPF product based on user query. Enforces SPF 50+ / PA+++ standard.

    Args:
        query: User query string requesting sunscreen recommendations.

    Returns:
        Recommendation text with SPF 50+ standard enforcement and source citations.
    """
    try:
        # --- Check for low-SPF request ---
        if _detect_low_spf_request(query):
            logger.info(
                "spf_recommender: low SPF request detected in query: %r",
                query[:50],
            )
            return (
                "SPF Standard: The recommended minimum is SPF 50+ with PA+++ or higher "
                "(EU/WHO standard). SPF 30 blocks ~97% of UVB vs SPF 50's ~98%, but the gap "
                "in real-world application is larger. I recommend SPF 50+ only.\n\n"
                "Would you like recommendations for lightweight SPF 50+ options instead?"
            )

        # --- Retrieve SPF-related documents ---
        retriever = Retriever()
        docs = retriever.query("SPF sunscreen UV protection")

        # --- Format and return recommendation ---
        recommendation = _format_recommendation(docs)

        logger.info(
            "spf_recommender: generated recommendation from %d docs for query: %r",
            len(docs),
            query[:50],
        )

        return recommendation

    except Exception as exc:
        logger.error("spf_recommender failed: %s", exc)
        return "Sorry, I could not generate an SPF recommendation. Please try again."
