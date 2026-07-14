"""Relevance filtering for domain-scoped-search candidates (Requirements
1-5, 7.1).

Houses Part A of the product-finder-streaming feature end-to-end: the
batched relevance-classification LLM call (`_classify_relevance`) and the
filter -> bounded backfill -> reclassify orchestration (`filter_category`).
Kept as its own module rather than folded into `product_finder.py` (already
substantial) or `product_source_discovery.py` (a different concern —
discovering *domains*, not classifying *listings*) — mirrors the precedent
product-source-agent's design already set for `domain_search.py`.

See design.md's "Process 2: Relevance filter + bounded backfill" flowchart
for the full step-by-step algorithm `filter_category` implements; every
terminal node in that flowchart is reached with at most two
`_classify_relevance` calls, so Requirement 4.3's "two calls per category,
maximum, never open-ended" is true by construction (no loop), not by a
runtime guard.
"""

import asyncio
import logging

from openai import AsyncOpenAI

from backend.config import settings
from backend.llm.structured import StructuredOutputError, structured_completion
from backend.schemas import ListingRelevanceLLM, ProductListing
from backend.tools.stage_events import StageEmitter

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)
# Module-level singleton, mirroring product_source_discovery.py's client-
# construction pattern (AsyncOpenAI() performs no I/O at construction time,
# so this is safe regardless of whether this module's functions ever run on
# a given request path).


# ── LLM call (Req 1.1, 1.2, 2, 4.1) ──────────────────────────────────────────

_RELEVANCE_SYSTEM_PROMPT = (
    "You classify web-search results for a specific product as genuine "
    "single-product listing pages versus category/collection pages or "
    "editorial/blog articles.\n\n"
    "Given a product name (and optional brand) and a numbered list of "
    "candidates (title, snippet, url), return the indices of every "
    "candidate that is a genuine page for that specific product — not a "
    "category/collection page listing many products, and not a blog/"
    "editorial article that merely mentions the product."
)


def _build_user_content(name: str, brand: str | None, candidates: list[ProductListing]) -> str:
    """Numbers `candidates` 0..len(candidates)-1 in the user message, one
    line per candidate built from its title/listing_url — there is no
    separate snippet field retained on `ProductListing`; `title` already
    carries the search result's title text, which is what the
    classification prompt needs."""
    product = f"{brand} {name}" if brand else name
    lines = [f"Product: {product}", "", "Candidates:"]
    lines.extend(
        f"{index}. title={candidate.title!r} url={candidate.listing_url!r}"
        for index, candidate in enumerate(candidates)
    )
    return "\n".join(lines)


