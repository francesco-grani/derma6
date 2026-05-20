#!/usr/bin/env python3
"""Fetch ingredient pages from the Paula's Choice Ingredient Dictionary.

Uses Playwright (headless Chromium) because the site is a JS-rendered SPA.
Run `uv run playwright install chromium` once before first use.

Usage:
    uv run scripts/scrape_paulas_choice.py
    uv run scripts/scrape_paulas_choice.py --ingredient retinol

Outputs one .txt file per ingredient to data/raw/paulas_choice/.
"""

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from kb_config import INGREDIENTS as _ALL, raw_dir  # noqa: E402

OUTPUT_DIR = raw_dir("paulas_choice")

# slug → PC URL, skipping ingredients with no PC page
INGREDIENTS: dict[str, str] = {
    slug: cfg["pc_url"]
    for slug, cfg in _ALL.items()
    if cfg.get("pc_url")
}

CONTENT_SELECTORS = [
    "[class*='IngredientDetail']",
    "[class*='ingredient-detail']",
    "main article",
    "main",
]


def dismiss_popup(page) -> None:
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass


def extract_text(page) -> str:
    dismiss_popup(page)

    # Try structured selectors first
    for sel in CONTENT_SELECTORS:
        el = page.query_selector(sel)
        if el:
            text = el.inner_text()
            if len(text.strip()) > 200:
                return text.strip()

    # Fallback: grab all visible body text and strip nav/footer noise
    full = page.evaluate("""() => {
        // Remove nav, header, footer, popup elements before extracting
        ['nav', 'header', 'footer', '[role=dialog]', '[class*=popup]', '[class*=modal]',
         '[class*=Popup]', '[class*=Modal]', '[class*=klaviyo]'].forEach(sel => {
            document.querySelectorAll(sel).forEach(el => el.remove());
        });
        return document.body.innerText;
    }""")
    return full.strip()


def fetch_ingredient(slug: str, url: str, browser) -> str | None:
    page = browser.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        content = extract_text(page)
        header = f"Source: {url}\nIngredient: {slug}\n\n"
        return header + content
    except Exception as exc:
        print(f"  [ERROR] {slug}: {exc}")
        return None
    finally:
        page.close()


def save(slug: str, content: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{slug}.txt"
    out.write_text(content, encoding="utf-8")
    print(f"  [OK] saved → {out} ({len(content)} chars)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Paula's Choice ingredient pages")
    parser.add_argument("--ingredient", help="Single ingredient slug (e.g. retinol)")
    args = parser.parse_args()

    targets = {args.ingredient: INGREDIENTS[args.ingredient]} if args.ingredient else INGREDIENTS

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i, (slug, url) in enumerate(targets.items()):
            print(f"Fetching: {slug}")
            content = fetch_ingredient(slug, url, browser)
            if content:
                save(slug, content)
            if i < len(targets) - 1:
                time.sleep(2)
        browser.close()


if __name__ == "__main__":
    main()
