"""Product finder tool: on-demand retail and secondhand listings lookup.

Exposes `GET /api/products/find` (Requirement 9.2). Unlike the LangChain tools
in this package (`spf_recommender.py`, `kb_search.py`), this module is a
read-only HTTP endpoint invoked directly by the frontend, not a tool wired
into the agent graph — see design.md's "Why backend/tools/, and why its own
router" for the rationale.

Module layout:
    1. Imports
    2. Router declaration
    3. Price extraction helper
    4. Source lookups: Vinted / retail + secondhand-marketplace / Kleinanzeigen
    5. The `/find` endpoint itself

Market/location resolution (`MarketConfig`/`MARKET_CONFIGS`/`resolve_market()`,
product-finder v1) has been replaced by the agentic source-discovery step in
`backend/tools/product_source_discovery.py` (product-source-agent) —
`_normalize_location`/`_is_germany` are imported from that module rather than
defined here, to avoid a circular import (see that module's docstring).
"""

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, AsyncIterator, Literal

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from vinted import Vinted

from backend.auth import get_current_user
from backend.config import settings
from backend.db.deps import get_product_cache_store, get_profile_store, get_source_discovery_store
from backend.db.product_cache_store import ProductCacheStore
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.db.source_discovery_store import SourceDiscoveryStore
from backend.schemas import (
    DiscoveredSources,
    ProductFindResponse,
    ProductFindResultEvent,
    ProductFindStageEvent,
    ProductListing,
    UserProfile,
)
from backend.tools.domain_search import search_domain
from backend.tools.product_source_discovery import (
    _is_germany,
    _normalize_location,
    get_or_discover_sources,
)
from backend.tools.relevance_filter import filter_category

if TYPE_CHECKING:
    from backend.tools.stage_events import StageEmitter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])

# ── Price extraction helper (Requirement 11.5/11.6) ─────────────────────────

# Currency symbol -> ISO 4217 code, matching the `currency` field's wire
# format elsewhere in this feature (Vinted's `currency_code`, e.g. "EUR").
_CURRENCY_SYMBOLS: dict[str, str] = {"€": "EUR", "$": "USD", "£": "GBP"}
_SYMBOL_CLASS = "".join(re.escape(symbol) for symbol in _CURRENCY_SYMBOLS)

# Matches either a symbol-prefixed amount ("€12.99") or a symbol-suffixed
# amount ("12,99 €"). The amount allows an optional group of thousands
# separators ("." or ",") followed by an optional two-digit fractional part;
# _normalize_amount() below resolves which separator is the decimal point.
_PRICE_RE = re.compile(
    rf"(?:(?P<prefix_symbol>[{_SYMBOL_CLASS}])\s?"
    rf"(?P<prefix_amount>\d{{1,3}}(?:[.,]\d{{3}})*(?:[.,]\d{{2}})?))"
    rf"|(?:(?P<suffix_amount>\d{{1,3}}(?:[.,]\d{{3}})*(?:[.,]\d{{2}})?)"
    rf"\s?(?P<suffix_symbol>[{_SYMBOL_CLASS}]))"
)


def _normalize_amount(raw: str) -> float | None:
    """Normalize a matched amount string (e.g. "1.234,56", "12,99", "12.99")
    into a float.

    Treats the last "." or "," in `raw` as the decimal separator and any
    earlier ones as thousands separators, matching both German ("12,99")
    and English ("12.99") price conventions.
    """
    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    decimal_pos = max(last_dot, last_comma)
    if decimal_pos == -1:
        cleaned = raw
    else:
        integer_part = re.sub(r"[.,]", "", raw[:decimal_pos])
        fractional_part = raw[decimal_pos + 1 :]
        cleaned = f"{integer_part}.{fractional_part}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_price(text: str) -> tuple[float | None, str | None]:
    """Best-effort regex price extraction from a retail search result's
    title/snippet (Req 11.5).

    Recognizes symbol-prefixed ("€12.99") and symbol-suffixed ("12,99 €")
    amounts. Returns `(None, None)` when no clean price is found — callers
    still include the listing in that case rather than discarding it
    (Req 11.6).
    """
    match = _PRICE_RE.search(text)
    if match is None:
        return None, None

    if match.group("prefix_symbol") is not None:
        symbol = match.group("prefix_symbol")
        raw_amount = match.group("prefix_amount")
    else:
        symbol = match.group("suffix_symbol")
        raw_amount = match.group("suffix_amount")

    amount = _normalize_amount(raw_amount)
    if amount is None:
        return None, None

    return amount, _CURRENCY_SYMBOLS[symbol]


# ── Vinted (secondhand) lookup (Requirement 10) ─────────────────────────────


def _search_vinted_sync(query: str, country_code: str) -> list:
    """Blocking Vinted search: construction does a Cloudflare-bypass call via
    `cloudscraper`, and `.search()` is itself a blocking HTTP call. Must be
    run off the event loop (see `_lookup_secondhand`)."""
    client = Vinted(domain=country_code)
    response = client.search(query=query)
    return response.items


async def _lookup_secondhand(
    name: str, brand: str | None, vinted_domain: str
) -> tuple[list[ProductListing], bool]:
    """Look up secondhand listings for `name`/`brand` on Vinted
    (Req 10.1-10.3, Req 4.3's "parameterized by the discovered locale instead
    of a hardcoded one"). `vinted_domain` (e.g. "vinted.it") replaces the old
    `market: MarketConfig` parameter — the short country-code derivation
    (`.rsplit(".", 1)[-1]`) is unchanged in spirit, just reads from the plain
    string argument instead of `market.vinted_domain`.

    Runs the blocking `vinted-api-wrapper` calls in a thread and bounds them
    with `settings.product_lookup_timeout_seconds` (Req 12). Never raises:
    any failure (timeout or otherwise) is logged and surfaced as `([], False)`
    so the caller can still return partial results from other sources
    (Req 14).
    """
    query = f"{brand} {name}" if brand else name
    country_code = vinted_domain.rsplit(".", 1)[-1]

    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(_search_vinted_sync, query, country_code),
            timeout=settings.product_lookup_timeout_seconds,
        )
        # Result processing (not just the network call) is inside this same
        # try block: `vinted-api-wrapper` can return a malformed/unexpected
        # `response.items` (observed live: on an internal JSON-parse failure
        # it silently falls back to a shape whose `.items` isn't a list),
        # and that must degrade to `([], False)` like any other failure
        # rather than raise (Req 14) — see product-finder memory/incident
        # notes for the live repro.
        listings = [
            ProductListing(
                type="used",
                title=item.title,
                price=_parse_vinted_amount(getattr(item.price, "amount", None)),
                currency=getattr(item.price, "currency_code", None),
                source="Vinted",
                thumbnail_url=getattr(item.photo, "url", None),
                listing_url=item.url,
            )
            for item in items[: settings.product_max_listings_per_source]
        ]
    except asyncio.TimeoutError:
        logger.error(
            "Vinted lookup timed out: source=vinted query=%r vinted_domain=%s",
            query,
            vinted_domain,
        )
        return [], False
    except Exception as exc:  # noqa: BLE001 - external API, must not raise
        logger.error(
            "Vinted lookup failed: source=vinted query=%r vinted_domain=%s error=%s",
            query,
            vinted_domain,
            exc,
        )
        return [], False

    return listings, True


