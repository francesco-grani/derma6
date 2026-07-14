"""Source discovery: the discovery LLM call, candidate validation, and
candidate verification (product-source-agent, Requirements 1-3, 6.3, 8,
Non-Functional Consideration 3).

Task 5 (this task): the module's static data (known Vinted locales, the
Germany-seed fallback constants), the pure/near-pure helpers
(`_normalize_location`, `_is_germany`, `_validate_domain_candidate`), the
single-domain verification probe (`_verify_domain_relevance`), and the
discovery LLM call (`_discover_sources_llm`).

Task 6 (same module, later): the orchestration (`_discover_sources`,
`get_or_discover_sources`) that assembles these pieces into the single
cache-or-run entry point `find_product()` (backend/tools/product_finder.py)
calls.

`_normalize_location`/`_is_germany` are defined here rather than in
`product_finder.py` so that module can import them without creating a
circular import — see design.md's "Why `_normalize_location`/`_is_germany`
live in `product_source_discovery.py`, not `product_finder.py`."
"""

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from backend.config import settings
from backend.llm.structured import StructuredOutputError, structured_completion
from backend.schemas import DiscoveredSources, DiscoveredSourcesLLM
from backend.tools.domain_search import search_domain

if TYPE_CHECKING:
    from backend.db.source_discovery_store import SourceDiscoveryStore
    from backend.tools.stage_events import StageEmitter

logger = logging.getLogger(__name__)

# ── Known-good Vinted locales (Req 3.1, 3.2) ────────────────────────────────

# Vinted operates a small, essentially static set of country locales — unlike
# retailer/marketplace domains, there's no open-ended universe to web-search
# verify against, so an LLM-proposed locale is checked against this allowlist
# instead of a live probe (cheaper, deterministic, and avoids constructing a
# real vinted-api-wrapper client — which does a blocking Cloudflare-bypass
# call — just to validate a guess). A locale the LLM proposes that isn't in
# this set is discarded (Req 2.4's "silently discard" principle, applied to
# the Vinted category); a real Vinted locale absent from this list is a false
# negative that degrades gracefully to "no Vinted for this location" rather
# than a wrong result, consistent with Requirement 7's failure philosophy.
_KNOWN_VINTED_LOCALE_DOMAINS: frozenset[str] = frozenset({
    "vinted.de", "vinted.fr", "vinted.it", "vinted.es", "vinted.pt", "vinted.nl",
    "vinted.be", "vinted.lu", "vinted.at", "vinted.pl", "vinted.cz", "vinted.sk",
    "vinted.hu", "vinted.ro", "vinted.dk", "vinted.se", "vinted.fi", "vinted.lt",
    "vinted.lv", "vinted.co.uk", "vinted.ie", "vinted.com",  # vinted.com == US
})

# ── Germany seed data (Requirement 8) ───────────────────────────────────────

# Germany is the one location product-finder v1 already had hardcoded data
# for (previously `MARKET_CONFIGS["DE"]`). That data survives here — not in
# product_finder.py — as a narrow, literal fallback `get_or_discover_sources()`
# (Task 6) reaches for only when live discovery fails for Germany (Req
# 8.2/8.4). It lives in this module, alongside `_KNOWN_VINTED_LOCALE_DOMAINS`
# above (the same kind of static, discovery-adjacent data), because this is
# the only code that consumes it; `product_finder.py` imports just
# `_normalize_location` and `_is_germany` below for its own two uses.
_GERMANY_LOCATION_ALIASES: frozenset[str] = frozenset({"germany", "deutschland", "de", "german"})
_GERMANY_SEED_RETAILER_DOMAINS: tuple[str, ...] = (
    "dm.de", "rossmann.de", "douglas.de", "flaconi.de", "amazon.de",
)
_GERMANY_SEED_VINTED_DOMAIN: str = "vinted.de"


def _normalize_location(location: str | None) -> str:
    """Trim + case-fold (Req 6.3); `None`/blank normalizes to `""`. Used
    internally by `get_or_discover_sources()` (Task 6) to derive its cache
    key, and imported by `product_finder.py` to derive the product-listing
    cache key from the same normalized unit."""
    return (location or "").strip().lower()


