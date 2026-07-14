"""Tests for backend.tools.product_finder_studio (product-finder-studio-graph,
Task 6).

Scoped entirely to the new Studio-only shadow graph module and its
`langgraph.json` registration (Requirement 1.5/13.5 — no new tests are added
for `product_finder.py`, `product_source_discovery.py`, or
`relevance_filter.py`, since none of them changed).

Every node body in `product_finder_studio.py` calls exactly one reused
function looked up as a *module-level global* of `product_finder_studio`
itself (imported by name, e.g. `from backend.tools.product_finder import
_lookup_retail`) — so tests here monkeypatch those names directly on
`backend.tools.product_finder_studio` (not on `backend.tools.product_finder`),
mirroring how `tests/test_product_source_discovery.py` and
`tests/test_api_products.py` patch functions at the boundary they're actually
looked up from. The module-level `_cache_store` singleton is patched via its
bound methods (`_cache_store.get`/`.set`), the same store instance the nodes
actually use.

`pyproject.toml` sets `asyncio_mode = "auto"` (see `tests/test_api_products.py`
and `tests/test_product_source_discovery.py`), so `async def test_...`
functions run without an explicit `@pytest.mark.asyncio` marker or
`pytestmark`.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.tools.product_finder_studio as pfs
from backend.schemas import DiscoveredSources, ProductFindResponse, ProductListing


def _listing(source: str, title: str = "Balea Toner") -> ProductListing:
    return ProductListing(
        type="new",
        title=title,
        price=9.99,
        currency="EUR",
        source=source,
        thumbnail_url=None,
        listing_url=f"https://{source}/item",
    )


def _discovered(
    *,
    retailer_domains: tuple[str, ...] = ("dm.de",),
    vinted_domain: str | None = "vinted.de",
    secondhand_domains: tuple[str, ...] = ("kleiderkreisel.de",),
) -> DiscoveredSources:
    return DiscoveredSources(
        retailer_domains=retailer_domains,
        vinted_domain=vinted_domain,
        secondhand_domains=secondhand_domains,
    )


def _passthrough_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `_sort_by_relevance_and_completeness` a no-op passthrough so
    combine's output listings equal the raw concatenation order, for tests
    that don't care about sorting itself (already covered by
    `tests/test_product_finder.py`'s own `TestSortByRelevanceAndCompleteness`,
    Requirement 1.5)."""
    monkeypatch.setattr(
        pfs,
        "_sort_by_relevance_and_completeness",
        lambda listings, name, brand: listings,
    )


class TestGraphShape:
    """Graph compiles and has the expected shape (Requirement 4)."""

    def test_graph_is_a_compiled_state_graph(self) -> None:
        # CompiledStateGraph exposes get_graph(); importing the module at
        # collection time already proves import succeeds without error.
        assert hasattr(pfs.graph, "ainvoke")
        assert hasattr(pfs.graph, "get_graph")

    def test_node_names_match_exactly_no_extra_or_missing(self) -> None:
        node_names = set(pfs.graph.get_graph().nodes.keys())
        # LangGraph always includes the implicit "__start__"/"__end__" nodes
        # alongside the ones this module registered via add_node().
        expected = {
            "cache_check",
            "discovery",
            "lookup_vinted",
            "lookup_secondhand_marketplaces",
            "lookup_retail",
            "lookup_kleinanzeigen",
            "combine",
        }
        assert expected.issubset(node_names)
        assert node_names - expected == {"__start__", "__end__"}


class TestCacheHitShortCircuits:
    """Requirement 4.1: a cache hit ends the run immediately, without
    discovery or any lookup node running."""

    async def test_cache_hit_returns_cached_response_and_calls_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cached = ProductFindResponse(listings=[_listing("dm.de")], retail_ok=True, secondhand_ok=False)
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: cached)

        def _raise(*args: object, **kwargs: object) -> None:
            raise AssertionError("should not have been called on a cache hit")

        monkeypatch.setattr(pfs, "get_or_discover_sources", AsyncMock(side_effect=_raise))
        monkeypatch.setattr(pfs, "_lookup_secondhand", AsyncMock(side_effect=_raise))
        monkeypatch.setattr(pfs, "_lookup_secondhand_marketplaces", AsyncMock(side_effect=_raise))
        monkeypatch.setattr(pfs, "_lookup_retail", AsyncMock(side_effect=_raise))
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", AsyncMock(side_effect=_raise))

        result = await pfs.graph.ainvoke({"name": "Balea Toner", "location": "Germany", "source": None})

        assert result["response"] == cached