def _parse_vinted_amount(raw_amount: str | None) -> float | None:
    """Vinted's `Price.amount` is a decimal-looking string (e.g. "12.99");
    parse it to a float, tolerating `None`/malformed values (Req 10.3)."""
    if raw_amount is None:
        return None
    try:
        return float(raw_amount)
    except ValueError:
        return None


# ── Retail (new) / secondhand-marketplace lookup (Requirements 4, 5, 11) ────

_MAX_LISTINGS_PER_SOURCE_DOMAIN = 3  # unchanged from v1


def _diversify_by_source(
    listings: list[ProductListing], max_per_source: int
) -> list[ProductListing]:
    """Interleaves `listings` round-robin by `source` and drops any beyond
    `max_per_source` for a single source, so the retail results aren't
    dominated by whichever retailer domain the search ranked highest (in
    practice, Amazon)."""
    by_source: dict[str, list[ProductListing]] = {}
    for listing in listings:
        by_source.setdefault(listing.source, []).append(listing)
    for bucket in by_source.values():
        del bucket[max_per_source:]

    interleaved: list[ProductListing] = []
    while any(by_source.values()):
        for bucket in by_source.values():
            if bucket:
                interleaved.append(bucket.pop(0))
    return interleaved


async def _query_domain(
    query: str,
    domain: str,
    listing_type: Literal["new", "used"],
    max_results: int,
    on_stage: "StageEmitter | None" = None,
) -> tuple[list[ProductListing], bool]:
    """One domain's contribution to a category (Req 5.1): calls
    `domain_search.search_domain(query, domain, max_results,
    timeout_seconds=settings.product_lookup_timeout_seconds)` (Req 4.5's
    existing 8s per-source timeout, now applied per domain), builds
    `ProductListing`s tagged `type=listing_type`, `source=domain` (the domain
    the query was scoped to — Tavily's `include_domains=[domain]`/the DDG
    `site:domain` qualifier already guarantee every result belongs to that
    domain, so there's no more "which configured domain does this URL belong
    to" ambiguity to resolve — `_retail_source_from_url()` is removed, this
    is strictly simpler than v1). Price extraction (`_extract_price`)
    unchanged. Never raises — any failure/timeout is logged (`source=domain`)
    and returns `([], False)` (Req 5.4).

    `on_stage` (Req 7.3), when given, is called with `("domain_check", ...)`
    as the very first statement inside the `try` block below, before
    `search_domain(...)` is awaited — emitted at the moment this domain's
    query actually dispatches, not synthesized before/after."""
    try:
        if on_stage is not None:
            on_stage("domain_check", f"Checking {domain}...")
        results, ok = await search_domain(
            query, domain, max_results, timeout_seconds=settings.product_lookup_timeout_seconds
        )
        if not ok:
            logger.error(
                "Domain lookup failed: source=%s query=%r listing_type=%s",
                domain,
                query,
                listing_type,
            )
            return [], False

        listings: list[ProductListing] = []
        for item in results[:max_results]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            url = item.get("url", "")
            price, currency = _extract_price(f"{title} {snippet}")
            listings.append(
                ProductListing(
                    type=listing_type,
                    title=title,
                    price=price,
                    currency=currency,
                    source=domain,
                    thumbnail_url=None,
                    listing_url=url,
                )
            )
    except Exception as exc:  # noqa: BLE001 - external API, must not raise
        logger.error(
            "Domain lookup raised: source=%s query=%r listing_type=%s error=%s",
            domain,
            query,
            listing_type,
            exc,
        )
        return [], False

    return listings, True


async def _lookup_domains(
    name: str,
    brand: str | None,
    domains: tuple[str, ...],
    listing_type: Literal["new", "used"],
    on_stage: "StageEmitter | None" = None,
) -> tuple[list[ProductListing], bool, list[ProductListing]]:
    """The shared category-level fan-out + combine used by both
    `_lookup_retail` and `_lookup_secondhand_marketplaces` (Req 4.1, 4.2 —
    "the same domain-scoped web-search mechanism"). Runs `_query_domain`
    concurrently across every domain in `domains` via `asyncio.gather`
    (Req 5.2); combines the per-domain result lists with
    `_diversify_by_source` (kept, unchanged implementation), capped at
    `settings.product_max_listings_per_source` total. Category-level
    `ok = any(domain_ok for _, domain_ok in per_domain_results)` — at least
    one domain succeeding is enough (Req 5.4); an empty `domains` tuple
    returns `([], False, [])` without issuing any query (defensive — in
    practice `find_product` never calls this with an empty tuple, since it
    skips the lookup entirely when discovery yielded zero domains for that
    category, per Requirement 7.4/7.5).

    `on_stage` (Req 7.3/7.4), when given, is passed through to every
    `_query_domain` call so each domain's own coroutine emits its own
    "domain_check" event at the moment its query actually dispatches, fully
    independent of the others — `asyncio.gather`'s concurrency (Req 5.2,
    Non-Functional Consideration 2) is untouched, since emitting is a
    synchronous, non-blocking statement each coroutine makes on its own
    schedule, not a shared synchronization point.

    Returns a third element, `raw_pool` (Req 3.1): the flat concatenation of
    every domain's *pre-diversification* listings, in `asyncio.gather`'s
    input-preserving order — this is exactly the material
    `_diversify_by_source`'s per-domain truncation and the final
    `[:max_results]` slice below can throw away, retained here instead of
    discarded so `filter_category`'s backfill step (Req 3) has candidates to
    draw from. `raw_pool` is a superset of the returned diversified
    `listings`."""
    if not domains:
        return [], False, []

    query = f"{brand} {name}" if brand else name
    max_results = settings.product_max_listings_per_source

    per_domain_results = await asyncio.gather(
        *(
            _query_domain(query, domain, listing_type, max_results, on_stage)
            for domain in domains
        )
    )

    raw_pool: list[ProductListing] = []
    for domain_listings, _domain_ok in per_domain_results:
        raw_pool.extend(domain_listings)
    listings = _diversify_by_source(list(raw_pool), _MAX_LISTINGS_PER_SOURCE_DOMAIN)[:max_results]

    ok = any(domain_ok for _, domain_ok in per_domain_results)
    return listings, ok, raw_pool


