#!/usr/bin/env python3
"""Fetch ingredient pages from INCI Decoder.

Usage:
    uv run scripts/scrape_inci_decoder.py
    uv run scripts/scrape_inci_decoder.py --ingredient retinol

Outputs one .txt file per ingredient to data/raw/inci_decoder/.
Extracts: what-it-does summary, irritancy level, comedogenicity score.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from kb_config import INGREDIENTS as _ALL, raw_dir  # noqa: E402

OUTPUT_DIR = raw_dir("inci_decoder")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Flatten all inci_slugs across ingredients → {inci_slug: display_name}
INGREDIENTS: dict[str, str] = {
    inci_slug: f"{cfg['display_name']} ({inci_slug})"
    for cfg in _ALL.values()
    for inci_slug in cfg["inci_slugs"]
}

BASE_URL = "https://incidecoder.com/ingredients/"


def fetch_ingredient(slug: str, client: httpx.Client) -> str | None:
    url = f"{BASE_URL}{slug}"
    try:
        resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  [ERROR] {slug}: {exc}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    sections: list[str] = [f"Source: {url}", f"Ingredient: {INGREDIENTS[slug]}", ""]

    # Basic info box: also-called, what-it-does
    info_box = soup.select_one(".ingredinfobox")
    if info_box:
        sections.append("## Basic Info")
        sections.append(info_box.get_text(separator="\n", strip=True))

    # Main description / "Our Take" databox
    databox = soup.select_one(".databox")
    if databox:
        sections.append("\n## Description")
        # Extract bullet points
        for li in databox.find_all("li"):
            sections.append(f"- {li.get_text(strip=True)}")
        # Extract any paragraphs outside of li
        for p in databox.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                sections.append(text)

    # Studies / references list
    doclist = soup.select_one(".doclist")
    if doclist:
        sections.append("\n## Studies Cited")
        for item in doclist.find_all(["li", "div", "p"]):
            text = item.get_text(separator=" ", strip=True)
            if text and len(text) > 20:
                sections.append(f"- {text}")

    return "\n".join(sections)


def save(slug: str, content: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{slug}.txt"
    out.write_text(content, encoding="utf-8")
    print(f"  [OK] saved → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape INCI Decoder ingredient pages")
    parser.add_argument("--ingredient", help="Single slug to fetch (e.g. retinol)")
    args = parser.parse_args()

    targets = {args.ingredient: INGREDIENTS[args.ingredient]} if args.ingredient else INGREDIENTS

    with httpx.Client() as client:
        for i, (slug, name) in enumerate(targets.items()):
            print(f"Fetching: {name} ({slug})")
            content = fetch_ingredient(slug, client)
            if content:
                save(slug, content)
            if i < len(targets) - 1:
                time.sleep(2)


if __name__ == "__main__":
    main()