class TestFullFanOut:
    """Requirement 4.4, 4.5, 8, 9.1: every category discovered -> all four
    lookups run, combine concatenates in the fixed order."""

    async def test_all_four_lookups_called_and_combine_concatenates_in_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        set_mock = MagicMock()
        monkeypatch.setattr(pfs._cache_store, "set", set_mock)
        monkeypatch.setattr(
            pfs, "get_or_discover_sources", AsyncMock(return_value=_discovered())
        )

        vinted_listing = _listing("vinted.de", "vinted-item")
        secondhand_listing = _listing("kleiderkreisel.de", "secondhand-item")
        retail_listing = _listing("dm.de", "retail-item")
        kleinanzeigen_listing = _listing("kleinanzeigen.de", "kleinanzeigen-item")

        lookup_secondhand = AsyncMock(return_value=([vinted_listing], True))
        lookup_secondhand_marketplaces = AsyncMock(return_value=([secondhand_listing], True))
        lookup_retail = AsyncMock(return_value=([retail_listing], True))
        lookup_kleinanzeigen = AsyncMock(return_value=([kleinanzeigen_listing], True))
        monkeypatch.setattr(pfs, "_lookup_secondhand", lookup_secondhand)
        monkeypatch.setattr(pfs, "_lookup_secondhand_marketplaces", lookup_secondhand_marketplaces)
        monkeypatch.setattr(pfs, "_lookup_retail", lookup_retail)
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", lookup_kleinanzeigen)

        captured_sort_input: list[ProductListing] = []

        def _spy_sort(listings: list[ProductListing], name: str, brand: str | None) -> list[ProductListing]:
            captured_sort_input.extend(listings)
            return listings

        monkeypatch.setattr(pfs, "_sort_by_relevance_and_completeness", _spy_sort)

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "brand": None, "location": "Germany", "source": None}
        )

        lookup_secondhand.assert_called_once()
        lookup_secondhand_marketplaces.assert_called_once()
        lookup_retail.assert_called_once()
        lookup_kleinanzeigen.assert_called_once()

        assert captured_sort_input == [
            vinted_listing,
            secondhand_listing,
            retail_listing,
            kleinanzeigen_listing,
        ]
        assert result["response"].listings == captured_sort_input
        assert result["response"].retail_ok is True
        assert result["response"].secondhand_ok is True
        set_mock.assert_called_once()


class TestSourceNarrowsFanOut:
    """Requirement 4.4: source="vinted" only permits vinted +
    secondhand-marketplaces, never retail/kleinanzeigen."""

    async def test_source_vinted_excludes_retail_and_kleinanzeigen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        monkeypatch.setattr(pfs._cache_store, "set", MagicMock())
        monkeypatch.setattr(
            pfs, "get_or_discover_sources", AsyncMock(return_value=_discovered())
        )
        _passthrough_sort(monkeypatch)

        lookup_secondhand = AsyncMock(return_value=([_listing("vinted.de")], True))
        lookup_secondhand_marketplaces = AsyncMock(
            return_value=([_listing("kleiderkreisel.de")], True)
        )
        lookup_retail = AsyncMock(side_effect=AssertionError("retail must not be called"))
        lookup_kleinanzeigen = AsyncMock(side_effect=AssertionError("kleinanzeigen must not be called"))
        monkeypatch.setattr(pfs, "_lookup_secondhand", lookup_secondhand)
        monkeypatch.setattr(pfs, "_lookup_secondhand_marketplaces", lookup_secondhand_marketplaces)
        monkeypatch.setattr(pfs, "_lookup_retail", lookup_retail)
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", lookup_kleinanzeigen)

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "location": "Germany", "source": "vinted"}
        )

        lookup_secondhand.assert_called_once()
        lookup_secondhand_marketplaces.assert_called_once()
        lookup_retail.assert_not_called()
        lookup_kleinanzeigen.assert_not_called()
        assert result["response"].retail_ok is False