# A desktop-browser UA gets several retailers' bot-detection page instead of
# the real listing (verified live: dm.de serves an empty SPA shell, rossmann.de
# a "Client Challenge" page) — but the *same* retailers serve the real,
# fully-rendered page, og:image included, to known link-preview crawler UAs,
# since that's the exact mechanism they rely on for their own rich previews in
# messaging apps. Impersonating one gets the enrichment fetch treated as that
# case rather than as generic bot traffic. (douglas.de/flaconi.de reject every
# UA tried, crawler or not — a real WAF/Cloudflare challenge, not UA-based, so
# this doesn't help there.)
_OG_IMAGE_HEADERS = {
    "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
}


def _find_ld_json_product(soup: BeautifulSoup) -> dict | None:
    """Locate a schema.org `Product` object among a page's
    `application/ld+json` script tags (Google Shopping/rich-results
    boilerplate that most e-commerce sites already emit for SEO — a
    standards-based extraction tier, not a per-retailer hack, so it
    generalizes to retailers the discovery agent surfaces in the future
    without needing a dedicated parser written for each one).

    Handles the two wrapping shapes seen live: a bare single object, and a
    top-level `@graph` array mixing `Product` in with unrelated types like
    `BreadcrumbList`/`WebSite`. Returns the first `Product` match, or `None`
    if no script tag parses as JSON or none contains one — malformed JSON-LD
    (not uncommon in the wild) is silently skipped, never raised, since the
    caller still has its other extraction tiers to try.
    """
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if isinstance(candidate.get("@graph"), list):
                candidates.extend(item for item in candidate["@graph"] if isinstance(item, dict))
            node_type = candidate.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if "Product" in types:
                return candidate

    return None


def _ld_json_image_url(product: dict) -> str | None:
    """Extract an image URL from a schema.org `Product`'s `image` field,
    which the spec allows as a bare URL string, a list of either, or an
    `ImageObject` (`{"url": ...}`) — real pages use all three shapes."""
    image = product.get("image")
    if isinstance(image, str) and image:
        return image
    if isinstance(image, dict):
        url = image.get("url")
        return url if isinstance(url, str) and url else None
    if isinstance(image, list):
        for item in image:
            if isinstance(item, str) and item:
                return item
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url:
                    return url
    return None


def _extract_thumbnail_from_html(html: str) -> str | None:
    """Best-effort image URL extraction from a retail listing page's HTML.

    Tries, in order: the `og:image` meta tag (most retailers), `twitter:image`
    (fallback), schema.org `Product` JSON-LD's `image` field (see
    `_find_ld_json_product`/`_ld_json_image_url` — verified live to be what
    dm.de exposes instead of either meta tag), then Amazon's proprietary
    `data-a-dynamic-image` attribute on `#landingImage`. The last one matters
    in practice, not just in theory: verified live that Amazon product pages
    carry neither `og:image`/`twitter:image` nor `Product` JSON-LD at all,
    and Amazon dominates real result counts among `market.retailer_domains` —
    without this fallback, thumbnail enrichment silently does nothing for a
    large share of retail results.
    """
    soup = BeautifulSoup(html, "lxml")

    tag = soup.select_one('meta[property="og:image"]') or soup.select_one(
        'meta[name="twitter:image"]'
    )
    content = tag.get("content") if tag else None
    if isinstance(content, str) and content:
        return content

    product = _find_ld_json_product(soup)
    if product is not None:
        image_url = _ld_json_image_url(product)
        if image_url is not None:
            return image_url

    landing_image = soup.select_one("#landingImage")
    if landing_image:
        raw = landing_image.get("data-a-dynamic-image")
        if isinstance(raw, str) and raw:
            try:
                candidates = list(json.loads(raw).keys())
            except (json.JSONDecodeError, AttributeError):
                candidates = []
            if candidates:
                return candidates[0]

    return None


