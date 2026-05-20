#!/usr/bin/env python3
"""Fetch subreddit wiki pages via Reddit's public JSON API.

No authentication required for public wikis — Reddit serves them at:
  https://www.reddit.com/r/<sub>/wiki/<page>.json

Usage:
    uv run scripts/fetch_reddit_wiki.py
    uv run scripts/fetch_reddit_wiki.py --sub SkincareAddiction --page routine

Outputs one .txt file per page to data/raw/reddit/.
"""

import argparse
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from kb_config import REDDIT_PAGES as _PAGES, raw_dir  # noqa: E402

OUTPUT_DIR = raw_dir("reddit")

HEADERS = {
    "User-Agent": "skincare-kb-builder/1.0 (research script; contact grani.francesco@gmail.com)",
}

# (subreddit, wiki_page) pairs — sourced from kb_config.py
PAGES: list[tuple[str, str]] = _PAGES


def fetch_wiki_page(sub: str, page: str, client: httpx.Client) -> str | None:
    url = f"https://www.reddit.com/r/{sub}/wiki/{page}.json"
    try:
        resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=15)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  [ERROR] r/{sub}/wiki/{page}: {exc}")
        return None

    data = resp.json()
    # Reddit wiki JSON: data.data.content_md contains the markdown source
    content_md = data.get("data", {}).get("content_md", "")
    if not content_md:
        print(f"  [WARN] r/{sub}/wiki/{page}: empty content_md")
        return None

    # Prepend source metadata
    header = f"Source: https://www.reddit.com/r/{sub}/wiki/{page}\nSubreddit: r/{sub}\nPage: {page}\n\n"
    return header + content_md


def clean_filename(sub: str, page: str) -> str:
    name = f"{sub}__{page}".replace("/", "_")
    return re.sub(r"[^\w\-]", "_", name)


def save(sub: str, page: str, content: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = clean_filename(sub, page) + ".txt"
    out = OUTPUT_DIR / filename
    out.write_text(content, encoding="utf-8")
    print(f"  [OK] saved → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Reddit wiki pages as markdown")
    parser.add_argument("--sub", help="Subreddit name (e.g. SkincareAddiction)")
    parser.add_argument("--page", help="Wiki page slug (e.g. routine)")
    args = parser.parse_args()

    if args.sub and args.page:
        targets = [(args.sub, args.page)]
    else:
        targets = PAGES

    with httpx.Client() as client:
        for i, (sub, page) in enumerate(targets):
            print(f"Fetching: r/{sub}/wiki/{page}")
            content = fetch_wiki_page(sub, page, client)
            if content:
                save(sub, page, content)
            if i < len(targets) - 1:
                time.sleep(2)


if __name__ == "__main__":
    main()
