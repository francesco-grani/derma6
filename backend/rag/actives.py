"""Canonical skincare actives vocabulary and text matching.

Used at index time to tag each knowledge-base chunk with the actives it
mentions, and at query time to extract the actives from a user question, so
that retrieval can *softly boost* chunks whose actives overlap the query's.

Matching is a curated alias lookup over a small, closed vocabulary (~14
canonical actives) rather than open-ended NER. Aliases are drawn from the KB
ingredient profiles (knowledge_base/ingredients/*.md) and the conflict table
(knowledge_base/conflict_table.json). Ambiguous short acronyms — most notably
bare "HA" for hyaluronic acid — are deliberately omitted: the risk of matching
them inside unrelated words outweighs the recall they add, and the full names
("hyaluronic acid", "sodium hyaluronate") are almost always present anyway.
"""

from __future__ import annotations

import re

# Canonical active name -> list of surface forms that should map to it. The
# canonical name itself is included as an alias so callers never have to special
# case it. Every alias is matched case-insensitively with word boundaries.
_ALIASES: dict[str, list[str]] = {
    "retinol": [
        "retinol", "retinoid", "retinoids", "retinaldehyde", "retinal",
        "retinyl palmitate", "retinyl ester", "retinyl esters",
        "tretinoin", "adapalene", "tazarotene", "vitamin a",
    ],
    "vitamin c": [
        "vitamin c", "ascorbic acid", "l-ascorbic acid", "ascorbate",
        "sodium ascorbyl phosphate", "magnesium ascorbyl phosphate",
        "ascorbyl glucoside", "tetrahexyldecyl ascorbate",
    ],
    "niacinamide": ["niacinamide", "nicotinamide", "vitamin b3"],
    "aha": [
        "aha", "ahas", "alpha-hydroxy acid", "alpha hydroxy acid",
        "alpha-hydroxy acids", "alpha hydroxy acids",
        "glycolic acid", "lactic acid", "mandelic acid",
        "malic acid", "tartaric acid",
    ],
    "bha": [
        "bha", "beta-hydroxy acid", "beta hydroxy acid",
        "salicylic acid", "willow bark",
    ],
    "benzoyl peroxide": ["benzoyl peroxide", "bpo"],
    "azelaic acid": ["azelaic acid"],
    "hyaluronic acid": [
        "hyaluronic acid", "sodium hyaluronate", "hyaluronate",
    ],
    "ceramides": ["ceramides", "ceramide"],
    "peptides": ["peptides", "peptide", "matrixyl", "argireline"],
    "spf": [
        "spf", "sunscreen", "zinc oxide", "titanium dioxide", "avobenzone",
    ],
}

# The set of canonical actives this vocabulary knows about.
CANONICAL_ACTIVES: frozenset[str] = frozenset(_ALIASES)

# One compiled pattern per canonical active: \b(alias1|alias2|...)\b, longest
# aliases first so a multi-word form is preferred over a substring of it.
_PATTERNS: dict[str, re.Pattern[str]] = {
    canonical: re.compile(
        r"\b(?:"
        + "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
        + r")\b",
        re.IGNORECASE,
    )
    for canonical, aliases in _ALIASES.items()
}

# Delimiter used to serialise a set of actives into a single ChromaDB metadata
# value (Chroma metadata values must be scalars, not lists).
_SEP = ","


def extract_actives(text: str) -> set[str]:
    """Return the set of canonical actives mentioned in *text*.

    Matching is case-insensitive and word-boundary anchored. An empty or
    None-ish input yields an empty set.
    """
    if not text:
        return set()
    return {name for name, pattern in _PATTERNS.items() if pattern.search(text)}


def serialize_actives(actives: set[str]) -> str:
    """Serialise a set of actives into a deterministic scalar metadata value.

    Produces a comma-joined, sorted string (e.g. "niacinamide,retinol"), or the
    empty string when there are no actives. Sorting keeps ChromaDB upserts
    idempotent for unchanged chunks.
    """
    return _SEP.join(sorted(actives))


def parse_actives(value: str | None) -> set[str]:
    """Inverse of :func:`serialize_actives`; tolerates None and empty strings."""
    if not value:
        return set()
    return {part for part in value.split(_SEP) if part}
