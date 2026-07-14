"""LangGraph Studio shadow graph for the product finder pipeline
(product-finder-studio-graph).

Exists ONLY for LangGraph Studio visualization/debugging of
backend/tools/product_finder.py's stages (cache check, agentic source
discovery, the up-to-four-way source-lookup fan-out, and response
assembly) — it is not imported by backend/main.py and is not on any
request path the FastAPI app serves. Rebuilt inline here, compiled with
checkpointer=False, mirroring backend/agent/studio.py's existing pattern
for derma6_agent/rag_pipeline.

Every node below calls a real, unmodified function from
backend.tools.product_finder or backend.tools.product_source_discovery
(imported, never reimplemented) — see each node's docstring for the exact
function and the _resolve_product_find() line it mirrors.

COST WARNING: invoking this graph makes the same real LLM calls (source
discovery, on a discovery cache miss), the same real Vinted/Kleinanzeigen/
web-search requests, and the same real thumbnail/price enrichment fetches
an equivalent live GET /api/products/find request would make. There is no
mock or replay mode.

SHARED-CACHE WARNING: the cache_check and combine nodes read from and
write to the exact same on-disk ProductCacheStore/SourceDiscoveryStore
production reads from and writes to (settings.product_cache_db_path,
settings.source_discovery_db_path) — a Studio run here can be served a
cached result a real user request populated, and can populate a cache
entry a later real request is served from. This is a deliberate,
signed-off characteristic of this feature (requirements.md Requirements
Review Note point 3), not a bug.
"""

from typing import Literal

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from backend.db.deps import get_product_cache_store, get_source_discovery_store
from backend.db.product_cache_store import ProductCacheStore
from backend.schemas import DiscoveredSources, ProductFindResponse, ProductListing
from backend.tools.product_finder import (
    _lookup_kleinanzeigen,
    _lookup_retail,
    _lookup_secondhand,
    _lookup_secondhand_marketplaces,
    _sort_by_relevance_and_completeness,
)
from backend.tools.product_source_discovery import (
    _is_germany,
    _normalize_location,
    get_or_discover_sources,
)

# Same "constructed the same way backend/agent/studio.py constructs its own
# reused stores" pattern backend/agent/graph.py already establishes
# (`_store = get_profile_store()`) — Requirement 7.1.
_cache_store: ProductCacheStore = get_product_cache_store()
_discovery_store = get_source_discovery_store()


# ── State (Requirement 3) ────────────────────────────────────────────────────


class ProductFinderStudioState(BaseModel):
    """Studio-editable input (Requirement 3.1) plus every intermediate value
    a node writes, so Studio's per-node view shows each stage's actual
    output (Requirement 9.2). A Pydantic model, not a TypedDict — the
    default values below are what make a no-edit Studio invocation runnable
    (Requirement 3.2) on a *per-invocation* basis (Requirement 3.3), unlike
    backend/agent/studio.py's `_profile`, which is a module-level constant
    fixed at import time because the chat agent's persona isn't the axis
    being debugged there. Here it is, so the defaults live on the state
    schema itself, re-applied fresh for every run.
    """

    # ── Input (Requirement 3.1) ──────────────────────────────────────────
    name: str = "Balea Toner"
    brand: str | None = None
    location: str = "Germany"
    source: Literal["retail", "vinted", "kleinanzeigen"] | None = None

    # ── Written by cache_check (Requirement 4.1) ─────────────────────────
    normalized_location: str = ""
    is_germany: bool = False
    cache_key: str = ""

    # ── Written by discovery (Requirement 4.2) ───────────────────────────
    discovered: DiscoveredSources = Field(default_factory=DiscoveredSources)

    # ── Written by the four lookup nodes (Requirement 4.3) ───────────────
    vinted_listings: list[ProductListing] = Field(default_factory=list)
    vinted_ok: bool = False
    secondhand_marketplace_listings: list[ProductListing] = Field(default_factory=list)
    secondhand_marketplace_ok: bool = False
    retail_listings: list[ProductListing] = Field(default_factory=list)
    retail_ok: bool = False
    kleinanzeigen_listings: list[ProductListing] = Field(default_factory=list)
    kleinanzeigen_ok: bool = False

    # ── Written by combine (Requirement 4.5, 9) ──────────────────────────
    response: ProductFindResponse | None = None