async def _fetch_og_image(url: str) -> str | None:
    """Best-effort fetch of a retail listing page's thumbnail image, since
    neither Tavily's nor DuckDuckGo's per-result data includes one (Tavily's
    `include_images` returns an unordered, page-wide list with no reliable
    correspondence to a specific result, so it can't be used per-listing).
    See `_extract_thumbnail_from_html` for the actual extraction logic.

    Never raises and has its own short timeout independent of the overall
    retail lookup: a single slow/broken listing page must cost that listing
    its thumbnail, not the whole lookup's already-successful title/price/url
    data (see `_lookup_retail`'s enrichment step)."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.product_thumbnail_fetch_timeout_seconds,
            headers=_OG_IMAGE_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception:  # noqa: BLE001 - best-effort enrichment, must not raise
        return None

    return _extract_thumbnail_from_html(response.text)


def _ld_json_price(product: dict) -> tuple[float | None, str | None]:
    """Extract `(amount, currency)` from a schema.org `Product`'s `offers`
    field, which the spec allows as a single `Offer` or a list of them (e.g.
    per size/variant) — the first offer with a usable `price` wins. JSON-LD
    `price` is usually a bare JSON number (not text needing separator
    disambiguation), but some sites quote it as a string, so both are
    handled: numeric values are used directly, string values go through
    `_normalize_amount()` like every other text-sourced price in this
    module."""
    offers = product.get("offers")
    offer_candidates = offers if isinstance(offers, list) else [offers]
    for offer in offer_candidates:
        if not isinstance(offer, dict):
            continue
        raw_price = offer.get("price")
        amount: float | None = None
        if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool):
            amount = float(raw_price)
        elif isinstance(raw_price, str) and raw_price:
            amount = _normalize_amount(raw_price)
        if amount is not None:
            currency = offer.get("priceCurrency")
            return amount, currency if isinstance(currency, str) else None
    return None, None


def _extract_price_from_html(html: str) -> tuple[float | None, str | None]:
    """Best-effort price extraction from a retail listing page's HTML, used
    as a fallback when `_extract_price()` found nothing in the search
    result's title/snippet text — see that function's docstring on why
    that's inherently hit-or-miss per result, not per source. Tries, in
    order: Open Graph's `product:price:amount`/`product:price:currency` meta
    tags, schema.org `itemprop="price"`/`itemprop="priceCurrency"`
    microdata, schema.org `Product` JSON-LD's `offers.price`/
    `offers.priceCurrency` (see `_find_ld_json_product`/`_ld_json_price` —
    verified live to be what dm.de exposes instead of either of the above),
    then Amazon's `.a-price .a-offscreen` text node (parsed with
    `_extract_price()`, same as the search-snippet path).
    """
    soup = BeautifulSoup(html, "lxml")

    amount_tag = soup.select_one('meta[property="product:price:amount"]')
    if amount_tag:
        raw_amount = amount_tag.get("content")
        amount = _normalize_amount(raw_amount) if isinstance(raw_amount, str) else None
        if amount is not None:
            currency_tag = soup.select_one('meta[property="product:price:currency"]')
            currency = currency_tag.get("content") if currency_tag else None
            return amount, currency if isinstance(currency, str) else None

    price_el = soup.select_one('[itemprop="price"]')
    if price_el:
        raw_amount = price_el.get("content") or price_el.get_text(strip=True)
        amount = _normalize_amount(raw_amount) if isinstance(raw_amount, str) else None
        if amount is not None:
            currency_el = soup.select_one('[itemprop="priceCurrency"]')
            raw_currency = (
                (currency_el.get("content") or currency_el.get_text(strip=True))
                if currency_el
                else None
            )
            return amount, raw_currency if isinstance(raw_currency, str) else None

    product = _find_ld_json_product(soup)
    if product is not None:
        amount, currency = _ld_json_price(product)
        if amount is not None:
            return amount, currency

    offscreen = soup.select_one(".a-price .a-offscreen")
    if offscreen:
        text = offscreen.get_text(strip=True)
        if text:
            return _extract_price(text)

    return None, None


async def _fetch_listing_price(url: str) -> tuple[float | None, str | None]:
    """Best-effort re-fetch of a retail listing page to extract its price
    directly from the page HTML, used only for listings whose price came
    back `None` from the search snippet (Amazon's snippets very rarely
    include one, so without this its price line is almost always empty).
    Mirrors `_fetch_og_image()`'s never-raise, independently-timed-out
    contract — a separate fetch rather than sharing `_fetch_og_image()`'s
    response, since that function's thumbnail-only contract is already
    covered by its own tests and callers; the extra request only happens for
    the subset of listings that actually need it.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.product_thumbnail_fetch_timeout_seconds,
            headers=_OG_IMAGE_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception:  # noqa: BLE001 - best-effort enrichment, must not raise
        return None, None

    return _extract_price_from_html(response.text)


async def _lookup_retail(
    name: str,
    brand: str | None,
    retailer_domains: tuple[str, ...],
    on_stage: "StageEmitter | None" = None,
) -> tuple[list[ProductListing], bool]:
    """Look up new (retail) listings for `name`/`brand`, one concurrent query
    per domain in `retailer_domains` (Req 11.1-11.4, Req 5): calls
    `_lookup_domains(..., listing_type="new")`, then runs the same thumbnail
    (`_fetch_og_image`) and price (`_fetch_listing_price`) enrichment passes
    as v1, unchanged — these are independent of the per-domain restructuring
    and stay exactly as they are today.

    Relevance filtering (Part A, Req 5.3) runs on `_lookup_domains`'s result
    before either enrichment pass, via `filter_category`, so enrichment work
    is never spent on a candidate filtering would go on to discard.

    Never raises: `_lookup_domains` already never raises (Req 14), and both
    enrichment passes below are guarded on their own so neither can turn an
    already-successful text/price/url result into a failure just because
    enrichment is slow or fails outright — worst case, listings are returned
    with `thumbnail_url=None`/`price=None`.
    """
    listings, ok, raw_pool = await _lookup_domains(
        name, brand, retailer_domains, listing_type="new", on_stage=on_stage
    )

    # Req 5.3: relevance filtering (Part A) completes before enrichment runs,
    # so enrichment is never spent on a candidate filtering would discard.
    listings = await filter_category(
        name,
        brand,
        listings,
        raw_pool,
        settings.product_max_listings_per_source,
        on_stage=on_stage,
    )

    query = f"{brand} {name}" if brand else name

    if listings:
        if on_stage is not None:
            on_stage("thumbnail_enrichment", "Fetching thumbnails")
        try:
            thumbnails = await asyncio.gather(
                *(_fetch_og_image(listing.listing_url) for listing in listings)
            )
            for listing, thumbnail_url in zip(listings, thumbnails):
                listing.thumbnail_url = thumbnail_url
        except Exception as exc:  # noqa: BLE001 - enrichment, must not raise
            logger.warning(
                "Retail thumbnail enrichment failed: query=%r error=%s",
                query,
                exc,
            )

        # Same best-effort shape as the thumbnail step above, scoped to only
        # the listings whose snippet-based price came back empty (Req 11.6):
        # a real page fetch to try harder, but a failure here still can't
        # cost a listing its already-successful title/url data.
        listings_missing_price = [listing for listing in listings if listing.price is None]
        if listings_missing_price:
            if on_stage is not None:
                on_stage("price_enrichment", "Retrieving prices")
            try:
                prices = await asyncio.gather(
                    *(
                        _fetch_listing_price(listing.listing_url)
                        for listing in listings_missing_price
                    )
                )
                for listing, (price, currency) in zip(listings_missing_price, prices):
                    listing.price = price
                    listing.currency = currency
            except Exception as exc:  # noqa: BLE001 - enrichment, must not raise
                logger.warning(
                    "Retail price enrichment failed: query=%r error=%s",
                    query,
                    exc,
                )

    return listings, ok


