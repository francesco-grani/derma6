"""Routine sequencer tool for ordering skincare products in the correct sequence."""

import logging

from langchain_core.tools import tool

from backend.tools.kb_search import retriever

logger = logging.getLogger(__name__)

# Canonical step order for skincare routines
STEP_ORDER = ["cleanser", "toner", "serum", "moisturiser", "spf"]

# Hardcoded classification map: ingredient/keyword -> step category
CLASSIFICATION_MAP = {
    # cleansers
    "cleanser": "cleanser",
    "face wash": "cleanser",
    "micellar": "cleanser",
    "foam": "cleanser",
    # toners
    "toner": "toner",
    "essence": "toner",
    # serums (actives)
    "retinol": "serum",
    "niacinamide": "serum",
    "vitamin c": "serum",
    "aha": "serum",
    "bha": "serum",
    "glycolic acid": "serum",
    "salicylic acid": "serum",
    "hyaluronic acid": "serum",
    "peptides": "serum",
    "azelaic acid": "serum",
    "benzoyl peroxide": "serum",
    "serum": "serum",
    # moisturisers
    "moisturiser": "moisturiser",
    "moisturizer": "moisturiser",
    "cream": "moisturiser",
    "ceramides": "moisturiser",
    "lotion": "moisturiser",
    # spf
    "spf": "spf",
    "sunscreen": "spf",
    "sunblock": "spf",
}


def _classify_ingredient(ingredient: str) -> str | None:
    """Classify a single ingredient using the map, falling back to the shared retriever."""
    if ingredient in CLASSIFICATION_MAP:
        return CLASSIFICATION_MAP[ingredient]

    try:
        docs = retriever.query("routine sequencing rules application order")
        content_lower = " ".join([doc.content.lower() for doc in docs])
        for step in STEP_ORDER:
            if step in content_lower and ingredient in content_lower:
                return step
        for step in STEP_ORDER:
            if step in content_lower:
                return step
    except Exception as exc:
        logger.error("Retriever fallback failed for '%s': %s", ingredient, exc)

    return None


@tool
def routine_sequencer(ingredients: str) -> str:
    """Order a list of skincare ingredients/products into the correct routine sequence.

    Input: comma-separated ingredient or product names (e.g., "retinol, moisturiser, spf").
    """
    try:
        items = [item.strip().lower() for item in ingredients.split(",")]
        items = [item for item in items if item]

        if not items:
            return "Error: No ingredients provided."

        classified: dict[str, list[str]] = {}
        unclassifiable: list[str] = []

        for ingredient in items:
            category = _classify_ingredient(ingredient)
            if category is not None:
                classified.setdefault(category, []).append(ingredient)
            else:
                unclassifiable.append(ingredient)

        lines = ["Routine order:"]
        step_num = 1

        for step in STEP_ORDER:
            if step in classified:
                for ingredient in classified[step]:
                    lines.append(f"{step_num}. {step}: {ingredient}")
                    step_num += 1

        lines.append(f"\nUnclassifiable items: [{', '.join(unclassifiable)}]")

        logger.info("routine_sequencer succeeded: %d items, %d unclassifiable", len(items), len(unclassifiable))
        return "\n".join(lines)

    except Exception as exc:
        logger.error("routine_sequencer failed: %s", exc)
        return "Sorry, I could not sequence the routine. Please try again."