class TestKleinanzeigenSkipsDiscovery:
    """Requirement 4.4 (discovery-skip for source="kleinanzeigen") and the
    no-network-call case for a non-Germany location."""

    async def test_kleinanzeigen_in_germany_runs_alone_without_discovery(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        monkeypatch.setattr(pfs._cache_store, "set", MagicMock())
        discovery_mock = AsyncMock(side_effect=AssertionError("discovery must not run"))
        monkeypatch.setattr(pfs, "get_or_discover_sources", discovery_mock)
        _passthrough_sort(monkeypatch)

        lookup_kleinanzeigen = AsyncMock(return_value=([_listing("kleinanzeigen.de")], True))
        lookup_secondhand = AsyncMock(side_effect=AssertionError("vinted must not run"))
        lookup_secondhand_marketplaces = AsyncMock(
            side_effect=AssertionError("secondhand marketplaces must not run")
        )
        lookup_retail = AsyncMock(side_effect=AssertionError("retail must not run"))
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", lookup_kleinanzeigen)
        monkeypatch.setattr(pfs, "_lookup_secondhand", lookup_secondhand)
        monkeypatch.setattr(pfs, "_lookup_secondhand_marketplaces", lookup_secondhand_marketplaces)
        monkeypatch.setattr(pfs, "_lookup_retail", lookup_retail)

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "location": "Germany", "source": "kleinanzeigen"}
        )

        discovery_mock.assert_not_called()
        lookup_kleinanzeigen.assert_called_once()
        lookup_secondhand.assert_not_called()
        lookup_secondhand_marketplaces.assert_not_called()
        lookup_retail.assert_not_called()
        assert result["response"].secondhand_ok is True

    async def test_kleinanzeigen_non_germany_runs_no_lookup_and_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        set_mock = MagicMock()
        monkeypatch.setattr(pfs._cache_store, "set", set_mock)
        discovery_mock = AsyncMock(side_effect=AssertionError("discovery must not run"))
        monkeypatch.setattr(pfs, "get_or_discover_sources", discovery_mock)

        lookup_kleinanzeigen = AsyncMock(side_effect=AssertionError("kleinanzeigen must not run"))
        lookup_secondhand = AsyncMock(side_effect=AssertionError("vinted must not run"))
        lookup_secondhand_marketplaces = AsyncMock(
            side_effect=AssertionError("secondhand marketplaces must not run")
        )
        lookup_retail = AsyncMock(side_effect=AssertionError("retail must not run"))
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", lookup_kleinanzeigen)
        monkeypatch.setattr(pfs, "_lookup_secondhand", lookup_secondhand)
        monkeypatch.setattr(pfs, "_lookup_secondhand_marketplaces", lookup_secondhand_marketplaces)
        monkeypatch.setattr(pfs, "_lookup_retail", lookup_retail)

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "location": "France", "source": "kleinanzeigen"}
        )

        discovery_mock.assert_not_called()
        lookup_kleinanzeigen.assert_not_called()
        lookup_secondhand.assert_not_called()
        lookup_secondhand_marketplaces.assert_not_called()
        lookup_retail.assert_not_called()
        assert result["response"].listings == []
        assert result["response"].retail_ok is False
        assert result["response"].secondhand_ok is False
        set_mock.assert_not_called()


class TestDiscoveredButEmptyCategoryNotAttempted:
    """Requirement 4.4's full conjunction: a discovered-but-empty category
    (e.g. vinted_domain=None) isn't attempted even though `source` alone
    would permit it."""

    async def test_vinted_domain_none_skips_lookup_vinted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        monkeypatch.setattr(pfs._cache_store, "set", MagicMock())
        monkeypatch.setattr(
            pfs,
            "get_or_discover_sources",
            AsyncMock(return_value=_discovered(vinted_domain=None)),
        )
        _passthrough_sort(monkeypatch)

        lookup_secondhand = AsyncMock(side_effect=AssertionError("vinted must not run"))
        lookup_secondhand_marketplaces = AsyncMock(
            return_value=([_listing("kleiderkreisel.de")], True)
        )
        lookup_retail = AsyncMock(return_value=([_listing("dm.de")], True))
        lookup_kleinanzeigen = AsyncMock(return_value=([_listing("kleinanzeigen.de")], True))
        monkeypatch.setattr(pfs, "_lookup_secondhand", lookup_secondhand)
        monkeypatch.setattr(pfs, "_lookup_secondhand_marketplaces", lookup_secondhand_marketplaces)
        monkeypatch.setattr(pfs, "_lookup_retail", lookup_retail)
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", lookup_kleinanzeigen)

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "location": "Germany", "source": None}
        )

        lookup_secondhand.assert_not_called()
        lookup_secondhand_marketplaces.assert_called_once()
        lookup_retail.assert_called_once()
        lookup_kleinanzeigen.assert_called_once()
        assert result["response"].secondhand_ok is True