# ── Nodes (Requirement 4, 5, 10, 11) ─────────────────────────────────────────


async def _cache_check_node(state: ProductFinderStudioState) -> dict:
    """Node 1 (Requirement 4.1). Mirrors _resolve_product_find()'s cache
    check verbatim: same key derivation
    (`f"{normalized_location or 'unknown'}:{source or 'all'}"` ->
    `ProductCacheStore.make_key(name, brand, ...)`) against the same store
    instance production uses (`_cache_store`, Requirement 7.1). A cache hit
    writes the cached ProductFindResponse straight into `state.response` —
    `_route_after_cache_check` (below) is what actually ends the run on a
    hit; this node only computes values, it never branches itself."""
    normalized_location = _normalize_location(state.location)
    is_germany = _is_germany(normalized_location)
    cache_location_key = f"{normalized_location or 'unknown'}:{state.source or 'all'}"
    cache_key = ProductCacheStore.make_key(state.name, state.brand, cache_location_key)

    updates: dict = {
        "normalized_location": normalized_location,
        "is_germany": is_germany,
        "cache_key": cache_key,
    }
    cached = _cache_store.get(cache_key)
    if cached is not None:
        updates["response"] = cached
    return updates


async def _discovery_node(state: ProductFinderStudioState) -> dict:
    """Node 2 (Requirement 4.2). Calls get_or_discover_sources() verbatim
    (Requirement 5.1) against the same `_discovery_store` production uses
    (Requirement 7.1). `on_stage` is omitted — defaults to None
    (Requirement 10.1); Studio's own per-node execution view is this
    graph's progress-visibility mechanism (Requirement 10.2), not the SSE
    stage-event stream _resolve_product_find()'s streaming path threads
    through this same function. Only reached when `_route_after_cache_check`
    determined `source in (None, "retail", "vinted")` (Requirement 4.4)."""
    discovered = await get_or_discover_sources(state.location, _discovery_store)
    return {"discovered": discovered}


async def _lookup_vinted_node(state: ProductFinderStudioState) -> dict:
    """Node 3 — calls _lookup_secondhand() (the Vinted lookup) verbatim.
    Only scheduled when `_route_lookups` determined
    `discovered.vinted_domain is not None`, so `state.discovered.vinted_domain`
    is guaranteed non-None here; `_lookup_secondhand` takes a non-optional
    `str`, hence the assert below rather than a silent Optional pass-through."""
    vinted_domain = state.discovered.vinted_domain
    assert vinted_domain is not None, "lookup_vinted scheduled without a discovered vinted_domain"
    listings, ok = await _lookup_secondhand(state.name, state.brand, vinted_domain)
    return {"vinted_listings": listings, "vinted_ok": ok}


async def _lookup_secondhand_marketplaces_node(state: ProductFinderStudioState) -> dict:
    """Node 4 — calls _lookup_secondhand_marketplaces() verbatim, `on_stage`
    omitted (Requirement 10.1). Only scheduled when
    `discovered.secondhand_domains` is non-empty."""
    listings, ok = await _lookup_secondhand_marketplaces(
        state.name, state.brand, state.discovered.secondhand_domains
    )
    return {"secondhand_marketplace_listings": listings, "secondhand_marketplace_ok": ok}


async def _lookup_retail_node(state: ProductFinderStudioState) -> dict:
    """Node 5 — calls _lookup_retail() verbatim, `on_stage` omitted
    (Requirement 10.1). Only scheduled when `discovered.retailer_domains`
    is non-empty."""
    listings, ok = await _lookup_retail(state.name, state.brand, state.discovered.retailer_domains)
    return {"retail_listings": listings, "retail_ok": ok}