async def _lookup_secondhand_marketplaces(
    name: str,
    brand: str | None,
    domains: tuple[str, ...],
    on_stage: "StageEmitter | None" = None,
) -> tuple[list[ProductListing], bool]:
    """Look up secondhand listings for `name`/`brand` across discovered,
    non-Vinted secondhand-marketplace domains (Req 3.3/3.4, 4.2, 9.3): calls
    `_lookup_domains(..., listing_type="used")`, then the same relevance
    filtering (Part A) `_lookup_retail` runs, via `filter_category`.
    Deliberately skips the retail lookup's thumbnail/price-page enrichment
    passes — Requirement 4.2 only asks for the domain-scoped search
    mechanism to be reused, not enrichment parity with retail; keeping this
    function to exactly the search-and-tag (+ filter) shape keeps its
    latency budget predictable and its scope tight. Revisitable in a future
    iteration if secondhand-marketplace listing quality turns out to need
    it."""
    listings, ok, raw_pool = await _lookup_domains(
        name, brand, domains, listing_type="used", on_stage=on_stage
    )
    listings = await filter_category(
        name,
        brand,
        listings,
        raw_pool,
        settings.product_max_listings_per_source,
        on_stage=on_stage,
    )
    return listings, ok


# ── Kleinanzeigen (German secondhand) lookup (Requirement 10) ───────────────

_KLEINANZEIGEN_BASE_URL = "https://www.kleinanzeigen.de"
_KLEINANZEIGEN_SEARCH_URL = f"{_KLEINANZEIGEN_BASE_URL}/s-suchanfrage.html"
# Kleinanzeigen doesn't publish a stable "browser-only" gate, but an empty/
# generic User-Agent gets served a reduced (bot) page in practice; a common
# desktop UA string avoids that without impersonating a specific real user.
_KLEINANZEIGEN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def _search_kleinanzeigen_sync(query: str, max_results: int) -> list[dict[str, str | None]]:
    """Blocking Kleinanzeigen search: GET the search results page and parse
    listing cards out of the HTML. Must be run off the event loop (see
    `_lookup_kleinanzeigen`).

    NOTE (accepted risk, see design.md/requirements.md Req 10): unlike
    `_lookup_secondhand` (Vinted, via `vinted-api-wrapper`) and `_lookup_retail`
    (Tavily/DuckDuckGo search clients), Kleinanzeigen has no structured search
    API available to this project, so this is plain HTML scraping. The
    `article.aditem` markup and its `.aditem-main--middle--price-shipping--price`
    price node were verified against a live response during implementation
    (2026-07-13), but marketplace HTML structure drifts over time without
    notice — if this stops returning results, re-inspect the live page first.

    The `?keywords=` query-string form of the search URL was verified to work
    (it 30x-redirects to Kleinanzeigen's canonical slug URL, e.g.
    `/s-<slug>/k0`, which `httpx` follows via `follow_redirects=True`); it's
    used here instead of hand-building the slug because it avoids having to
    replicate Kleinanzeigen's slugification rules (umlauts, punctuation,
    whitespace) ourselves.
    """
    with httpx.Client(
        follow_redirects=True,
        timeout=settings.product_lookup_timeout_seconds,
        headers=_KLEINANZEIGEN_HEADERS,
    ) as client:
        response = client.get(_KLEINANZEIGEN_SEARCH_URL, params={"keywords": query})
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    items: list[dict[str, str | None]] = []
    for article in soup.select("article.aditem")[:max_results]:
        title_el = article.select_one("h2.text-module-begin a")
        price_el = article.select_one(".aditem-main--middle--price-shipping--price")
        image_el = article.select_one(".aditem-image img")

        href = article.get("data-href") or (title_el.get("href") if title_el else None)
        listing_url = (
            href if href and href.startswith("http") else f"{_KLEINANZEIGEN_BASE_URL}{href}"
        ) if href else None

        items.append(
            {
                "title": title_el.get_text(strip=True) if title_el else "",
                "price_text": price_el.get_text(strip=True) if price_el else None,
                "thumbnail_url": image_el.get("src") if image_el else None,
                "listing_url": listing_url,
            }
        )

    if not items:
        # No `article.aditem` nodes matched. This is ambiguous — it could be a
        # genuinely empty search result, or it could mean Kleinanzeigen's
        # markup has drifted (or we got served an empty/bot-gated response
        # body) and the selectors above no longer match anything. Since this
        # is unstructured HTML scraping (see NOTE above) with no way to tell
        # those cases apart, we conservatively treat "zero matches" as a
        # probable scrape failure rather than a confident empty result, so
        # `_lookup_kleinanzeigen` reports `ok=False` and callers know this
        # source's absence shouldn't be read as "no secondhand listings
        # exist".
        raise ValueError("no Kleinanzeigen listing items parsed from response")
    return items


