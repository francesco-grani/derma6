"""Central registry for Knowledge Base ingredients and data sources.

To add a new ingredient:
  1. Add an entry to INGREDIENTS below.
  2. Create the KB document at the path you set in "kb_file".
     Use any existing ingredient doc as a template.
  3. Run:  uv run scripts/enrich_kb.py --ingredient <slug>

That's it. The pipeline fetches all sources and enriches the KB document
automatically. Then re-index with:  uv run scripts/index_kb.py
"""

from pathlib import Path

_BASE = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Ingredient registry
# ---------------------------------------------------------------------------
# Each key is the canonical slug used across all scripts.
# Fields:
#   display_name  — human-readable label
#   kb_file       — path to the KB markdown document (relative to repo root)
#   pc_url        — Paula's Choice ingredient-detail URL (None if no page exists)
#   inci_slugs    — list of incidecoder.com/ingredients/<slug> slugs
#   pubmed_query  — search string for NCBI PubMed
# ---------------------------------------------------------------------------

INGREDIENTS: dict[str, dict] = {
    "retinol": {
        "display_name": "Retinol",
        "kb_file": "knowledge_base/ingredients/retinol.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-retinol.html",
        "inci_slugs": ["retinol"],
        "pubmed_query": "retinol topical skincare dermatology",
    },
    "niacinamide": {
        "display_name": "Niacinamide",
        "kb_file": "knowledge_base/ingredients/niacinamide.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-niacinamide.html",
        "inci_slugs": ["niacinamide"],
        "pubmed_query": "niacinamide topical skin care cosmetic",
    },
    "vitamin_c": {
        "display_name": "Vitamin C (L-Ascorbic Acid)",
        "kb_file": "knowledge_base/ingredients/vitamin_c.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-vitamin-c.html",
        "inci_slugs": ["ascorbic-acid"],
        "pubmed_query": "ascorbic acid topical skin aging cosmetic",
    },
    "aha_guide": {
        "display_name": "AHA (Alpha Hydroxy Acids)",
        "kb_file": "knowledge_base/ingredients/aha_guide.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-aha.html",
        "inci_slugs": ["glycolic-acid", "lactic-acid"],
        "pubmed_query": "glycolic acid topical exfoliation skin",
    },
    "bha_guide": {
        "display_name": "BHA (Salicylic Acid)",
        "kb_file": "knowledge_base/ingredients/bha_guide.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-bha-beta-hydroxy-acid.html",
        "inci_slugs": ["salicylic-acid"],
        "pubmed_query": "salicylic acid topical acne treatment",
    },
    "benzoyl_peroxide": {
        "display_name": "Benzoyl Peroxide",
        "kb_file": "knowledge_base/ingredients/benzoyl_peroxide.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-benzoyl-peroxide.html",
        "inci_slugs": ["benzoyl-peroxide"],
        "pubmed_query": "benzoyl peroxide acne topical treatment",
    },
    "hyaluronic_acid": {
        "display_name": "Hyaluronic Acid",
        "kb_file": "knowledge_base/ingredients/hyaluronic_acid.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-hyaluronic-acid.html",
        "inci_slugs": ["sodium-hyaluronate"],
        "pubmed_query": "hyaluronic acid topical skin hydration",
    },
    "ceramides": {
        "display_name": "Ceramides",
        "kb_file": "knowledge_base/ingredients/ceramides.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-ceramides.html",
        "inci_slugs": ["ceramide-np"],
        "pubmed_query": "ceramide topical skin barrier",
    },
    "peptides": {
        "display_name": "Peptides",
        "kb_file": "knowledge_base/ingredients/peptides.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-peptides.html",
        "inci_slugs": ["palmitoyl-tripeptide-1"],
        "pubmed_query": "peptides topical collagen skin aging",
    },
    "azelaic_acid": {
        "display_name": "Azelaic Acid",
        "kb_file": "knowledge_base/ingredients/azelaic_acid.md",
        "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-azelaic-acid.html",
        "inci_slugs": ["azelaic-acid"],
        "pubmed_query": "azelaic acid topical skin rosacea acne",
    },
    "spf_actives": {
        "display_name": "SPF Actives (Zinc Oxide & Titanium Dioxide)",
        "kb_file": "knowledge_base/ingredients/spf_actives.md",
        "pc_url": None,
        "inci_slugs": ["zinc-oxide", "titanium-dioxide"],
        "pubmed_query": "UV filter sunscreen skin protection photoprotection",
    },
}

# ---------------------------------------------------------------------------
# Reddit wiki pages (KB-wide, not per-ingredient)
# Fetched once and used to enrich guide documents.
# ---------------------------------------------------------------------------
REDDIT_PAGES: list[tuple[str, str]] = [
    ("SkincareAddiction", "index"),
    ("SkincareAddiction", "faq"),
    ("SkincareAddiction", "sca_routine"),
    ("SkincareAddiction", "expanding_your_routine"),
    ("SkincareAddiction", "routine_order"),
    ("SkincareAddiction", "ph_dependence"),
    ("SkincareAddiction", "retinoids"),
    ("SkincareAddiction", "alpha_hydroxy_acids"),
    ("SkincareAddiction", "beta_hydroxy_acids"),
    ("SkincareAddiction", "niacinamide"),
    ("SkincareAddiction", "azelaic_acid"),
    ("SkincareAddiction", "benzoyl_peroxide"),
    ("SkincareAddiction", "vitamin_c_recs"),
    ("SkincareAddiction", "sunscreen"),
    ("SkincareAddiction", "hyperpigmentation"),
    ("SkincareAddiction", "acne"),
    ("SkincareAddiction", "rosacea"),
    ("SkincareAddiction", "shaving"),
    ("SkincareAddiction", "anti_aging"),
    ("SkincareAddiction", "skin_concerns"),
    ("SkincareAddiction", "ingredients"),
]

# ---------------------------------------------------------------------------
# Derived paths (computed, not configured)
# ---------------------------------------------------------------------------

def raw_dir(source: str) -> Path:
    """Return the data/raw/<source> directory."""
    return _BASE / "data" / "raw" / source


def kb_path(slug: str) -> Path:
    """Return the absolute KB document path for an ingredient slug."""
    return _BASE / INGREDIENTS[slug]["kb_file"]


def pc_raw_path(slug: str) -> Path:
    """Return the Paula's Choice raw file path for a slug."""
    return raw_dir("paulas_choice") / f"{slug.replace('_', '-')}.txt"


def inci_raw_paths(slug: str) -> list[Path]:
    """Return all INCI Decoder raw file paths for a slug."""
    return [raw_dir("inci_decoder") / f"{s}.txt" for s in INGREDIENTS[slug]["inci_slugs"]]


def pubmed_raw_path(slug: str) -> Path:
    """Return the PubMed JSON path for a slug."""
    return raw_dir("pubmed") / f"{slug}.json"