async def _lookup_kleinanzeigen_node(state: ProductFinderStudioState) -> dict:
    """Node 6 — calls _lookup_kleinanzeigen() verbatim. Only scheduled when
    `state.is_germany` is True and `source in (None, "kleinanzeigen")`."""
    listings, ok = await _lookup_kleinanzeigen(state.name, state.brand)
    return {"kleinanzeigen_listings": listings, "kleinanzeigen_ok": ok}


async def _combine_node(state: ProductFinderStudioState) -> dict:
    """Node 7 (Requirement 4.5, 9). Mirrors _resolve_product_find()'s
    combine/sort/cache-write step verbatim: concatenation in
    vinted/secondhand-marketplaces/retail/kleinanzeigen order,
    _sort_by_relevance_and_completeness() (Requirement 5.1, imported
    unchanged), secondhand_ok = vinted_ok or secondhand_marketplace_ok or
    kleinanzeigen_ok (Requirement 9.1), and the same "don't cache a total
    failure" rule (Requirement 7.2) against `_cache_store` (Requirement
    7.1). Reached only after every lookup node scheduled for this
    invocation has completed — LangGraph's superstep barrier is this
    graph's equivalent of asyncio.gather (Requirement 4.5, 8.1)."""
    listings = (
        state.vinted_listings
        + state.secondhand_marketplace_listings
        + state.retail_listings
        + state.kleinanzeigen_listings
    )
    listings = _sort_by_relevance_and_completeness(listings, state.name, state.brand)
    secondhand_ok = state.vinted_ok or state.secondhand_marketplace_ok or state.kleinanzeigen_ok

    response = ProductFindResponse(
        listings=listings, retail_ok=state.retail_ok, secondhand_ok=secondhand_ok
    )

    if state.retail_ok or secondhand_ok:
        cache_location_key = f"{state.normalized_location or 'unknown'}:{state.source or 'all'}"
        _cache_store.set(
            state.cache_key,
            response,
            name=state.name,
            brand=state.brand,
            market_code=cache_location_key,
        )

    return {"response": response}


# Every node body above calls exactly one reused function and returns its
# result — Requirement 11.1's "no additional try/except suppression" is true
# by construction, since there is no `try` anywhere in this list. If any
# reused function's own never-raise contract is ever violated by a real
# defect, the exception propagates straight out of the node coroutine, which
# is exactly the "let it fail visibly" behavior Requirement 11.2 asks for.


# ── Routing (Requirement 4.4, 5.2, 8) ────────────────────────────────────────


def _route_lookups(state: ProductFinderStudioState) -> list[str] | str:
    """Shared by both routing points that precede the lookup fan-out —
    reached either directly from cache_check (source="kleinanzeigen",
    discovery skipped) or from discovery (every other source) — mirrors
    _resolve_product_find()'s four `attempt_*` booleans exactly, not a
    re-derived equivalent (Requirement 5.2):

        attempt_vinted = source in (None, "vinted") and discovered.vinted_domain is not None
        attempt_secondhand_marketplaces = source in (None, "vinted") and bool(discovered.secondhand_domains)
        attempt_retail = source in (None, "retail") and bool(discovered.retailer_domains)
        attempt_kleinanzeigen = source in (None, "kleinanzeigen") and is_germany

    Returns the list of node names to fan out into in parallel (Requirement
    8.1) — LangGraph schedules every returned node name in the same
    superstep; `combine`'s edges from all four lookup nodes make it wait
    for exactly the ones actually scheduled this run (Requirement 4.5,
    8.2), the graph equivalent of asyncio.gather's lack of an ordering
    dependency among the four lookups. An empty list (nothing attempted —
    e.g. source="kleinanzeigen" on a non-Germany location) routes directly
    to "combine" rather than dead-ending the run."""
    attempt_vinted = state.source in (None, "vinted") and state.discovered.vinted_domain is not None
    attempt_secondhand_marketplaces = state.source in (None, "vinted") and bool(
        state.discovered.secondhand_domains
    )
    attempt_retail = state.source in (None, "retail") and bool(state.discovered.retailer_domains)
    attempt_kleinanzeigen = state.source in (None, "kleinanzeigen") and state.is_germany

    targets: list[str] = []
    if attempt_vinted:
        targets.append("lookup_vinted")
    if attempt_secondhand_marketplaces:
        targets.append("lookup_secondhand_marketplaces")
    if attempt_retail:
        targets.append("lookup_retail")
    if attempt_kleinanzeigen:
        targets.append("lookup_kleinanzeigen")
    return targets or "combine"