async def _lookup_kleinanzeigen(
    name: str, brand: str | None
) -> tuple[list[ProductListing], bool]:
    """Look up secondhand listings for `name`/`brand` on Kleinanzeigen
    (Req 10.4-10.6, Req 8.1: "using the existing... bespoke HTML-scraping
    integration... unchanged").

    Germany-only in practice, but that gate lives in the `/find` endpoint
    (Task 11), gated purely on `_is_germany(location)` and independent of
    discovery entirely — this function assumes it's only ever invoked when
    appropriate and no longer takes a `market` parameter at all (it was only
    ever used for a log field, same "not attempted, no network call" shape
    as v1's market-code gate, Req 9.4).

    Runs the blocking `httpx` GET + HTML parse in a thread and bounds it with
    `settings.product_lookup_timeout_seconds` (Req 12). Never raises: any
    failure (timeout, HTTP error, or parse error) is logged and surfaced as
    `([], False)` so the caller can still return partial results from other
    sources (Req 14).
    """
    query = f"{brand} {name}" if brand else name
    max_results = settings.product_max_listings_per_source

    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(_search_kleinanzeigen_sync, query, max_results),
            timeout=settings.product_lookup_timeout_seconds,
        )
        # Result processing is inside this same try block, not just the
        # network call/parse step — a malformed item shape must degrade to
        # `([], False)` like any other failure rather than raise (Req 14).
        # See the equivalent Vinted incident note above.
        listings: list[ProductListing] = []
        for item in items:
            price_text = item.get("price_text")
            # Plain "VB" (Verhandlungsbasis / negotiable) has no numeric price;
            # _extract_price() returns (None, None) for it, which is the correct
            # ProductListing.price for that case. "35 € VB" still extracts 35.0.
            # Currency is always EUR here (Kleinanzeigen is a German-only site)
            # regardless of whether a numeric price was found.
            price, _ = _extract_price(price_text) if price_text else (None, None)
            listings.append(
                ProductListing(
                    type="used",
                    title=item.get("title") or "",
                    price=price,
                    currency="EUR",
                    source="Kleinanzeigen",
                    thumbnail_url=item.get("thumbnail_url"),
                    listing_url=item.get("listing_url") or "",
                )
            )
    except asyncio.TimeoutError:
        logger.error(
            "Kleinanzeigen lookup timed out: source=kleinanzeigen query=%r",
            query,
        )
        return [], False
    except Exception as exc:  # noqa: BLE001 - external site, must not raise
        logger.error(
            "Kleinanzeigen lookup failed: source=kleinanzeigen query=%r error=%s",
            query,
            exc,
        )
        return [], False

    return listings, True


# ── The `/find` endpoint (Requirement 9) ────────────────────────────────────


def _unwrap_lookup_result(
    result: tuple[list[ProductListing], bool] | BaseException,
    source: str,
) -> tuple[list[ProductListing], bool]:
    """Normalize one `asyncio.gather(..., return_exceptions=True)` slot.

    `_lookup_secondhand`/`_lookup_retail`/`_lookup_kleinanzeigen` are already
    documented to never raise (Req 12, 14) — `return_exceptions=True` is
    belt-and-suspenders in case that contract is ever violated, so an
    unexpected exception degrades to `([], False)` for that source instead of
    failing the whole request.
    """
    if isinstance(result, BaseException):
        logger.error("Product lookup raised unexpectedly: source=%s error=%s", source, result)
        return [], False
    return result


def _log_listings(
    listings: list[ProductListing], name: str, brand: str | None, location_key: str
) -> None:
    """Logs each returned listing at INFO level (title/source/price/url), so
    result quality can be inspected from the backend terminal without a
    debugger — e.g. spotting a listing that's off-topic for the query, or a
    retailer whose price never comes through (see `_extract_price()`'s
    docstring: price comes from the search result's title/snippet text, not
    the listing page itself, so it's inherently hit-or-miss per result, not
    per source)."""
    for listing in listings:
        logger.info(
            "Product find listing: query=%r brand=%r location=%s | type=%s source=%s "
            "price=%s currency=%s title=%r url=%s",
            name,
            brand,
            location_key,
            listing.type,
            listing.source,
            listing.price,
            listing.currency,
            listing.title,
            listing.listing_url,
        )


def _rank_listing(
    listing: ProductListing, name: str, brand: str | None
) -> tuple[bool, bool, bool, bool, float]:
    """Scores one listing for the final response ordering — most relevant
    and complete on top, cheapest of otherwise-tied listings first. Each of
    the first four components is a boolean where `True` ranks higher, and
    the tuple's field order is itself the tie-break priority: name match
    first, then brand match, then thumbnail presence, then price presence
    (relevance outranks completeness, per the ordering the two criteria
    were requested in). The fifth component only ever discriminates between
    listings that are already tied on all four booleans (in particular,
    both `has_price=True`, since a listing without a price can't be
    meaningfully compared on this axis at all) — verified live: two
    same-brand listings with identical relevance/completeness scores need a
    price-magnitude tiebreaker, or the cheaper one has no reason to sort
    ahead of the pricier one.

    "Exact" here means the query name/brand appears verbatim
    (case-insensitive) in the listing's title, not that the whole title
    equals the query — real listing titles are full retailer page titles
    (e.g. "Balea Toner Beauty Expert Refining, 100 ml ... | dm.de"), so a
    whole-string equality check would essentially never match anything;
    substring containment is what actually distinguishes an on-target
    listing from a tangential one. `brand` is optional on the query; when
    it wasn't given there's nothing to check against, so every listing gets
    the same (non-penalizing) value for that component rather than the
    sort being skewed by an absent signal.
    """
    title_lower = listing.title.lower()
    name_match = name.lower() in title_lower
    brand_match = brand is None or brand.lower() in title_lower
    has_thumbnail = listing.thumbnail_url is not None
    has_price = listing.price is not None
    # Negated so a *lower* price yields a *larger* key, ranking first under
    # this function's overall `reverse=True` sort (see
    # `_sort_by_relevance_and_completeness`) — the same trick used for the
    # boolean components, just for a continuous value. The placeholder for
    # a missing price is inert: `has_price` (already earlier in the tuple)
    # separates priced from unpriced listings before this component is ever
    # reached for a comparison between them.
    price_rank = -listing.price if listing.price is not None else 0.0
    return (name_match, brand_match, has_thumbnail, has_price, price_rank)


def _sort_by_relevance_and_completeness(
    listings: list[ProductListing], name: str, brand: str | None
) -> list[ProductListing]:
    """Orders the final combined listings so the most relevant and complete
    results surface first (see `_rank_listing`). Uses a stable sort, so
    listings tied on every ranked component keep their prior relative
    order — preserving the existing per-source ordering
    (`_diversify_by_source`'s round-robin interleave, and the
    vinted/secondhand-marketplace/retail/kleinanzeigen concatenation order)
    as the final tie-break rather than reshuffling ties arbitrarily.
    `sorted(..., reverse=True)` is documented to preserve stability in
    Python, not literally reverse the output, so this holds."""
    return sorted(listings, key=lambda listing: _rank_listing(listing, name, brand), reverse=True)


