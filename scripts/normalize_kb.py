#!/usr/bin/env python3
"""Enrich existing KB ingredient documents with real sourced content.

For each KB document, reads the corresponding raw files from data/raw/ and calls
the LLM to produce an enriched version. Writes results back to knowledge_base/.

Usage:
    uv run scripts/normalize_kb.py                     # all ingredients
    uv run scripts/normalize_kb.py --ingredient retinol  # one at a time
    uv run scripts/normalize_kb.py --dry-run           # print diff only
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent))
from kb_config import INGREDIENTS as _ALL, inci_raw_paths, kb_path, pc_raw_path, pubmed_raw_path  # noqa: E402

load_dotenv()

client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4o-mini")

# Build the ingredient map dynamically from central config
INGREDIENT_MAP: dict[str, dict] = {
    slug: {
        "kb":     kb_path(slug),
        "pc":     pc_raw_path(slug) if cfg.get("pc_url") else None,
        "inci":   inci_raw_paths(slug),
        "pubmed": pubmed_raw_path(slug),
    }
    for slug, cfg in _ALL.items()
}

SYSTEM_PROMPT = """\
You are a skincare science editor enriching a RAG knowledge base document.
Your task: update the existing document with real sourced content from the provided
raw source files. Follow these rules exactly:

1. KEEP the existing document structure (all headings in place).
2. ADD new factual content from the sources where it genuinely adds value — do not
   duplicate what is already there.
3. REPLACE approximate or vague citations with the verified journal references from
   the Paula's Choice or PubMed sources. Format citations as numbered list under
   ## Sources. Include author, year, journal, DOI or URL where available.
4. ADD a "Paula's Choice Rating" line in the Overview section: e.g. "**Paula's
   Choice rating:** Best — benefits: Anti-Aging, Anti-Acne".
5. ADD an INCI Decoder classification line in the Overview: e.g. "**INCI Decoder
   classification:** superstar — cell-communicating ingredient".
6. If a source contains a fact that CONTRADICTS the existing KB content, keep both
   and flag it: append "(⚠ source conflict — verify)" to the relevant sentence.
7. Do NOT add product recommendations, brand names, or pricing.
8. Do NOT change the tone — keep it clinical but accessible.
9. Output the full updated document in Markdown. Nothing else — no preamble, no
   explanation outside the document itself.
"""


def read_sources(entry: dict) -> str:
    parts: list[str] = []

    if entry.get("pc") and entry["pc"].exists():
        parts.append("=== PAULA'S CHOICE (primary source) ===")
        parts.append(entry["pc"].read_text(encoding="utf-8"))

    for inci_path in entry.get("inci", []):
        if inci_path.exists():
            parts.append(f"=== INCI DECODER: {inci_path.stem} ===")
            parts.append(inci_path.read_text(encoding="utf-8"))

    if entry.get("pubmed") and entry["pubmed"].exists():
        records = json.loads(entry["pubmed"].read_text(encoding="utf-8"))
        parts.append("=== PUBMED ABSTRACTS ===")
        for r in records:
            parts.append(
                f"PMID:{r['pmid']} | {', '.join(r['authors'][:2])} ({r['year']}) | "
                f"{r['journal']}\n{r['title']}\nDOI:{r['doi']}\n{r['abstract']}\n"
            )

    return "\n\n".join(parts)


def enrich(name: str, entry: dict, dry_run: bool) -> None:
    kb_path: Path = entry["kb"]
    if not kb_path.exists():
        print(f"  [SKIP] KB file not found: {kb_path}")
        return

    current = kb_path.read_text(encoding="utf-8")
    sources = read_sources(entry)

    user_msg = (
        f"## Current KB document\n\n{current}\n\n"
        f"## Raw source files\n\n{sources}"
    )

    print(f"  Calling LLM for {name}…")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=4096,
    )
    enriched = response.choices[0].message.content.strip()

    if dry_run:
        print(f"\n--- DRY RUN: {name} ---")
        print(enriched[:800])
        print("…")
        return

    kb_path.write_text(enriched + "\n", encoding="utf-8")
    print(f"  [OK] {kb_path} updated ({len(enriched)} chars)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich KB documents from real sources")
    parser.add_argument("--ingredient", help="Single ingredient key (e.g. retinol)")
    parser.add_argument("--dry-run", action="store_true", help="Print output, don't write")
    args = parser.parse_args()

    targets = (
        {args.ingredient: INGREDIENT_MAP[args.ingredient]}
        if args.ingredient
        else INGREDIENT_MAP
    )

    for i, (name, entry) in enumerate(targets.items()):
        print(f"\n[{i+1}/{len(targets)}] {name}")
        try:
            enrich(name, entry, args.dry_run)
        except Exception as exc:
            print(f"  [ERROR] {exc}")
        if i < len(targets) - 1:
            time.sleep(1)


if __name__ == "__main__":
    main()
