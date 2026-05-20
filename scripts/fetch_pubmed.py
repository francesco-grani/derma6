#!/usr/bin/env python3
"""Fetch PubMed abstracts for skincare ingredient search terms.

Uses NCBI E-utilities (no API key required for <3 req/s; rate limited here).
Outputs one .json file per ingredient to data/raw/pubmed/.

Usage:
    uv run scripts/fetch_pubmed.py
    uv run scripts/fetch_pubmed.py --ingredient retinol
    uv run scripts/fetch_pubmed.py --max-results 5
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from kb_config import INGREDIENTS as _ALL, raw_dir  # noqa: E402

OUTPUT_DIR = raw_dir("pubmed")

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

# slug → PubMed search query (from central config)
INGREDIENTS: dict[str, str] = {slug: cfg["pubmed_query"] for slug, cfg in _ALL.items()}


def search_pmids(query: str, max_results: int, client: httpx.Client) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    resp = client.get(ESEARCH, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_abstracts(pmids: list[str], client: httpx.Client) -> list[dict]:
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    resp = client.get(EFETCH, params=params, timeout=20)
    resp.raise_for_status()

    # Parse XML minimally — extract PMID, title, abstract, authors, year
    from xml.etree import ElementTree as ET

    root = ET.fromstring(resp.text)
    results: list[dict] = []

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        title_el = article.find(".//ArticleTitle")
        abstract_el = article.find(".//AbstractText")
        year_el = article.find(".//PubDate/Year")
        journal_el = article.find(".//Journal/Title")
        doi_el = article.find(".//ArticleId[@IdType='doi']")

        authors = []
        for author in article.findall(".//Author")[:3]:
            last = author.findtext("LastName", "")
            initials = author.findtext("Initials", "")
            if last:
                authors.append(f"{last} {initials}".strip())

        results.append({
            "pmid": pmid_el.text if pmid_el is not None else "",
            "title": title_el.text if title_el is not None else "",
            "abstract": abstract_el.text if abstract_el is not None else "",
            "authors": authors,
            "year": year_el.text if year_el is not None else "",
            "journal": journal_el.text if journal_el is not None else "",
            "doi": doi_el.text if doi_el is not None else "",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid_el.text}/" if pmid_el is not None else "",
        })

    return results


def save(key: str, data: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{key}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] {len(data)} abstracts saved → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch PubMed abstracts for KB ingredients")
    parser.add_argument("--ingredient", help="Single ingredient key (e.g. retinol)")
    parser.add_argument("--max-results", type=int, default=3, help="Abstracts per ingredient (default: 3)")
    args = parser.parse_args()

    targets = {args.ingredient: INGREDIENTS[args.ingredient]} if args.ingredient else INGREDIENTS

    with httpx.Client() as client:
        for i, (key, query) in enumerate(targets.items()):
            print(f"Searching PubMed: {key!r}")
            try:
                pmids = search_pmids(query, args.max_results, client)
                print(f"  Found PMIDs: {pmids}")
                time.sleep(0.4)  # NCBI rate limit: <3 req/s without API key
                abstracts = fetch_abstracts(pmids, client)
                save(key, abstracts)
            except Exception as exc:
                print(f"  [ERROR] {key}: {exc}")
            if i < len(targets) - 1:
                time.sleep(1)


if __name__ == "__main__":
    main()