def _is_germany(normalized_location: str) -> bool:
    """True iff `normalized_location` is one of Germany's known aliases.
    Used for exactly two things: deciding, inside `get_or_discover_sources()`
    (Task 6), whether a discovery failure should fall back to the
    Requirement 8.4 seed sources above; and — imported into
    `product_finder.py` — gating the Kleinanzeigen attempt (Req 8.1,
    independent of discovery entirely). Never used to substitute Germany's
    sources for a different, unrecognized location (Req 7.3, 8.5) — it only
    ever answers "is this request's own location Germany.\""""
    return normalized_location in _GERMANY_LOCATION_ALIASES


# ── Domain syntax validation (Req 2.4) ──────────────────────────────────────

_DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _validate_domain_candidate(raw: str) -> str | None:
    """Lowercase/strip `raw` and check it against `_DOMAIN_RE` — a bare
    `label.label...tld` domain, no scheme, no path, no query string, no
    whitespace. Rejects (returns `None` for) a full URL
    (`"https://dm.de/search"`), a search-engine redirect link
    (`"google.com/url?q=..."`), or free text (`"dm dot de"`) — all of these
    fail the regex because they contain a `/`, `?`, or whitespace character
    the pattern doesn't allow. Never raises (Req 2.4: "silently discard")."""
    try:
        candidate = raw.strip().lower()
    except AttributeError:
        return None
    return candidate if _DOMAIN_RE.match(candidate) else None


# ── Web-search verification (Non-Functional Consideration 3) ────────────────

_VERIFICATION_QUERY = "skincare beauty products"


async def _verify_domain_relevance(domain: str) -> bool:
    """Confirm a syntactically-valid candidate domain is a real, queryable
    site with skincare/beauty-relevant content, mitigating the risk of the
    LLM hallucinating a domain that doesn't exist or doesn't sell the right
    category of product. Runs one `domain_search.search_domain()` call
    scoped to just this domain, with a generic query ("skincare beauty
    products") rather than the specific product name being looked up —
    verification happens once per location (then cached), decoupled from any
    specific product query. Returns `True` iff at least one result comes
    back; never raises (any search failure — empty results or a raised
    exception — is treated as "could not verify," conservatively discarding
    the candidate rather than accepting an unverified one)."""
    try:
        results, ok = await search_domain(
            _VERIFICATION_QUERY,
            domain,
            1,
            timeout_seconds=settings.product_lookup_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - belt-and-suspenders; search_domain itself never raises
        logger.info("Domain verification raised for domain=%s: %s", domain, exc)
        return False
    return ok and bool(results)


# ── LLM call (Req 2, 3; Requirements Review Note point 2) ───────────────────

_client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)
# Module-level singleton, mirroring memory_extraction.py's client-construction
# pattern (AsyncOpenAI() performs no I/O at construction time, so this is
# safe regardless of whether discovery runs on the request path).


class DiscoveryUnavailable(Exception):
    """Raised by `_discover_sources()` (Task 6) for any condition
    Requirement 7.1 treats as a discovery failure: the LLM call/parse
    failing outright, or `location_recognized=False`. Caught by
    `get_or_discover_sources()` (Task 6), which converts it into the Req 7
    failure-handling path (log, don't cache, degrade to empty or — for
    Germany — the seed fallback)."""


_DISCOVERY_SYSTEM_PROMPT = (
    "You identify online shopping sources for skincare/beauty products for a given "
    "country.\n\n"
    "Given the country, identify:\n"
    "1. retailer_domains: 2-15 bare domains (no scheme, no path — e.g. \"dm.de\", not "
    "\"https://www.dm.de/\") of retailers that plausibly sell skincare/beauty products and "
    "operate in or ship to that country.\n"
    "2. vinted_locale_domain: the bare domain of the Vinted secondhand-marketplace locale "
    "that operates in that country (e.g. \"vinted.de\" for Germany), or null if Vinted does "
    "not operate a locale there.\n"
    "3. secondhand_marketplace_domains: 2-15 bare domains of OTHER (non-Vinted) secondhand or "
    "resale marketplaces relevant to that country.\n\n"
    "Only the first several entries of each list will actually be used, so ORDER both lists "
    "from most to least prominent/reliable for that country — put well-known, high-confidence "
    "sources first. Include a mix: both large, well-known general retailers/marketplaces "
    "(e.g. a dominant e-commerce marketplace operating in that country) AND well-known local "
    "or specialty retailers — do not omit a major, obviously-relevant retailer just to make "
    "room for niche ones; rank it by how prominent and reliable it is for that country, not "
    "by novelty.\n\n"
    "The input is expected to be a country. If it names a more specific place (e.g. a city), "
    "treat it as its country. Set location_recognized=false, and leave the other fields empty, "
    "if the given string does not resolve to a real country you can confidently name "
    "retailers/marketplaces for. Never guess or fall back to a different country."
)


