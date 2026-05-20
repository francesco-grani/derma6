"""Routine sequencer tool for ordering skincare products in the correct sequence."""

import logging
from langchain_core.tools import tool

from backend.rag.retriever import Retriever

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


def _classify_ingredient(ingredient: str, retriever: Retriever) -> str | None:
    """Classify a single ingredient using the map, falling back to retriever if needed.

    Args:
        ingredient: The ingredient to classify (should be normalized).
        retriever: The Retriever instance for fallback classification.

    Returns:
        The step category (e.g., "serum"), or None if unclassifiable.
    """
    # Check hardcoded map first
    if ingredient in CLASSIFICATION_MAP:
        return CLASSIFICATION_MAP[ingredient]

    # Try retriever fallback
    try:
        docs = retriever.query("routine sequencing rules application order")

        # Scan returned docs for step keywords
        content_lower = " ".join([doc.content.lower() for doc in docs])

        for step in STEP_ORDER:
            if step in content_lower:
                # Try to match ingredient context in the content
                # Look for the ingredient name near step keywords
                if ingredient in content_lower:
                    return step

        # If ingredient appears in content but we can't match to a step, try a fallback
        # by looking at the first step mention
        for step in STEP_ORDER:
            if step in content_lower:
                return step
    except Exception as e:
        logger.error(f"Retriever fallback failed for '{ingredient}': {e}")

    return None


@tool
def routine_sequencer(ingredients: str) -> str:
    """Order a list of skincare ingredients/products into the correct routine sequence.

    Input: comma-separated ingredient or product names (e.g., "retinol, moisturiser, spf").

    Returns:
        A formatted string with the ordered routine sequence and any unclassifiable items.
    """
    try:
        # Split on comma, strip, filter empty
        items = [item.strip().lower() for item in ingredients.split(",")]
        items = [item for item in items if item]

        # Handle empty input
        if not items:
            return "Error: No ingredients provided."

        # Initialize retriever
        retriever = Retriever()

        # Classify each ingredient
        classified = {}  # step_category -> list of ingredients
        unclassifiable = []

        for ingredient in items:
            category = _classify_ingredient(ingredient, retriever)

            if category:
                if category not in classified:
                    classified[category] = []
                classified[category].append(ingredient)
            else:
                unclassifiable.append(ingredient)

        # Build ordered output based on STEP_ORDER
        lines = ["Routine order:"]
        step_num = 1

        for step in STEP_ORDER:
            if step in classified:
                for ingredient in classified[step]:
                    lines.append(f"{step_num}. {ingredient} ({step})")
                    step_num += 1

        # Add unclassifiable items note
        unclass_str = ", ".join(unclassifiable) if unclassifiable else ""
        lines.append(f"\nUnclassifiable items: [{unclass_str}]")

        result = "\n".join(lines)
        logger.info(f"routine_sequencer succeeded: {len(items)} items, {len(unclassifiable)} unclassifiable")
        return result

    except Exception as e:
        logger.error(f"routine_sequencer failed: {e}")
        return "Sorry, I could not sequence the routine. Please try again."