async def _resolve_product_find(
    name: str,
    brand: str | None,
    source: Literal["retail", "vinted", "kleinanzeigen"] | None,
    profile: UserProfile,
    cache_store: ProductCacheStore,
    discovery_store: SourceDiscoveryStore,
    on_stage: "StageEmitter | None" = None,
) -> ProductFindResponse:
    """Look up retail + secondhand listings for `name`/`brand` (Req 9) —
    today's `find_product()` body, extracted verbatim below the
    profile-fetch/auth step so both the non-streaming and streaming response
    paths (Req 6.1, 6.2) share exactly one copy of the cache-check/discovery/
    fan-out/cache-store logic.

    Normalizes the caller's profile `location` (Req 9.5, 6.3) and determines
    `is_germany` directly from it (Req 8.1, independent of discovery); serves
    a cached response when available (Req 13, keyed by normalized location +
    `source` rather than v1's `market.code`), and otherwise — for any
    `source` whose lookups actually depend on discovered domains
    (`None`/`retail`/`vinted`, Req 12.3) — awaits `get_or_discover_sources()`
    before constructing any lookup coroutine, then runs the attempted
    Vinted, secondhand-marketplace, retail, and (Germany-only, Req 8.1)
    Kleinanzeigen lookups concurrently (Req 12). Always returns a response —
    per-source outcomes are signalled via `retail_ok`/`secondhand_ok`, not an
    exception (Req 14) — the cache check (the very first thing this function
    does) is also what makes a cache-hit stream (Req 12) emit zero stage
    events: `on_stage` is never called before returning in that case.

    Optional `source` restricts the request to a single source instead of
    running every attempted one — added so the frontend can fire one request
    per source in parallel and render each as its own result arrives, rather
    than the whole popover waiting on the slowest source (see
    `ProductFinderPopover.tsx`). Omitting it preserves the original
    combined-response behavior (still used by anything that wants one
    request for everything). A `source="kleinanzeigen"` request skips
    discovery entirely (Req 12.3's rationale: Kleinanzeigen never depends on
    discovered domains) and short-circuits to an empty/`ok=False` result with
    no network call at all on a non-Germany location, exactly like v1 already
    treated Kleinanzeigen for non-DE markets (Req 9.9/10.8's `secondhand_ok`
    semantics are unaffected by whether sources ran in one request or
    three).

    `on_stage` (Req 7), when given, is threaded into `get_or_discover_sources`
    and into whichever of `_lookup_retail`/`_lookup_secondhand_marketplaces`
    are attempted — `_lookup_secondhand` (Vinted) and `_lookup_kleinanzeigen`
    are called exactly as they are today, with no `on_stage` argument at all
    (neither has any stage event of its own, Req 7.1/7.2).
    """
    normalized_location = _normalize_location(profile.location)
    is_germany = _is_germany(normalized_location)

    # `source` is folded into the cache key's location slot so per-source and
    # combined-response cache entries never collide in the shared table.
    cache_location_key = f"{normalized_location or 'unknown'}:{source or 'all'}"
    cache_key = ProductCacheStore.make_key(name, brand, cache_location_key)

    cached = cache_store.get(cache_key)
    if cached is not None:
        logger.info(
            "Product find cache hit: query=%r brand=%r location=%s source=%s",
            name,
            brand,
            normalized_location or "unknown",
            source or "all",
        )
        _log_listings(cached.listings, name, brand, normalized_location or "unknown")
        return cached

    # Discovery only runs for requests whose lookups actually depend on its
    # output (Req 12.3) — a `source="kleinanzeigen"` request never runs a
    # retail/Vinted/secondhand-marketplace lookup at all, so spending
    # discovery's latency on it would only delay that one card for no
    # benefit (see design.md "Skipping discovery for source=kleinanzeigen").
    if source in (None, "retail", "vinted"):
        discovered = await get_or_discover_sources(profile.location, discovery_store, on_stage)
    else:
        discovered = DiscoveredSources()

    attempt_vinted = source in (None, "vinted") and discovered.vinted_domain is not None
    attempt_secondhand_marketplaces = source in (None, "vinted") and bool(
        discovered.secondhand_domains
    )
    attempt_retail = source in (None, "retail") and bool(discovered.retailer_domains)
    attempt_kleinanzeigen = source in (None, "kleinanzeigen") and is_germany

    lookups: list[tuple[str, asyncio.Future]] = []
    if attempt_vinted:
        lookups.append(("vinted", _lookup_secondhand(name, brand, discovered.vinted_domain)))
    if attempt_secondhand_marketplaces:
        lookups.append(
            (
                "secondhand_marketplaces",
                _lookup_secondhand_marketplaces(
                    name, brand, discovered.secondhand_domains, on_stage=on_stage
                ),
            )
        )
    if attempt_retail:
        lookups.append(
            (
                "retail",
                _lookup_retail(name, brand, discovered.retailer_domains, on_stage=on_stage),
            )
        )
    if attempt_kleinanzeigen:
        lookups.append(("kleinanzeigen", _lookup_kleinanzeigen(name, brand)))

    # See _unwrap_lookup_result()'s docstring for why return_exceptions=True
    # is used defensively even though the lookups are documented not to raise.
    results = await asyncio.gather(*(coro for _, coro in lookups), return_exceptions=True)
    outcomes = {
        lookup_name: _unwrap_lookup_result(result, lookup_name)
        for (lookup_name, _), result in zip(lookups, results)
    }

    vinted_listings, vinted_ok = outcomes.get("vinted", ([], False))
    secondhand_marketplace_listings, secondhand_marketplace_ok = outcomes.get(
        "secondhand_marketplaces", ([], False)
    )
    retail_listings, retail_ok = outcomes.get("retail", ([], False))
    kleinanzeigen_listings, kleinanzeigen_ok = outcomes.get("kleinanzeigen", ([], False))

    listings = (
        vinted_listings + secondhand_marketplace_listings + retail_listings + kleinanzeigen_listings
    )
    listings = _sort_by_relevance_and_completeness(listings, name, brand)
    # True if any secondhand sub-source succeeded (Req 3.5, 7.5, 9.3, 10.8's
    # OR-across-sub-sources pattern, now with a third sub-source folded in
    # the same way the second one was in v1); each is False by construction
    # when not attempted, so this collapses correctly for every `source`
    # value without a separate branch per case.
    secondhand_ok = vinted_ok or secondhand_marketplace_ok or kleinanzeigen_ok

    response = ProductFindResponse(
        listings=listings,
        retail_ok=retail_ok,
        secondhand_ok=secondhand_ok,
    )

    logger.info(
        "Product find miss: query=%r brand=%r location=%s source=%s retail_ok=%s "
        "secondhand_ok=%s (vinted_ok=%s secondhand_marketplace_ok=%s "
        "kleinanzeigen_attempted=%s kleinanzeigen_ok=%s) listings=%d",
        name,
        brand,
        normalized_location or "unknown",
        source or "all",
        retail_ok,
        secondhand_ok,
        vinted_ok,
        secondhand_marketplace_ok,
        attempt_kleinanzeigen,
        kleinanzeigen_ok,
        len(listings),
    )
    _log_listings(listings, name, brand, normalized_location or "unknown")

    # Req 14: a total failure (every attempted source down) must not be
    # cached, so a transient outage doesn't get frozen into the cache for the
    # full TTL — a legitimate all-empty-but-successful search is still cached.
    if retail_ok or secondhand_ok:
        cache_store.set(
            cache_key, response, name=name, brand=brand, market_code=cache_location_key
        )
    else:
        logger.warning(
            "Product find total failure, not caching: query=%r brand=%r location=%s source=%s",
            name,
            brand,
            normalized_location or "unknown",
            source or "all",
        )

    return response