async def _discover_sources_llm(location: str) -> DiscoveredSourcesLLM:
    """Calls `structured_completion()` (backend/llm/structured.py, reused
    unchanged) with `schema_model=DiscoveredSourcesLLM`,
    `model=settings.effective_source_discovery_model`. See
    `_DISCOVERY_SYSTEM_PROMPT` for the exact instructions given to the model.
    Wraps `structured_completion`'s `StructuredOutputError` in
    `DiscoveryUnavailable` (Req 7.1) rather than letting it propagate as-is,
    so `get_or_discover_sources()` (Task 6) has one exception type to catch
    for every discovery-failure condition."""
    try:
        result, _used_fallback = await structured_completion(
            _client,
            model=settings.effective_source_discovery_model,
            schema_model=DiscoveredSourcesLLM,
            system_prompt=_DISCOVERY_SYSTEM_PROMPT,
            user_content=location,
        )
    except StructuredOutputError as exc:
        raise DiscoveryUnavailable(
            f"Source discovery LLM call failed for location={location!r}: {exc}"
        ) from exc
    return result


# ── Orchestration (Req 2, 3, 4.4 negative constraint) ────────────────────────

# Raised from 4 to 10 (2026-07-14, live bug): a well-known, reliable retailer
# (amazon.de) was getting truncated purely because the discovery LLM happened
# to list it 6th out of 6 proposed that run — the cap was trimming from the
# end of an arbitrarily-ordered list, not by any actual quality signal. The
# system prompt now also explicitly asks the model to order both domain lists
# by prominence/reliability and to include well-known general retailers
# alongside specialty ones, so truncation (still needed — an unbounded fan-out
# of concurrent per-domain queries doesn't scale) is much less likely to drop
# an obviously-relevant source.
_MAX_DOMAINS_PER_CATEGORY = 10  # Req 2.2, 3.4


def _validate_and_dedupe_candidates(raw_candidates: list[str]) -> list[str]:
    """Syntax-validate every raw LLM candidate (`_validate_domain_candidate`)
    and drop duplicates, preserving the LLM's original proposal order (Req
    2.2/3.4's "keep the survivors in proposal order" applies to this
    pre-verification step too, so the later cap-at-`_MAX_DOMAINS_PER_CATEGORY`
    slice is meaningful)."""
    seen: set[str] = set()
    validated: list[str] = []
    for raw in raw_candidates:
        candidate = _validate_domain_candidate(raw)
        if candidate is not None and candidate not in seen:
            seen.add(candidate)
            validated.append(candidate)
    return validated


async def _verify_candidates(candidates: list[str]) -> list[str]:
    """Verify every syntactically-valid `candidates` domain concurrently
    (`asyncio.gather` over `_verify_domain_relevance`), returning only the
    survivors in their original order. An empty input short-circuits to an
    empty output without spending an `asyncio.gather` call on nothing."""
    if not candidates:
        return []
    verified = await asyncio.gather(*(_verify_domain_relevance(c) for c in candidates))
    return [candidate for candidate, ok in zip(candidates, verified) if ok]