class TestCacheWriteIsConditional:
    """Requirement 7.2: cache write only happens when at least one lookup
    succeeded (retail_ok or secondhand_ok)."""

    async def test_all_failures_never_write_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        set_mock = MagicMock()
        monkeypatch.setattr(pfs._cache_store, "set", set_mock)
        monkeypatch.setattr(
            pfs, "get_or_discover_sources", AsyncMock(return_value=_discovered())
        )
        _passthrough_sort(monkeypatch)

        monkeypatch.setattr(pfs, "_lookup_secondhand", AsyncMock(return_value=([], False)))
        monkeypatch.setattr(
            pfs, "_lookup_secondhand_marketplaces", AsyncMock(return_value=([], False))
        )
        monkeypatch.setattr(pfs, "_lookup_retail", AsyncMock(return_value=([], False)))
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", AsyncMock(return_value=([], False)))

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "location": "Germany", "source": None}
        )

        set_mock.assert_not_called()
        assert result["response"].retail_ok is False
        assert result["response"].secondhand_ok is False

    async def test_at_least_one_success_writes_cache_with_expected_key_and_market_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        set_mock = MagicMock()
        monkeypatch.setattr(pfs._cache_store, "set", set_mock)
        monkeypatch.setattr(
            pfs, "get_or_discover_sources", AsyncMock(return_value=_discovered())
        )
        _passthrough_sort(monkeypatch)

        monkeypatch.setattr(pfs, "_lookup_secondhand", AsyncMock(return_value=([], False)))
        monkeypatch.setattr(
            pfs, "_lookup_secondhand_marketplaces", AsyncMock(return_value=([], False))
        )
        monkeypatch.setattr(
            pfs, "_lookup_retail", AsyncMock(return_value=([_listing("dm.de")], True))
        )
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", AsyncMock(return_value=([], False)))

        result = await pfs.graph.ainvoke(
            {"name": "Balea Toner", "brand": "Balea", "location": "Germany", "source": None}
        )

        set_mock.assert_called_once()
        _cache_key_arg, response_arg = set_mock.call_args.args
        expected_cache_key = pfs.ProductCacheStore.make_key("Balea Toner", "Balea", "germany:all")
        assert _cache_key_arg == expected_cache_key
        assert response_arg == result["response"]
        assert set_mock.call_args.kwargs["market_code"] == "germany:all"
        assert set_mock.call_args.kwargs["name"] == "Balea Toner"
        assert set_mock.call_args.kwargs["brand"] == "Balea"


class TestNodeFailurePropagates:
    """Requirement 11.2: an unexpected exception from a reused function
    propagates out of the graph invocation rather than completing with an
    empty/default result."""

    async def test_lookup_failure_raises_instead_of_completing_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pfs._cache_store, "get", lambda cache_key: None)
        monkeypatch.setattr(pfs._cache_store, "set", MagicMock())
        monkeypatch.setattr(
            pfs, "get_or_discover_sources", AsyncMock(return_value=_discovered())
        )

        monkeypatch.setattr(
            pfs, "_lookup_secondhand", AsyncMock(side_effect=RuntimeError("boom"))
        )
        monkeypatch.setattr(
            pfs, "_lookup_secondhand_marketplaces", AsyncMock(return_value=([], True))
        )
        monkeypatch.setattr(pfs, "_lookup_retail", AsyncMock(return_value=([], True)))
        monkeypatch.setattr(pfs, "_lookup_kleinanzeigen", AsyncMock(return_value=([], True)))

        with pytest.raises(RuntimeError, match="boom"):
            await pfs.graph.ainvoke({"name": "Balea Toner", "location": "Germany", "source": None})


class TestLanggraphJsonRegistration:
    """Requirement 2.2, 2.3: the new `product_finder` entry is registered
    alongside the pre-existing `derma6_agent`/`rag_pipeline` entries, which
    remain unchanged."""

    def test_product_finder_entry_present_and_existing_entries_unchanged(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        config = json.loads((repo_root / "langgraph.json").read_text())

        graphs = config["graphs"]
        assert graphs["product_finder"] == "./backend/tools/product_finder_studio.py:graph"
        assert graphs["derma6_agent"] == "./backend/agent/studio.py:graph"
        assert graphs["rag_pipeline"] == "./backend/agent/studio.py:rag_graph"