def _route_after_cache_check(state: ProductFinderStudioState) -> str | list[str]:
    """Mirrors _resolve_product_find()'s cache-check short-circuit
    (Requirement 4.1) and its `if source in (None, "retail", "vinted")`
    discovery gate (Requirement 4.4, 5.2) — the identical condition, not a
    re-derived one. `_cache_check_node` has already written the cached
    response into `state.response` on a hit; this function's only job on
    that path is routing straight to END, skipping discovery and every
    lookup node (Requirement 4.1)."""
    if state.response is not None:
        return END
    if state.source in (None, "retail", "vinted"):
        return "discovery"
    # source == "kleinanzeigen": discovery is never attempted for this
    # source (mirrors _resolve_product_find()'s discovery-skip for this
    # source) — Kleinanzeigen's own gate (`is_germany`) doesn't depend on
    # discovery, so route straight to the same fan-out decision `discovery`
    # itself routes through below.
    return _route_lookups(state)


# ── Graph construction (Requirement 2.1, 2.2) ────────────────────────────────

_builder = StateGraph(ProductFinderStudioState)
_builder.add_node("cache_check", _cache_check_node)
_builder.add_node("discovery", _discovery_node)
_builder.add_node("lookup_vinted", _lookup_vinted_node)
_builder.add_node("lookup_secondhand_marketplaces", _lookup_secondhand_marketplaces_node)
_builder.add_node("lookup_retail", _lookup_retail_node)
_builder.add_node("lookup_kleinanzeigen", _lookup_kleinanzeigen_node)
_builder.add_node("combine", _combine_node)

_builder.set_entry_point("cache_check")
# Both conditional-edge functions compute their destination dynamically (a
# plain `list[str] | str` return type, not a `Literal[...]` enumerating every
# possible value), so LangGraph has nothing to statically infer the reachable
# nodes from — omitting `path_map` leaves Studio's graph view drawing every
# node past the branch as disconnected (verified live: this was exactly the
# symptom before `path_map` was added here). Passing `path_map` as a list of
# every node name each function can actually return makes the edges explicit
# for visualization while leaving runtime routing untouched (the functions'
# return values already equal these node names directly, so this is a
# same-name identity mapping, not a translation layer).
_builder.add_conditional_edges(
    "cache_check",
    _route_after_cache_check,
    [
        "discovery",
        "lookup_vinted",
        "lookup_secondhand_marketplaces",
        "lookup_retail",
        "lookup_kleinanzeigen",
        "combine",
        END,
    ],
)
_builder.add_conditional_edges(
    "discovery",
    _route_lookups,
    ["lookup_vinted", "lookup_secondhand_marketplaces", "lookup_retail", "lookup_kleinanzeigen", "combine"],
)
_builder.add_edge("lookup_vinted", "combine")
_builder.add_edge("lookup_secondhand_marketplaces", "combine")
_builder.add_edge("lookup_retail", "combine")
_builder.add_edge("lookup_kleinanzeigen", "combine")
_builder.add_edge("combine", END)

graph = _builder.compile(checkpointer=False)