async def _discover_sources(location: str) -> DiscoveredSources:
    """The full discovery run for one already-normalized `location` string.
    See the module docstring / design.md's `_discover_sources` section for
    the full step-by-step description. Never raises for a "found nothing" in
    any individual category — only `DiscoveryUnavailable` (unrecognized
    location, or an unexpected exception wrapped as belt-and-suspenders)
    constitutes "the discovery step failed" for Requirement 7's caching
    exemption."""
    try:
        llm_result = await _discover_sources_llm(location)
        if not llm_result.location_recognized:
            raise DiscoveryUnavailable(
                f"Source discovery could not recognize location={location!r}"
            )

        retailer_candidates = _validate_and_dedupe_candidates(llm_result.retailer_domains)
        secondhand_candidates = _validate_and_dedupe_candidates(
            llm_result.secondhand_marketplace_domains
        )

        # Retailer- and secondhand-candidate verification run concurrently
        # with each other (Req: "run concurrently with step 2's verification
        # batch"), each internally fanning out over its own candidates too.
        retailer_verified, secondhand_verified = await asyncio.gather(
            _verify_candidates(retailer_candidates),
            _verify_candidates(secondhand_candidates),
        )

        vinted_domain: str | None = None
        if llm_result.vinted_locale_domain is not None:
            validated_vinted = _validate_domain_candidate(llm_result.vinted_locale_domain)
            if validated_vinted is not None and validated_vinted in _KNOWN_VINTED_LOCALE_DOMAINS:
                vinted_domain = validated_vinted

        return DiscoveredSources(
            retailer_domains=tuple(retailer_verified[:_MAX_DOMAINS_PER_CATEGORY]),
            vinted_domain=vinted_domain,
            secondhand_domains=tuple(secondhand_verified[:_MAX_DOMAINS_PER_CATEGORY]),
        )
    except DiscoveryUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - belt-and-suspenders, Req 7.1
        logger.error("Source discovery run failed unexpectedly for location=%r: %s", location, exc)
        raise DiscoveryUnavailable(
            f"Source discovery run failed unexpectedly for location={location!r}: {exc}"
        ) from exc


def _germany_seed_sources() -> DiscoveredSources:
    """Requirement 8.2/8.4's literal Germany fallback — never cached, see
    `get_or_discover_sources()`'s docstring for why."""
    return DiscoveredSources(
        retailer_domains=_GERMANY_SEED_RETAILER_DOMAINS,
        vinted_domain=_GERMANY_SEED_VINTED_DOMAIN,
        secondhand_domains=(),
    )


async def get_or_discover_sources(
    location: str | None,
    store: "SourceDiscoveryStore",
    on_stage: "StageEmitter | None" = None,
) -> DiscoveredSources:
    """The single function `find_product()` calls (Req 6, 7, 8, 11, 12). See
    the module docstring / design.md's `get_or_discover_sources` section for
    the full cache-or-run, failure-handling, and Germany-fallback behavior.

    `on_stage` (Req 7.1, Task 3's `StageEmitter`), if given, is called with
    `("discovery", ...)` exactly once, immediately before the underlying
    `_discover_sources(...)` call — and only on a discovery cache miss, never
    on a cache hit."""
    normalized = _normalize_location(location)
    if not normalized:
        logger.info("Source discovery skipped: no location set (raw location=%r)", location)
        return DiscoveredSources()

    cached = store.get(normalized)
    if cached is not None:
        logger.info("Source discovery cache hit: location=%r", normalized)
        return cached

    if on_stage is not None:
        on_stage("discovery", f"Assessing retailers for {location}")

    try:
        result = await asyncio.wait_for(
            _discover_sources(normalized), timeout=settings.source_discovery_timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Source discovery timed out after %ss: location=%r",
            settings.source_discovery_timeout_seconds,
            normalized,
        )
    except DiscoveryUnavailable as exc:
        logger.warning("Source discovery failed: location=%r error=%s", normalized, exc)
    except Exception as exc:  # noqa: BLE001 - belt-and-suspenders, mirrors _discover_sources
        logger.error(
            "Source discovery failed unexpectedly: location=%r error=%s", normalized, exc
        )
    else:
        logger.info(
            "Source discovery succeeded: location=%r retailer_domains=%s vinted_domain=%s "
            "secondhand_domains=%s",
            normalized,
            result.retailer_domains,
            result.vinted_domain,
            result.secondhand_domains,
        )
        store.set(normalized, location or "", result)
        return result

    # Every failure path above falls through to here (Req 7.1/7.2/12.2): log
    # already emitted above, and neither branch below caches its result.
    if _is_germany(normalized):
        logger.info("Source discovery falling back to Germany seed sources: location=%r", normalized)
        return _germany_seed_sources()

    logger.info("Source discovery falling back to empty sources: location=%r", normalized)
    return DiscoveredSources()
