"""Conflict checker tool for detecting ingredient incompatibilities."""

import json
import logging
from pathlib import Path
from typing import Dict

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Load conflict_table.json at module import time
_CONFLICT_TABLE_PATH = Path(__file__).parent.parent.parent / "knowledge_base" / "conflict_table.json"


def _load_conflict_table() -> Dict[frozenset, Dict[str, str]]:
    """Load and normalize the conflict table from JSON file.

    Returns:
        A dictionary keyed by frozenset of normalized ingredient pairs,
        with values containing 'verdict' and 'reason'.
    """
    with open(_CONFLICT_TABLE_PATH, "r") as f:
        conflicts = json.load(f)

    table = {}
    for entry in conflicts:
        a = entry["ingredient_a"].lower().strip()
        b = entry["ingredient_b"].lower().strip()
        key = frozenset({a, b})
        table[key] = {
            "verdict": entry["verdict"],
            "reason": entry["reason"]
        }
    return table


# Module-level conflict table
_CONFLICT_TABLE = _load_conflict_table()


def _normalize_ingredient(ingredient: str) -> str:
    """Normalize an ingredient name: lowercase and strip whitespace."""
    return ingredient.lower().strip()


@tool
def conflict_checker(ingredients: str) -> str:
    """Check if two skincare ingredients conflict.

    Input: two comma-separated ingredient names (e.g., "retinol, vitamin c")

    Returns:
        A formatted string with verdict, reason, or error message.
    """
    # Parse input: split on comma
    parts = ingredients.split(",")

    # Validate: must have exactly 2 parts
    if len(parts) != 2:
        return "Error: Both ingredient names must be non-empty."

    ingredient_a = _normalize_ingredient(parts[0])
    ingredient_b = _normalize_ingredient(parts[1])

    # Validate: both must be non-empty after normalization
    if not ingredient_a or not ingredient_b:
        return "Error: Both ingredient names must be non-empty."

    # Look up in conflict table using frozenset for order-independence
    lookup_key = frozenset({ingredient_a, ingredient_b})

    if lookup_key in _CONFLICT_TABLE:
        entry = _CONFLICT_TABLE[lookup_key]
        verdict = entry["verdict"]
        reason = entry["reason"]

        # Log the result
        logger.info(f"Conflict check: {ingredient_a} + {ingredient_b} = {verdict}")

        return f"Verdict: {verdict}\nReason: {reason}\nUnknown ingredients: []"
    else:
        # Unknown pair
        logger.warning(f"Unknown ingredients in conflict check: {ingredient_a} + {ingredient_b}")
        return f"Verdict: unknown_ingredient\nReason: No conflict data for {ingredient_a} + {ingredient_b}. Consult a dermatologist.\nUnknown ingredients: [{ingredient_a}, {ingredient_b}]"
