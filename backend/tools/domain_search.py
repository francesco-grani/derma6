"""Single-domain web-search primitive (product-source-agent, Requirement 4, 5).

Extracted so it has exactly one owner shared by three call sites that all
need "search this one domain and tell me what came back": the retail lookup
(`backend/tools/product_finder.py`), the discovery-driven secondhand-
marketplace lookup (same module), and discovery's own domain-candidate
verification step (`backend/tools/product_source_discovery.py`).

`search_domain_sync()` is the single-domain generalization of product-finder
v1's `_search_retail_sync()`, which scoped one call to *all* of
`market.retailer_domains` at once — this module always scopes to exactly one
`domain` (Req 5.1 replaces that shared-query approach).
"""

import asyncio
import logging

from backend.config import settings

logger = logging.getLogger(__name__)


def search_domain_sync(query: str, domain: str, max_results: int) -> list[dict]:
    """Blocking single-domain search: Tavily (preferred, `include_domains=
    [domain]` — a single-element list) or DuckDuckGo (fallback, a single
    `site:domain` qualifier appended to `query`), reusing the client
    construction pattern from `product_finder.py`'s (now-removed)
    `_search_retail_sync()`, generalized to exactly one domain. Must run off
    the event loop (wrap in `asyncio.to_thread` — see `search_domain`
    below)."""
    if settings.tavily_api_key:
        from langchain_community.tools.tavily_search import TavilySearchResults

        tool = TavilySearchResults(
            max_results=max_results,
            tavily_api_key=settings.tavily_api_key,
            include_domains=[domain],
        )
        raw = tool.invoke(query)
        if not isinstance(raw, list):
            # LangChain's TavilySearchResults swallows API/HTTP errors (e.g. a
            # `432` quota-exceeded response) and returns them as a plain *string*
            # instead of raising. Returning `[]` here masqueraded that as an
            # empty-but-successful result set, so the retail lookup logged
            # `retail_ok=True, listings=0` and even cached the emptiness. Raise
            # instead, so `search_domain` logs the real error and reports
            # `ok=False` — the failure is now visible and not cached.
            raise RuntimeError(f"Tavily search returned a non-list result: {raw!r}")
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in raw
            if isinstance(item, dict)
        ]

    from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

    scoped_query = f"{query} site:{domain}"
    ddg = DuckDuckGoSearchAPIWrapper()
    raw = ddg.results(scoped_query, max_results, source="text")
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        }
        for item in raw
        if isinstance(item, dict)
    ]


async def search_domain(
    query: str, domain: str, max_results: int, timeout_seconds: float
) -> tuple[list[dict], bool]:
    """Async, never-raise, explicitly-timed wrapper around
    `search_domain_sync` — the same `(results, ok)` never-raise shape used
    throughout this codebase's source lookups. Callers supply their own
    `timeout_seconds` since the retail/secondhand-marketplace lookups (Req
    4.5, using `settings.product_lookup_timeout_seconds`) and discovery's
    verification probe (using a shorter/independent budget) have different
    timeout budgets despite sharing this same primitive."""
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(search_domain_sync, query, domain, max_results),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Domain search timed out: domain=%s query=%r",
            domain,
            query,
        )
        return [], False
    except Exception as exc:  # noqa: BLE001 - external API, must not raise
        logger.error(
            "Domain search failed: domain=%s query=%r error=%s",
            domain,
            query,
            exc,
        )
        return [], False

    return results, True