class QueuedStageEmitter:
    """Queue-backed `StageEmitter` (Req 7), constructed once per streaming
    request. `.emit` is the synchronous callback threaded into
    `_resolve_product_find` as `on_stage`; `.queue` is drained by
    `event_stream()` below. Not exported/imported by
    `product_source_discovery.py` or `relevance_filter.py` — those only ever
    receive the plain `StageEmitter` callable, never construct one, so this
    class lives here, colocated with the one place it's used."""

    def __init__(self) -> None:
        self.queue: "asyncio.Queue[ProductFindStageEvent]" = asyncio.Queue()

    def emit(self, stage: str, message: str) -> None:
        # put_nowait, not put/await: called from inside coroutines running
        # concurrently under asyncio.gather (Req 7.4) — must never block or
        # yield control, or it would reintroduce exactly the serialization
        # Non-Functional Consideration 2 forbids. asyncio.Queue has no
        # capacity bound here, so put_nowait never raises QueueFull; a single
        # product lookup emits at most on the order of ten events.
        self.queue.put_nowait(ProductFindStageEvent(stage=stage, message=message))


def _sse(event: "ProductFindStageEvent | ProductFindResultEvent") -> str:
    """Same `data: {json}\\n\\n` framing as `backend/agent/graph.py`'s `_sse`
    helper (Requirements Review Note point 2), specialized to this feature's
    two Pydantic event types via `.model_dump_json()` instead of
    `json.dumps(dict)`."""
    return f"data: {event.model_dump_json()}\n\n"


@router.get("/find", response_model=ProductFindResponse)
async def find_product(
    name: str,
    brand: str | None = None,
    source: Literal["retail", "vinted", "kleinanzeigen"] | None = None,
    stream: bool = False,
    user_id: str = Depends(get_current_user),
    profile_store: ProfileStore = Depends(get_profile_store),
    cache_store: ProductCacheStore = Depends(get_product_cache_store),
    discovery_store: SourceDiscoveryStore = Depends(get_source_discovery_store),
):
    """`GET /api/products/find` (Req 9). Auth-gated (Req 9.1, 6.5) —
    `get_current_user` runs once, before either response path below, exactly
    as it does today.

    When `stream=False` (default), calls `_resolve_product_find(...)` and
    returns its result exactly as before this feature (Req 6.2, unchanged
    JSON contract and existing test coverage).

    When `stream=True`, returns a `text/event-stream` `StreamingResponse`
    (Req 6.1) mirroring `backend/api/chat.py`'s existing streaming headers:
    `_resolve_product_find(..., on_stage=emitter.emit)` runs as a background
    `asyncio.Task` while `event_stream()` races the emitter's queue against
    the task's completion, yielding each stage event (Req 7) as it arrives,
    then the terminal `result` event (Req 6.4, 8) followed by `[DONE]`. An
    unexpected exception escaping `_resolve_product_find` ends the stream
    with `[DONE]` and no `result` frame (Req 11.2/11.3) rather than
    propagating as an HTTP error, since the response has already started
    streaming by that point.
    """
    try:
        profile = profile_store.get_profile(user_id)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not stream:
        return await _resolve_product_find(
            name, brand, source, profile, cache_store, discovery_store
        )

    async def event_stream() -> AsyncIterator[str]:
        emitter = QueuedStageEmitter()
        task = asyncio.create_task(
            _resolve_product_find(
                name, brand, source, profile, cache_store, discovery_store, on_stage=emitter.emit
            )
        )
        try:
            while True:
                get_event = asyncio.ensure_future(emitter.queue.get())
                done, _pending = await asyncio.wait(
                    {get_event, task}, return_when=asyncio.FIRST_COMPLETED
                )
                if get_event in done:
                    yield _sse(get_event.result())
                else:
                    get_event.cancel()
                if task in done:
                    break
            # `on_stage` is synchronous and only ever called from within
            # `task`'s own coroutine tree; once `task` is done, nothing can
            # enqueue another event, so one final non-blocking drain is
            # sufficient to pick up anything emitted between the last
            # `queue.get()` resolving and the task actually finishing (Req
            # 11.1's per-source outcome must still reach the terminal event
            # undelayed).
            while not emitter.queue.empty():
                yield _sse(emitter.queue.get_nowait())
            result = task.result()
        except Exception as exc:  # noqa: BLE001 - Req 11.2/11.3
            logger.error("Product find stream ended unexpectedly: query=%r error=%s", name, exc)
            yield "data: [DONE]\n\n"
            return
        finally:
            if not task.done():
                task.cancel()

        yield _sse(ProductFindResultEvent(result=result))
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
