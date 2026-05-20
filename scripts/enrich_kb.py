#!/usr/bin/env python3
"""End-to-end KB enrichment pipeline.

Fetches fresh data from all sources, enriches KB documents, and re-indexes
ChromaDB — in one command.

─────────────────────────────────────────────
USAGE
─────────────────────────────────────────────
Refresh all ingredients (full pipeline):
    uv run scripts/enrich_kb.py

Refresh a single existing ingredient:
    uv run scripts/enrich_kb.py --ingredient retinol

Add a brand-new ingredient (step-by-step guide):
    uv run scripts/enrich_kb.py --new-ingredient adapalene

Skip the re-index step (just fetch + normalize):
    uv run scripts/enrich_kb.py --skip-index

─────────────────────────────────────────────
ADDING A NEW INGREDIENT
─────────────────────────────────────────────
1.  Edit scripts/kb_config.py → add an entry to INGREDIENTS:

        "adapalene": {
            "display_name": "Adapalene",
            "kb_file": "knowledge_base/ingredients/adapalene.md",
            "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-adapalene.html",
            "inci_slugs": ["adapalene"],
            "pubmed_query": "adapalene topical acne retinoid",
        },

2.  Create the KB document (use any existing doc as a template):
        cp knowledge_base/ingredients/retinol.md knowledge_base/ingredients/adapalene.md
        # Edit the copy to fill in what you already know about the ingredient

3.  Run this script:
        uv run scripts/enrich_kb.py --ingredient adapalene

    The pipeline will: fetch PC page → fetch INCI Decoder → fetch PubMed
    → enrich the KB document → re-index ChromaDB.

NOTE: the KB is capped at 20 entries per the project spec. Check the count
before adding:  find knowledge_base -name '*.md' | wc -l
─────────────────────────────────────────────
"""

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

from kb_config import INGREDIENTS  # noqa: E402


def run(cmd: list[str], label: str) -> bool:
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    result = subprocess.run(cmd, cwd=_SCRIPTS.parent)
    if result.returncode != 0:
        print(f"  [FAILED] {label} (exit {result.returncode})")
        return False
    return True


def check_kb_cap() -> None:
    kb_dir = _SCRIPTS.parent / "knowledge_base"
    count = len(list(kb_dir.rglob("*.md")))
    if count >= 20:
        print(f"\n⚠  KB cap reached: {count}/20 documents.")
        print("   Remove or merge an existing document before adding a new one.")
        print("   (Spec constraint: knowledge_base/ must stay ≤ 20 entries.)\n")


def guide_new_ingredient(slug: str) -> None:
    kb_count = len(list((_SCRIPTS.parent / "knowledge_base").rglob("*.md")))
    print(f"""
Adding new ingredient: {slug!r}
KB currently has {kb_count}/20 documents.

Steps to complete before running the pipeline:

  1. Edit scripts/kb_config.py → add to INGREDIENTS:

         "{slug}": {{
             "display_name": "<Display Name>",
             "kb_file": "knowledge_base/ingredients/{slug}.md",
             "pc_url": "<Paula's Choice URL or None>",
             "inci_slugs": ["<inci-decoder-slug>"],
             "pubmed_query": "<search terms for PubMed>",
         }},

  2. Create the KB document:
         cp knowledge_base/ingredients/retinol.md knowledge_base/ingredients/{slug}.md
         # Then edit it to match the new ingredient

  3. Re-run:
         uv run scripts/enrich_kb.py --ingredient {slug}
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch sources, enrich KB documents, and re-index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ingredient",
        metavar="SLUG",
        help="Process a single ingredient only (e.g. retinol)",
    )
    parser.add_argument(
        "--new-ingredient",
        metavar="SLUG",
        help="Print the step-by-step guide for adding a new ingredient",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip the ChromaDB re-index step",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch raw data only — skip normalize and index",
    )
    args = parser.parse_args()

    if args.new_ingredient:
        if args.new_ingredient in INGREDIENTS:
            print(f"{args.new_ingredient!r} already exists in kb_config.py — use --ingredient to re-enrich it.")
        else:
            guide_new_ingredient(args.new_ingredient)
            check_kb_cap()
        return

    slug_flag = ["--ingredient", args.ingredient] if args.ingredient else []

    # ── 1. Fetch: Paula's Choice (Playwright) ─────────────────────────────
    ok = run(
        ["uv", "run", "scripts/scrape_paulas_choice.py"] + slug_flag,
        "Paula's Choice — Playwright scraper",
    )
    if not ok:
        print("  Continuing despite PC scrape failure (some ingredients may lack PC data).")

    # ── 2. Fetch: INCI Decoder ─────────────────────────────────────────────
    ok = run(
        ["uv", "run", "scripts/scrape_inci_decoder.py"] + slug_flag,
        "INCI Decoder — httpx scraper",
    )
    if not ok:
        print("  Continuing despite INCI Decoder failure.")

    # ── 3. Fetch: PubMed ──────────────────────────────────────────────────
    ok = run(
        ["uv", "run", "scripts/fetch_pubmed.py"] + slug_flag,
        "PubMed — NCBI E-utilities API",
    )
    if not ok:
        print("  Continuing despite PubMed failure.")

    # ── 4. Fetch: Reddit wiki (KB-wide, only when refreshing everything) ──
    if not args.ingredient:
        run(
            ["uv", "run", "scripts/fetch_reddit_wiki.py"],
            "Reddit wiki — public JSON API",
        )

    if args.fetch_only:
        print("\nDone — raw data fetched. Skipping normalize and index (--fetch-only).")
        return

    # ── 5. Normalize: LLM enrichment ──────────────────────────────────────
    ok = run(
        ["uv", "run", "scripts/normalize_kb.py"] + slug_flag,
        "LLM normalization — enrich KB documents",
    )
    if not ok:
        print("  Normalize failed. Check OPENROUTER_API_KEY in .env.")
        return

    if args.skip_index:
        print("\nDone — KB enriched. Skipping re-index (--skip-index).")
        return

    # ── 6. Re-index ChromaDB ───────────────────────────────────────────────
    run(
        ["uv", "run", "python", "scripts/index_kb.py"],
        "ChromaDB re-index",
    )

    print("\n✓  Pipeline complete.")


if __name__ == "__main__":
    main()
