"""Skin type advisor tool: classifies a user's skin type and persists it to their profile."""

import logging

from langchain_core.tools import tool

from backend.db.profile_store import ProfileStore
from backend.rag.retriever import Retriever

logger = logging.getLogger(__name__)

# All recognised skin type labels
SKIN_TYPES = ["oily", "dry", "combination", "sensitive", "dehydrated", "acneic"]

# Keyword -> skin type heuristics (checked against description first)
_DESCRIPTION_KEYWORDS: dict[str, list[str]] = {
    "oily": ["shiny", "greasy", "oily", "shine", "excess oil", "sebum", "slick"],
    "dry": ["tight", "flaky", "dry", "rough", "peeling", "dull", "scaling"],
    "combination": [
        "oily t-zone",
        "t-zone",
        "oily forehead",
        "oily nose",
        "dry cheeks",
        "combination",
    ],
    "sensitive": [
        "reactive",
        "red",
        "redness",
        "burns",
        "stings",
        "irritated",
        "sensitive",
        "flush",
        "blush",
        "tingles",
    ],
    "dehydrated": [
        "tight but not flaky",
        "dehydrated",
        "dehydration",
        "lacks water",
        "thirsty",
        "dull and tight",
    ],
    "acneic": [
        "breakout",
        "breakouts",
        "acne",
        "pimple",
        "pimples",
        "blemish",
        "blemishes",
        "clogged",
        "cystic",
        "congested",
    ],
}

# One-sentence fallback characteristics per skin type
_CHARACTERISTICS: dict[str, str] = {
    "oily": "Produces excess sebum throughout the day, leaving a shiny or greasy appearance.",
    "dry": "Lacks sufficient oil, often feeling tight or appearing flaky and rough.",
    "combination": "Oily in the T-zone (forehead, nose, chin) while the cheeks remain normal or dry.",
    "sensitive": "Reacts easily to products or environmental triggers with redness, burning, or stinging.",
    "dehydrated": "Lacks water (not oil), feeling tight and looking dull without visible flaking.",
    "acneic": "Prone to breakouts, blackheads, or cystic blemishes due to clogged pores.",
}


def _classify_from_description(description: str) -> str | None:
    """Return the best-matching skin type from description keywords, or None."""
    desc_lower = description.lower()
    scores: dict[str, int] = {st: 0 for st in SKIN_TYPES}
    for skin_type, keywords in _DESCRIPTION_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                scores[skin_type] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else None


def _classify_from_docs(docs) -> str | None:
    """Return the most-mentioned skin type found across retrieved document contents."""
    combined = " ".join(doc.content.lower() for doc in docs)
    counts: dict[str, int] = {st: combined.count(st) for st in SKIN_TYPES}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] > 0 else None


def _extract_characteristic(skin_type: str, docs) -> str:
    """Pull the first sentence mentioning the skin type from retrieved docs, or use fallback."""
    for doc in docs:
        for sentence in doc.content.split("."):
            if skin_type in sentence.lower():
                cleaned = sentence.strip()
                if cleaned:
                    return cleaned + "."
    return _CHARACTERISTICS.get(skin_type, "")


@tool
def skin_type_advisor(input_str: str) -> str:
    """Classify a user's skin type from their description and persist it to their profile.

    Input format: 'description: <symptom description> | username: <username>'
    """
    try:
        # --- Parse input ---
        description = ""
        username = ""

        for part in input_str.split("|"):
            part = part.strip()
            if part.startswith("description:"):
                description = part[len("description:"):].strip()
            elif part.startswith("username:"):
                username = part[len("username:"):].strip()

        if not description:
            return "Error: 'description' is required and must not be empty."
        if not username:
            return "Error: 'username' is required and must not be empty."

        # --- Classify from keywords first (no retrieval needed) ---
        skin_type = _classify_from_description(description)

        # --- Retrieve docs for richer classification and characteristics ---
        retriever = Retriever()
        docs = retriever.query(f"skin type classification {description}")

        if skin_type is None and docs:
            skin_type = _classify_from_docs(docs)
        if skin_type is None:
            skin_type = "oily"  # last-resort default

        # --- Extract characteristics ---
        characteristic = _extract_characteristic(skin_type, docs) if docs else _CHARACTERISTICS.get(skin_type, "")

        # --- Persist ---
        ProfileStore().update_skin_type(username, skin_type)

        logger.info(
            "skin_type_advisor: classified '%s' as '%s' for user '%s'.",
            description[:40],
            skin_type,
            username,
        )

        return (
            f"Skin type: {skin_type}\n\n"
            f"Characteristics: {characteristic}\n\n"
            "Your profile has been updated."
        )

    except Exception as exc:
        logger.error("skin_type_advisor failed: %s", exc)
        return (
            "Sorry, I could not classify your skin type right now. "
            "Please try again or describe your skin in more detail."
        )