async def _classify_relevance(
    name: str, brand: str | None, candidates: list[ProductListing]
) -> list[int] | None:
    """One `structured_completion()` call classifying `candidates` (Req
    1.1/1.2 — at most one call per invocation, never one per candidate).
    Candidates are numbered 0..len(candidates)-1 in the user message built
    from each `ProductListing`'s title/listing_url.

    Returns the model's `genuine_indices`, restricted to the valid
    `0..len(candidates)-1` range and deduplicated (an out-of-range or
    negative index is dropped rather than clamped to a boundary value,
    since clamping could silently accept a candidate the model never
    actually identified). Returns `None` — not an empty list — if the call
    fails, times out (bounded by
    `settings.relevance_classification_timeout_seconds`, Req 2.3), or
    `structured_completion` raises `StructuredOutputError`; `None` is the
    signal callers use to mean 'could not classify, treat every candidate
    as genuine' (Req 2.1/2.2), which an empty list would incorrectly mean
    'the model classified zero as genuine'. Never raises."""
    try:
        result, _used_fallback = await asyncio.wait_for(
            structured_completion(
                _client,
                model=settings.effective_relevance_classification_model,
                schema_model=ListingRelevanceLLM,
                system_prompt=_RELEVANCE_SYSTEM_PROMPT,
                user_content=_build_user_content(name, brand, candidates),
            ),
            timeout=settings.relevance_classification_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Relevance classification timed out after %ss: product=%r candidates=%d",
            settings.relevance_classification_timeout_seconds,
            name,
            len(candidates),
        )
        return None
    except StructuredOutputError as exc:
        logger.warning(
            "Relevance classification failed: product=%r candidates=%d error=%s",
            name,
            len(candidates),
            exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001 - belt-and-suspenders, Req 2.1/2.2
        logger.error(
            "Relevance classification raised unexpectedly: product=%r candidates=%d error=%s",
            name,
            len(candidates),
            exc,
        )
        return None

    valid_indices_max = len(candidates) - 1
    seen: set[int] = set()
    genuine_indices: list[int] = []
    for index in result.genuine_indices:
        if 0 <= index <= valid_indices_max and index not in seen:
            seen.add(index)
            genuine_indices.append(index)
    return genuine_indices


# ── Filter -> backfill -> reclassify orchestration (Req 1-4, 7.1) ───────────


async def filter_category(
    name: str,
    brand: str | None,
    diversified: list[ProductListing],
    raw_pool: list[ProductListing],
    max_per_category: int,
    on_stage: StageEmitter | None = None,
) -> list[ProductListing]:
    """The full filter -> backfill -> reclassify pipeline for one category
    (Req 1-4), called once per category (retail, or secondhand
    marketplaces — Req 5) from `_lookup_retail`/
    `_lookup_secondhand_marketplaces`. Never raises; every failure mode
    degrades to 'return more listings than would otherwise be dropped',
    never fewer (Req 2 — the never-raise philosophy already established for
    per-source lookups, applied to this step).

    `on_stage`, when given, emits exactly one "relevance_filter" stage event
    (Req 7.1's "the relevance-classification step, when it runs" — singular,
    covering both the initial pass and any backfill reclassification pass as
    one user-visible step), emitted once, before the first classification
    call, only if `diversified` is non-empty (Req 7.2 — no event for a
    category with nothing to classify).

    See the module docstring / design.md's "Process 2" flowchart for the
    full step-by-step algorithm and Requirements traceability.
    """
    if not diversified:
        return []

    if on_stage is not None:
        on_stage("relevance_filter", "Checking listing relevance")

    genuine_indices = await _classify_relevance(name, brand, diversified)
    if genuine_indices is None:
        logger.info(
            "Relevance filter pass 1 unavailable, returning unfiltered: "
            "product=%r candidates=%d",
            name,
            len(diversified),
        )
        return diversified

    genuine_set = set(genuine_indices)
    accepted = [listing for index, listing in enumerate(diversified) if index in genuine_set]
    rejected_urls = {
        listing.listing_url for index, listing in enumerate(diversified) if index not in genuine_set
    }

    logger.info(
        "Relevance filter pass 1: product=%r candidates=%d accepted=%d rejected=%d",
        name,
        len(diversified),
        len(accepted),
        len(rejected_urls),
    )

    # Req 3.3: nothing to backfill for if the category is already at its cap
    # or filtering rejected nothing.
    if len(accepted) >= max_per_category or not rejected_urls:
        return accepted

    # Req 3.1/3.2: pull only candidates not already present in this
    # category's pre-filter set (accepted or rejected), by listing_url.
    already_seen_urls = {listing.listing_url for listing in accepted} | rejected_urls
    backfill_candidates = [
        listing for listing in raw_pool if listing.listing_url not in already_seen_urls
    ]
    if not backfill_candidates:
        return accepted

    backfilled = backfill_candidates[: max_per_category - len(accepted)]

    # Req 4.1: pass 2 is scoped only to the backfilled candidates, never
    # re-running classification over candidates pass 1 already accepted.
    # No further on_stage call here — Req 7.1's single "relevance_filter"
    # event (emitted once, above) covers both the initial pass and any
    # backfill reclassification pass as one user-visible step.
    backfill_genuine_indices = await _classify_relevance(name, brand, backfilled)
    if backfill_genuine_indices is None:
        logger.info(
            "Relevance filter pass 2 unavailable, including backfill unfiltered: "
            "product=%r backfilled=%d",
            name,
            len(backfilled),
        )
        return accepted + backfilled

    backfill_genuine_set = set(backfill_genuine_indices)
    accepted_backfill = [
        listing for index, listing in enumerate(backfilled) if index in backfill_genuine_set
    ]
    logger.info(
        "Relevance filter pass 2 (backfill): product=%r backfilled=%d accepted=%d",
        name,
        len(backfilled),
        len(accepted_backfill),
    )
    # Req 4.2: drop pass-2 rejections, no further backfill cycle regardless
    # of the resulting count.
    return accepted + accepted_backfill
