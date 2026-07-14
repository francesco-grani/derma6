"""Tests for backend.tools.product_finder (product-finder v1 +
product-source-agent).

Accumulates across product-finder's Tasks 6-11 and product-source-agent's
Tasks 8-11 as each part of `backend/tools/product_finder.py` is implemented,
mirroring `tests/test_api_routines.py`'s house style. Market/location
resolution (v1's `resolve_market()`/`MARKET_CONFIGS`/`MarketConfig`) has been
replaced by the agentic source-discovery step
(`backend.tools.product_source_discovery`, tested in
`tests/test_product_source_discovery.py`) — this file now covers price
extraction (`_extract_price()`), the Vinted secondhand lookup
(`_lookup_secondhand()`, now parameterized by a plain `vinted_domain: str`),
the per-domain query core (`_query_domain()`/`_lookup_domains()`), the retail
(new) lookup (`_lookup_retail()`, now fed by `_lookup_domains()`), the
secondhand-marketplace lookup (`_lookup_secondhand_marketplaces()`), the
Kleinanzeigen (secondhand, DE-only) lookup (`_lookup_kleinanzeigen()`, no
longer takes a `market` parameter), and the `/find` endpoint itself
(`find_product()`, now discovery-gated).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import get_current_user
from backend.config import settings
from backend.db.deps import (
    get_product_cache_store,
    get_profile_store,
    get_source_discovery_store,
)
from backend.db.product_cache_store import ProductCacheStore
from backend.db.source_discovery_store import SourceDiscoveryStore
from backend.middleware.auth import JWTAuthMiddleware
from backend.schemas import DiscoveredSources, ProductFindResponse, ProductListing
from backend.tools.product_finder import (
    _diversify_by_source,
    _extract_price,
    _extract_price_from_html,
    _fetch_listing_price,
    _fetch_og_image,
    _lookup_domains,
    _lookup_kleinanzeigen,
    _lookup_retail,
    _lookup_secondhand,
    _lookup_secondhand_marketplaces,
    _query_domain,
    _sort_by_relevance_and_completeness,
)
from backend.tools.product_finder import router as product_finder_router
from backend.tools.product_source_discovery import (
    _GERMANY_SEED_RETAILER_DOMAINS,
    _GERMANY_SEED_VINTED_DOMAIN,
)


class TestExtractPrice:
    def test_symbol_prefixed_dot_decimal(self) -> None:
        assert _extract_price("Vichy Mineral 89 Serum €12.99 - dm.de") == (12.99, "EUR")

    def test_symbol_suffixed_comma_decimal(self) -> None:
        assert _extract_price("Vichy Mineral 89 Serum 12,99 € - dm.de") == (12.99, "EUR")

    def test_noisy_snippet_with_no_clean_price_returns_none(self) -> None:
        assert _extract_price("Top-rated serum, loved by thousands of reviewers") == (
            None,
            None,
        )

    def test_currency_symbol_without_amount_returns_none(self) -> None:
        assert _extract_price("€ Sale now on at your local drugstore!") == (None, None)


def _listing(
    source: str,
    title: str,
    price: float | None = None,
    thumbnail_url: str | None = None,
) -> ProductListing:
    return ProductListing(
        type="new",
        title=title,
        price=price,
        currency="EUR" if price is not None else None,
        source=source,
        thumbnail_url=thumbnail_url,
        listing_url=f"https://{source}/{title}",
    )


class TestDiversifyBySource:
    def test_caps_each_source_at_max_per_source(self) -> None:
        listings = [_listing("amazon.de", f"item{i}") for i in range(5)]

        result = _diversify_by_source(listings, max_per_source=3)

        assert len(result) == 3

    def test_interleaves_round_robin_across_sources_instead_of_grouping(self) -> None:
        listings = [
            _listing("amazon.de", "a1"),
            _listing("amazon.de", "a2"),
            _listing("amazon.de", "a3"),
            _listing("dm.de", "d1"),
            _listing("rossmann.de", "r1"),
        ]

        result = _diversify_by_source(listings, max_per_source=3)

        assert [listing.source for listing in result] == [
            "amazon.de",
            "dm.de",
            "rossmann.de",
            "amazon.de",
            "amazon.de",
        ]

    def test_empty_input_returns_empty(self) -> None:
        assert _diversify_by_source([], max_per_source=3) == []


class TestSortByRelevanceAndCompleteness:
    """`_sort_by_relevance_and_completeness()`: orders the final combined
    response so the most relevant (name/brand exact-match) and complete
    (thumbnail/price present) listings surface first."""

    def test_name_match_outranks_no_name_match(self) -> None:
        off_topic = _listing("dm.de", "Skincare Routine: 7 Schritte zu strahlender Haut")
        on_topic = _listing("rossmann.de", "Balea Hydrating Toner 200ml")

        result = _sort_by_relevance_and_completeness(
            [off_topic, on_topic], "Balea Hydrating Toner", None
        )

        assert result == [on_topic, off_topic]

    def test_name_match_is_case_insensitive_substring_not_whole_title_equality(self) -> None:
        listing = _listing(
            "dm.de", "BALEA Hydrating Toner Blue Beauty Expert, 100 ml dauerhaft günstig | dm.de"
        )

        result = _sort_by_relevance_and_completeness([listing], "Balea Hydrating Toner", None)

        assert result == [listing]

    def test_brand_match_breaks_a_tie_after_name_match(self) -> None:
        wrong_brand = _listing("dm.de", "Toner from a competitor brand")
        right_brand = _listing("rossmann.de", "Balea Toner")

        result = _sort_by_relevance_and_completeness([wrong_brand, right_brand], "Toner", "Balea")

        assert result == [right_brand, wrong_brand]

    def test_brand_none_does_not_penalize_any_listing(self) -> None:
        first = _listing("dm.de", "Balea Toner")
        second = _listing("rossmann.de", "Balea Toner")

        result = _sort_by_relevance_and_completeness([first, second], "Balea Toner", None)

        # No brand given -> brand component never differentiates -> original
        # (stable-sort) order is preserved between the tied listings.
        assert result == [first, second]

    def test_completeness_breaks_a_tie_after_relevance(self) -> None:
        incomplete = _listing("dm.de", "Balea Toner", price=None, thumbnail_url=None)
        complete = _listing("rossmann.de", "Balea Toner", price=9.99, thumbnail_url="https://x/y.jpg")

        result = _sort_by_relevance_and_completeness([incomplete, complete], "Balea Toner", None)

        assert result == [complete, incomplete]

    def test_thumbnail_presence_outranks_price_presence(self) -> None:
        price_only = _listing("dm.de", "Balea Toner", price=9.99, thumbnail_url=None)
        thumbnail_only = _listing(
            "rossmann.de", "Balea Toner", price=None, thumbnail_url="https://x/y.jpg"
        )

        result = _sort_by_relevance_and_completeness(
            [price_only, thumbnail_only], "Balea Toner", None
        )

        assert result == [thumbnail_only, price_only]

    def test_relevance_outranks_completeness(self) -> None:
        """A fully-enriched off-topic listing must still rank below a bare,
        unenriched on-topic one — relevance is the primary sort key."""
        off_topic_complete = _listing(
            "dm.de", "Unrelated Product", price=9.99, thumbnail_url="https://x/y.jpg"
        )
        on_topic_bare = _listing("rossmann.de", "Balea Toner", price=None, thumbnail_url=None)

        result = _sort_by_relevance_and_completeness(
            [off_topic_complete, on_topic_bare], "Balea Toner", None
        )

        assert result == [on_topic_bare, off_topic_complete]

    def test_ties_preserve_original_order_stable_sort(self) -> None:
        first = _listing("dm.de", "Unrelated A")
        second = _listing("rossmann.de", "Unrelated B")
        third = _listing("douglas.de", "Unrelated C")

        result = _sort_by_relevance_and_completeness(
            [first, second, third], "Balea Toner", None
        )

        assert result == [first, second, third]

    def test_cheaper_price_breaks_a_tie_after_completeness(self) -> None:
        """Regression test: two listings tied on every relevance/completeness
        component (neither title contains the full query verbatim, both have
        a thumbnail and a price) still need to resolve deterministically by
        price, or the cheaper one has no reason to rank first."""
        expensive = _listing(
            "amazon.it", "Balea Cream for Very Dry Feet", price=13.69, thumbnail_url="https://x/e.jpg"
        )
        cheap = _listing(
            "amazon.it", "Balea Moisturizing Day Cream SPF 15", price=8.49, thumbnail_url="https://x/c.jpg"
        )

        result = _sort_by_relevance_and_completeness(
            [expensive, cheap], "Balea Hydrating Cream", None
        )

        assert result == [cheap, expensive]

    def test_price_tiebreak_never_overrides_relevance(self) -> None:
        """A cheaper but off-topic listing must still rank below a pricier
        on-topic one — the price tiebreak only applies among listings
        already tied on relevance/completeness."""
        cheap_off_topic = _listing("dm.de", "Unrelated Product", price=1.0, thumbnail_url="https://x/a.jpg")
        pricier_on_topic = _listing(
            "rossmann.de", "Balea Toner", price=20.0, thumbnail_url="https://x/b.jpg"
        )

        result = _sort_by_relevance_and_completeness(
            [cheap_off_topic, pricier_on_topic], "Balea Toner", None
        )

        assert result == [pricier_on_topic, cheap_off_topic]

    def test_empty_input_returns_empty(self) -> None:
        assert _sort_by_relevance_and_completeness([], "Balea Toner", None) == []


class _FakePrice:
    def __init__(self, amount: str | None, currency_code: str | None) -> None:
        self.amount = amount
        self.currency_code = currency_code


class _FakePhoto:
    def __init__(self, url: str | None) -> None:
        self.url = url


class _FakeItem:
    def __init__(
        self,
        title: str,
        price: "_FakePrice | None",
        brand_title: str | None,
        url: str,
        photo_url: str | None,
    ) -> None:
        self.title = title
        self.price = price
        self.brand_title = brand_title
        self.url = url
        self.photo = _FakePhoto(photo_url)


class _FakeSearchResponse:
    def __init__(self, items: list) -> None:
        self.items = items


def _make_client(items: list) -> MagicMock:
    """A `Vinted(...)` stand-in whose `.search()` returns a fake response."""
    client = MagicMock()
    client.search.return_value = _FakeSearchResponse(items)
    return client


class TestLookupSecondhand:
    """Task 8: `_lookup_secondhand()`, with `vinted.Vinted` mocked at the
    boundary (`backend.tools.product_finder.Vinted`) per Req 10 and Req 14's
    never-raise contract."""

    async def test_success_maps_items_to_listings(self) -> None:
        items = [
            _FakeItem(
                title="Vichy Mineral 89 Serum",
                price=_FakePrice("12.99", "EUR"),
                brand_title="Vichy",
                url="https://www.vinted.de/items/1",
                photo_url="https://images.vinted.net/1.jpg",
            ),
            _FakeItem(
                title="La Roche-Posay Cream",
                price=_FakePrice("8.50", "EUR"),
                brand_title="La Roche-Posay",
                url="https://www.vinted.de/items/2",
                photo_url="https://images.vinted.net/2.jpg",
            ),
        ]
        client = _make_client(items)

        with patch("backend.tools.product_finder.Vinted", return_value=client) as mock_vinted:
            listings, ok = await _lookup_secondhand("Mineral 89", "Vichy", "vinted.de")

        assert ok is True
        assert len(listings) == 2
        mock_vinted.assert_called_once_with(domain="de")
        client.search.assert_called_once_with(query="Vichy Mineral 89")

        first, second = listings
        assert first.type == "used"
        assert first.source == "Vinted"
        assert first.title == "Vichy Mineral 89 Serum"
        assert first.price == 12.99
        assert first.currency == "EUR"
        assert first.thumbnail_url == "https://images.vinted.net/1.jpg"
        assert first.listing_url == "https://www.vinted.de/items/1"

        assert second.type == "used"
        assert second.source == "Vinted"
        assert second.title == "La Roche-Posay Cream"
        assert second.price == 8.50
        assert second.currency == "EUR"

    async def test_query_without_brand_uses_name_only(self) -> None:
        client = _make_client([])

        with patch("backend.tools.product_finder.Vinted", return_value=client):
            listings, ok = await _lookup_secondhand("Mineral 89 Serum", None, "vinted.de")

        assert ok is True
        assert listings == []
        client.search.assert_called_once_with(query="Mineral 89 Serum")

    async def test_construction_failure_returns_empty_and_false(self, caplog: pytest.LogCaptureFixture) -> None:
        with patch("backend.tools.product_finder.Vinted", side_effect=RuntimeError("cloudflare blocked")):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_secondhand("Mineral 89", "Vichy", "vinted.de")

        assert listings == []
        assert ok is False
        assert "vinted" in caplog.text.lower()

    async def test_search_failure_returns_empty_and_false(self, caplog: pytest.LogCaptureFixture) -> None:
        client = MagicMock()
        client.search.side_effect = RuntimeError("boom")

        with patch("backend.tools.product_finder.Vinted", return_value=client):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_secondhand("Mineral 89", "Vichy", "vinted.de")

        assert listings == []
        assert ok is False
        assert "vinted" in caplog.text.lower()

    async def test_timeout_returns_empty_and_false_with_no_retry(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(settings, "product_lookup_timeout_seconds", 0.05)

        def _slow_search(*args: object, **kwargs: object) -> _FakeSearchResponse:
            import time

            time.sleep(0.5)
            return _FakeSearchResponse([])

        client = MagicMock()
        client.search.side_effect = _slow_search

        with patch("backend.tools.product_finder.Vinted", return_value=client) as mock_vinted:
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_secondhand("Mineral 89", "Vichy", "vinted.de")

        assert listings == []
        assert ok is False
        assert "vinted" in caplog.text.lower()
        # No retry: the client is only ever constructed once.
        mock_vinted.assert_called_once()

    async def test_malformed_response_items_returns_empty_and_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression test: a live run against the real Vinted API hit a case
        where the request succeeded (HTTP 200) but `vinted-api-wrapper`
        failed to parse the response as JSON internally and silently
        returned a `response.items` that wasn't a list (a bound
        `dict.items` method, in the observed case), which isn't
        subscriptable. Result *processing*, not just the network call, must
        be covered by the never-raise contract (Req 14)."""
        client = MagicMock()
        client.search.return_value = _FakeSearchResponse(items=object())  # not subscriptable

        with patch("backend.tools.product_finder.Vinted", return_value=client):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_secondhand("Mineral 89", "Vichy", "vinted.de")

        assert listings == []
        assert ok is False
        assert "vinted" in caplog.text.lower()

    async def test_results_are_capped_to_configured_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "product_max_listings_per_source", 3)
        items = [
            _FakeItem(
                title=f"Item {i}",
                price=_FakePrice("5.00", "EUR"),
                brand_title="Vichy",
                url=f"https://www.vinted.de/items/{i}",
                photo_url=f"https://images.vinted.net/{i}.jpg",
            )
            for i in range(6)
        ]
        client = _make_client(items)

        with patch("backend.tools.product_finder.Vinted", return_value=client):
            listings, ok = await _lookup_secondhand("Mineral 89", "Vichy", "vinted.de")

        assert ok is True
        assert len(listings) == 3


class TestQueryDomain:
    """`_query_domain()`: one domain's contribution to a category, built on
    `domain_search.search_domain()` (mocked at the boundary it's imported
    into `product_finder` under: `backend.tools.product_finder.search_domain`)
    per Req 5.1 and Req 5.4's never-raise contract."""

    async def test_success_maps_results_to_listings_tagged_with_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_search = AsyncMock(
            return_value=(
                [
                    {
                        "title": "Vichy Mineral 89 Serum €12.99",
                        "url": "https://dm.de/vichy-mineral-89",
                        "snippet": "Buy now",
                    }
                ],
                True,
            )
        )
        monkeypatch.setattr("backend.tools.product_finder.search_domain", mock_search)

        listings, ok = await _query_domain("Vichy Mineral 89", "dm.de", "new", 8)

        assert ok is True
        assert len(listings) == 1
        listing = listings[0]
        assert listing.type == "new"
        assert listing.source == "dm.de"
        assert listing.price == 12.99
        assert listing.currency == "EUR"
        assert listing.listing_url == "https://dm.de/vichy-mineral-89"
        mock_search.assert_awaited_once_with(
            "Vichy Mineral 89",
            "dm.de",
            8,
            timeout_seconds=settings.product_lookup_timeout_seconds,
        )

    async def test_used_listing_type_is_tagged_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(
                return_value=(
                    [{"title": "Item", "url": "https://kleiderkreisel.de/x", "snippet": ""}],
                    True,
                )
            ),
        )

        listings, ok = await _query_domain("Vichy", "kleiderkreisel.de", "used", 8)

        assert ok is True
        assert listings[0].type == "used"
        assert listings[0].source == "kleiderkreisel.de"

    async def test_result_without_extractable_price_is_still_included(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(
                return_value=(
                    [
                        {
                            "title": "Vichy Mineral 89 Serum",
                            "url": "https://dm.de/vichy-mineral-89",
                            "snippet": "Loved by thousands of reviewers",
                        }
                    ],
                    True,
                )
            ),
        )

        listings, ok = await _query_domain("Vichy Mineral 89", "dm.de", "new", 8)

        assert ok is True
        assert len(listings) == 1
        assert listings[0].price is None
        assert listings[0].currency is None

    async def test_search_not_ok_returns_empty_and_false(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(return_value=([], False)),
        )

        with caplog.at_level("ERROR"):
            listings, ok = await _query_domain("Vichy", "dm.de", "new", 8)

        assert listings == []
        assert ok is False
        assert "dm.de" in caplog.text

    async def test_raised_exception_returns_empty_and_false(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(side_effect=RuntimeError("boom")),
        )

        with caplog.at_level("ERROR"):
            listings, ok = await _query_domain("Vichy", "dm.de", "new", 8)

        assert listings == []
        assert ok is False
        assert "dm.de" in caplog.text

    async def test_results_are_capped_to_max_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        results = [
            {"title": f"Item {i}", "url": f"https://dm.de/item-{i}", "snippet": "€5.00"}
            for i in range(6)
        ]
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(return_value=(results, True)),
        )

        listings, ok = await _query_domain("Vichy", "dm.de", "new", 3)

        assert ok is True
        assert len(listings) == 3

    async def test_on_stage_invoked_once_before_search_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[tuple[str, str]] = []
        search_dispatched_after_event = False

        async def fake_search(query: str, domain: str, max_results: int, timeout_seconds: float):
            nonlocal search_dispatched_after_event
            search_dispatched_after_event = len(events) == 1
            return [], True

        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain", AsyncMock(side_effect=fake_search)
        )

        def on_stage(stage: str, message: str) -> None:
            events.append((stage, message))

        await _query_domain("Vichy", "dm.de", "new", 8, on_stage)

        assert events == [("domain_check", "Checking dm.de...")]
        assert search_dispatched_after_event is True

    async def test_on_stage_invoked_once_before_search_on_failure(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        events: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(side_effect=RuntimeError("boom")),
        )

        def on_stage(stage: str, message: str) -> None:
            events.append((stage, message))

        with caplog.at_level("ERROR"):
            listings, ok = await _query_domain("Vichy", "dm.de", "new", 8, on_stage)

        assert listings == []
        assert ok is False
        assert events == [("domain_check", "Checking dm.de...")]


class TestLookupDomains:
    """`_lookup_domains()`: the shared category-level fan-out
    (`asyncio.gather` over `_query_domain`, Req 5.2) + combine
    (`_diversify_by_source`, Req 5.3) used by both `_lookup_retail` and
    `_lookup_secondhand_marketplaces`."""

    async def test_empty_domains_short_circuits_without_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_search = AsyncMock()
        monkeypatch.setattr("backend.tools.product_finder.search_domain", mock_search)
        on_stage = MagicMock()

        listings, ok, raw_pool = await _lookup_domains("Serum", "Vichy", (), "new", on_stage)

        assert listings == []
        assert ok is False
        assert raw_pool == []
        mock_search.assert_not_called()
        on_stage.assert_not_called()

    async def test_runs_concurrently_not_sequentially(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time

        start_times: dict[str, float] = {}

        async def fake_search(query: str, domain: str, max_results: int, timeout_seconds: float):
            start_times[domain] = time.monotonic()
            delay = {"slow.de": 0.2, "fast.de": 0.01}[domain]
            await asyncio.sleep(delay)
            return [{"title": f"{domain} item", "url": f"https://{domain}/x", "snippet": ""}], True

        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain", AsyncMock(side_effect=fake_search)
        )

        t0 = time.monotonic()
        listings, ok, raw_pool = await _lookup_domains(
            "Serum", "Vichy", ("slow.de", "fast.de"), "new"
        )
        elapsed = time.monotonic() - t0

        assert ok is True
        assert {listing.source for listing in raw_pool} == {"slow.de", "fast.de"}
        # Both domains started at ~the same time (concurrent), not one after
        # the other.
        assert abs(start_times["slow.de"] - start_times["fast.de"]) < 0.1
        # Wall time tracks the slowest domain (~0.2s), not the sum (~0.21s) -
        # generous upper bound to avoid CI flakiness.
        assert elapsed < 0.2 + 0.15

    async def test_runs_concurrently_with_on_stage_supplied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Concurrency (wall time tracks the slowest domain, not the sum)
        must be preserved even when `on_stage` is supplied — emitting is a
        synchronous, non-blocking statement, not a shared synchronization
        point (Req 7.4, Non-Functional Consideration 2)."""
        import time

        async def fake_search(query: str, domain: str, max_results: int, timeout_seconds: float):
            delay = {"slow.de": 0.2, "fast.de": 0.01}[domain]
            await asyncio.sleep(delay)
            return [{"title": f"{domain} item", "url": f"https://{domain}/x", "snippet": ""}], True

        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain", AsyncMock(side_effect=fake_search)
        )
        events: list[tuple[str, str]] = []

        def on_stage(stage: str, message: str) -> None:
            events.append((stage, message))

        t0 = time.monotonic()
        listings, ok, raw_pool = await _lookup_domains(
            "Serum", "Vichy", ("slow.de", "fast.de"), "new", on_stage
        )
        elapsed = time.monotonic() - t0

        assert ok is True
        assert elapsed < 0.2 + 0.15
        assert sorted(events) == [
            ("domain_check", "Checking fast.de..."),
            ("domain_check", "Checking slow.de..."),
        ]

    async def test_on_stage_invoked_once_per_domain_at_dispatch_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain",
            AsyncMock(return_value=([], True)),
        )
        events: list[tuple[str, str]] = []

        def on_stage(stage: str, message: str) -> None:
            events.append((stage, message))

        await _lookup_domains("Serum", "Vichy", ("dm.de", "rossmann.de"), "new", on_stage)

        assert sorted(events) == [
            ("domain_check", "Checking dm.de..."),
            ("domain_check", "Checking rossmann.de..."),
        ]

    async def test_one_domain_fails_others_succeed_combined_ok_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_search(query: str, domain: str, max_results: int, timeout_seconds: float):
            if domain == "bad.de":
                raise RuntimeError("boom")
            return [{"title": f"{domain} item", "url": f"https://{domain}/x", "snippet": ""}], True

        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain", AsyncMock(side_effect=fake_search)
        )

        listings, ok, raw_pool = await _lookup_domains(
            "Serum", "Vichy", ("bad.de", "good.de"), "new"
        )

        assert ok is True
        assert {listing.source for listing in listings} == {"good.de"}
        assert {listing.source for listing in raw_pool} == {"good.de"}

    async def test_every_contributing_domain_represented_in_combined_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_search(query: str, domain: str, max_results: int, timeout_seconds: float):
            counts = {"amazon.de": 6, "dm.de": 1}
            n = counts[domain]
            return [
                {"title": f"{domain} item {i}", "url": f"https://{domain}/{i}", "snippet": ""}
                for i in range(n)
            ], True

        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain", AsyncMock(side_effect=fake_search)
        )

        listings, ok, raw_pool = await _lookup_domains(
            "Serum", "Vichy", ("amazon.de", "dm.de"), "new"
        )

        assert ok is True
        sources = {listing.source for listing in listings}
        assert sources == {"amazon.de", "dm.de"}

    async def test_raw_pool_retains_listings_dropped_by_per_domain_cap_and_final_slice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`raw_pool` must retain every domain's pre-diversification listing
        `_query_domain` returned, including ones `_diversify_by_source`'s
        per-domain cap (`_MAX_LISTINGS_PER_SOURCE_DOMAIN` == 3) or the
        category's final `[:max_results]` slice would otherwise discard (Req
        3.1) — this is exactly the material `filter_category`'s backfill
        step draws from.

        Three domains each return 5 raw results (== `max_results`, so
        `_query_domain`'s own `results[:max_results]` slice doesn't trim
        anything at the per-domain-query level); `_diversify_by_source`
        then caps each domain's bucket at 3 (9 total), and the category's
        final `[:max_results=5]` slice trims that further — `raw_pool` must
        still carry all 15 of the original per-domain results."""
        monkeypatch.setattr(settings, "product_max_listings_per_source", 5)
        domains = ("amazon.de", "dm.de", "rossmann.de")

        async def fake_search(query: str, domain: str, max_results: int, timeout_seconds: float):
            return [
                {"title": f"{domain} item {i}", "url": f"https://{domain}/{i}", "snippet": ""}
                for i in range(5)
            ], True

        monkeypatch.setattr(
            "backend.tools.product_finder.search_domain", AsyncMock(side_effect=fake_search)
        )

        listings, ok, raw_pool = await _lookup_domains("Serum", "Vichy", domains, "new")

        assert ok is True
        # The returned, capped/diversified list is much smaller (per-domain
        # cap of 3 x 3 domains = 9, then sliced to max_results=5)...
        assert len(listings) == 5
        # ...but raw_pool retains every raw result from every domain.
        assert len(raw_pool) == 15
        raw_urls = {listing.listing_url for listing in raw_pool}
        assert raw_urls == {f"https://{domain}/{i}" for domain in domains for i in range(5)}


class TestLookupRetail:
    """`_lookup_retail()`, now built on `_lookup_domains()` (mocked at the
    boundary) instead of a single shared Tavily/DuckDuckGo query — per-domain
    search behavior itself is covered by `TestQueryDomain`/`TestLookupDomains`
    above (and `domain_search.py`'s own tests). Enrichment (thumbnail/price)
    behavior is unchanged from v1, per Req 11 and Req 14's never-raise
    contract."""

    @staticmethod
    def _listing(source: str, title: str, price: float | None = None) -> ProductListing:
        return ProductListing(
            type="new",
            title=title,
            price=price,
            currency="EUR" if price is not None else None,
            source=source,
            thumbnail_url=None,
            listing_url=f"https://{source}/{title}",
        )

    @staticmethod
    def _passthrough_filter_category() -> AsyncMock:
        """A `filter_category` stand-in that returns `diversified` unfiltered
        — used by tests below that aren't exercising relevance filtering
        itself (covered by `tests/test_relevance_filter.py`), only the
        surrounding `_lookup_retail` wiring (ordering, enrichment)."""
        return AsyncMock(side_effect=lambda name, brand, diversified, raw_pool, cap, on_stage=None: diversified)

    async def test_forwards_to_lookup_domains_with_new_listing_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_lookup_domains = AsyncMock(return_value=([], True, []))
        monkeypatch.setattr("backend.tools.product_finder._lookup_domains", mock_lookup_domains)

        await _lookup_retail("Mineral 89", "Vichy", ("dm.de", "rossmann.de"))

        mock_lookup_domains.assert_awaited_once_with(
            "Mineral 89", "Vichy", ("dm.de", "rossmann.de"), listing_type="new", on_stage=None
        )

    async def test_ok_flag_passed_through_from_lookup_domains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains", AsyncMock(return_value=([], False, []))
        )

        listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("dm.de",))

        assert listings == []
        assert ok is False

    async def test_empty_listings_skip_enrichment_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains", AsyncMock(return_value=([], True, []))
        )

        with (
            patch("backend.tools.product_finder._fetch_og_image", new=AsyncMock()) as og_mock,
            patch(
                "backend.tools.product_finder._fetch_listing_price", new=AsyncMock()
            ) as price_mock,
        ):
            listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("dm.de",))

        assert listings == []
        assert ok is True
        og_mock.assert_not_called()
        price_mock.assert_not_called()

    async def test_thumbnails_attached_per_listing_after_search_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listings_in = [self._listing("dm.de", "Item A"), self._listing("rossmann.de", "Item B")]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", self._passthrough_filter_category()
        )

        async def _fake_fetch_og_image(url: str) -> str | None:
            return f"{url}/image.jpg"

        with patch(
            "backend.tools.product_finder._fetch_og_image",
            new=AsyncMock(side_effect=_fake_fetch_og_image),
        ):
            listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("dm.de", "rossmann.de"))

        assert ok is True
        assert listings[0].thumbnail_url == f"{listings_in[0].listing_url}/image.jpg"
        assert listings[1].thumbnail_url == f"{listings_in[1].listing_url}/image.jpg"

    async def test_thumbnail_enrichment_failure_does_not_discard_listings(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression test for the enrichment step's isolation guarantee:
        even if thumbnail enrichment fails entirely (not just a single
        listing's fetch — the whole `asyncio.gather` call raising), the
        already-successful search/price/url results must still be returned
        with `ok=True`, just without thumbnails. Enrichment failure must
        never downgrade a successful lookup to `([], False)`."""
        listings_in = [self._listing("dm.de", "Item A", price=5.00)]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", self._passthrough_filter_category()
        )

        with (
            patch(
                "backend.tools.product_finder._fetch_og_image",
                new=AsyncMock(side_effect=RuntimeError("enrichment blew up")),
            ),
            caplog.at_level("WARNING"),
        ):
            listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("dm.de",))

        assert ok is True
        assert len(listings) == 1
        assert listings[0].title == "Item A"
        assert listings[0].price == 5.00
        assert listings[0].thumbnail_url is None
        assert "thumbnail" in caplog.text.lower()

    async def test_price_enrichment_fills_in_price_missing_from_snippet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listings_in = [self._listing("amazon.de", "Item A", price=None)]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", self._passthrough_filter_category()
        )

        with (
            patch("backend.tools.product_finder._fetch_og_image", new=AsyncMock(return_value=None)),
            patch(
                "backend.tools.product_finder._fetch_listing_price",
                new=AsyncMock(return_value=(19.99, "EUR")),
            ),
        ):
            listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("amazon.de",))

        assert ok is True
        assert listings[0].price == 19.99
        assert listings[0].currency == "EUR"

    async def test_price_enrichment_only_fetches_listings_missing_a_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A listing whose snippet already yielded a price must not trigger
        a second network fetch — only the listing(s) still missing one."""
        listings_in = [
            self._listing("dm.de", "Item A", price=5.00),
            self._listing("amazon.de", "Item B", price=None),
        ]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", self._passthrough_filter_category()
        )
        fetch_price = AsyncMock(return_value=(19.99, "EUR"))

        with (
            patch("backend.tools.product_finder._fetch_og_image", new=AsyncMock(return_value=None)),
            patch("backend.tools.product_finder._fetch_listing_price", new=fetch_price),
        ):
            listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("dm.de", "amazon.de"))

        assert ok is True
        fetch_price.assert_called_once_with(listings_in[1].listing_url)
        assert listings[0].price == 5.00  # unchanged, from the snippet
        assert listings[1].price == 19.99  # filled in by enrichment

    async def test_price_enrichment_failure_does_not_discard_listings(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Mirrors `test_thumbnail_enrichment_failure_does_not_discard_listings`:
        a total failure of the price-enrichment step (the `asyncio.gather`
        call itself raising) must not downgrade an already-successful lookup
        to `([], False)` — the listing is simply returned with `price=None`."""
        listings_in = [self._listing("amazon.de", "Item A", price=None)]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", self._passthrough_filter_category()
        )

        with (
            patch("backend.tools.product_finder._fetch_og_image", new=AsyncMock(return_value=None)),
            patch(
                "backend.tools.product_finder._fetch_listing_price",
                new=AsyncMock(side_effect=RuntimeError("enrichment blew up")),
            ),
            caplog.at_level("WARNING"),
        ):
            listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("amazon.de",))

        assert ok is True
        assert len(listings) == 1
        assert listings[0].title == "Item A"
        assert listings[0].price is None
        assert "price" in caplog.text.lower()

    async def test_filter_category_invoked_between_lookup_domains_and_enrichment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Req 5.3: relevance filtering (including any backfill pass) must
        complete before either enrichment pass runs — asserted here via call
        ordering across all three mocked boundaries."""
        listings_in = [self._listing("amazon.de", "Item A", price=None)]
        call_order: list[str] = []

        async def fake_lookup_domains(*args: object, **kwargs: object):
            call_order.append("lookup_domains")
            return listings_in, True, listings_in

        async def fake_filter_category(name, brand, diversified, raw_pool, cap, on_stage=None):
            call_order.append("filter_category")
            return diversified

        async def fake_fetch_og_image(url: str) -> str | None:
            call_order.append("thumbnail")
            return None

        async def fake_fetch_listing_price(url: str):
            call_order.append("price")
            return None, None

        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains", AsyncMock(side_effect=fake_lookup_domains)
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", AsyncMock(side_effect=fake_filter_category)
        )
        monkeypatch.setattr(
            "backend.tools.product_finder._fetch_og_image",
            AsyncMock(side_effect=fake_fetch_og_image),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder._fetch_listing_price",
            AsyncMock(side_effect=fake_fetch_listing_price),
        )

        await _lookup_retail("Mineral 89", "Vichy", ("amazon.de",))

        assert call_order == ["lookup_domains", "filter_category", "thumbnail", "price"]

    async def test_on_stage_sees_stages_in_correct_order_when_all_apply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listings_in = [self._listing("amazon.de", "Item A", price=None)]

        async def fake_lookup_domains(name, brand, domains, listing_type, on_stage=None):
            if on_stage is not None:
                for domain in domains:
                    on_stage("domain_check", f"Checking {domain}...")
            return listings_in, True, listings_in

        async def fake_filter_category(name, brand, diversified, raw_pool, cap, on_stage=None):
            if on_stage is not None:
                on_stage("relevance_filter", "Checking listing relevance")
            return diversified

        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains", AsyncMock(side_effect=fake_lookup_domains)
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", AsyncMock(side_effect=fake_filter_category)
        )
        monkeypatch.setattr(
            "backend.tools.product_finder._fetch_og_image", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            "backend.tools.product_finder._fetch_listing_price", AsyncMock(return_value=(9.99, "EUR"))
        )

        events: list[str] = []

        def on_stage(stage: str, message: str) -> None:
            events.append(stage)

        await _lookup_retail("Mineral 89", "Vichy", ("amazon.de",), on_stage=on_stage)

        assert events == [
            "domain_check",
            "relevance_filter",
            "thumbnail_enrichment",
            "price_enrichment",
        ]

    async def test_price_enrichment_stage_event_skipped_when_every_listing_has_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listings_in = [self._listing("amazon.de", "Item A", price=5.00)]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", self._passthrough_filter_category()
        )
        monkeypatch.setattr(
            "backend.tools.product_finder._fetch_og_image", AsyncMock(return_value=None)
        )
        fetch_price = AsyncMock()
        monkeypatch.setattr("backend.tools.product_finder._fetch_listing_price", fetch_price)

        events: list[str] = []

        def on_stage(stage: str, message: str) -> None:
            events.append(stage)

        await _lookup_retail("Mineral 89", "Vichy", ("amazon.de",), on_stage=on_stage)

        fetch_price.assert_not_called()
        assert "price_enrichment" not in events
        assert "thumbnail_enrichment" in events

    async def test_thumbnail_enrichment_stage_event_skipped_when_listings_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When relevance filtering drops every candidate (`listings` ends up
        empty after `filter_category`), neither enrichment pass runs, so
        neither stage event fires (Req 7.2)."""
        listings_in = [self._listing("amazon.de", "Item A", price=None)]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=(listings_in, True, listings_in)),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", AsyncMock(return_value=[])
        )
        og_mock = AsyncMock()
        price_mock = AsyncMock()
        monkeypatch.setattr("backend.tools.product_finder._fetch_og_image", og_mock)
        monkeypatch.setattr("backend.tools.product_finder._fetch_listing_price", price_mock)

        events: list[str] = []

        def on_stage(stage: str, message: str) -> None:
            events.append(stage)

        listings, ok = await _lookup_retail("Mineral 89", "Vichy", ("amazon.de",), on_stage=on_stage)

        assert listings == []
        og_mock.assert_not_called()
        price_mock.assert_not_called()
        assert "thumbnail_enrichment" not in events
        assert "price_enrichment" not in events


class TestLookupSecondhandMarketplaces:
    """`_lookup_secondhand_marketplaces()` (Req 3.3/3.4, 4.2, 9.3): tags
    `type="used"`, `source=domain`; no thumbnail/price enrichment pass
    (contrast with `TestLookupRetail` above)."""

    async def test_forwards_to_lookup_domains_with_used_listing_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_lookup_domains = AsyncMock(return_value=([], True, []))
        monkeypatch.setattr("backend.tools.product_finder._lookup_domains", mock_lookup_domains)

        await _lookup_secondhand_marketplaces("Mineral 89", "Vichy", ("kleiderkreisel.de",))

        mock_lookup_domains.assert_awaited_once_with(
            "Mineral 89", "Vichy", ("kleiderkreisel.de",), listing_type="used", on_stage=None
        )

    async def test_tags_listings_used_and_source_domain_with_no_enrichment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listing = ProductListing(
            type="used",
            title="Item",
            price=None,
            currency=None,
            source="kleiderkreisel.de",
            thumbnail_url=None,
            listing_url="https://kleiderkreisel.de/item",
        )
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=([listing], True, [listing])),
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category",
            AsyncMock(side_effect=lambda name, brand, diversified, raw_pool, cap, on_stage=None: diversified),
        )

        with (
            patch("backend.tools.product_finder._fetch_og_image", new=AsyncMock()) as og_mock,
            patch(
                "backend.tools.product_finder._fetch_listing_price", new=AsyncMock()
            ) as price_mock,
        ):
            listings, ok = await _lookup_secondhand_marketplaces(
                "Mineral 89", "Vichy", ("kleiderkreisel.de",)
            )

        assert ok is True
        assert len(listings) == 1
        assert listings[0].type == "used"
        assert listings[0].source == "kleiderkreisel.de"
        assert listings[0].thumbnail_url is None
        og_mock.assert_not_called()
        price_mock.assert_not_called()

    async def test_filter_category_called_with_raw_pool_from_lookup_domains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listing = ProductListing(
            type="used",
            title="Item",
            price=None,
            currency=None,
            source="kleiderkreisel.de",
            thumbnail_url=None,
            listing_url="https://kleiderkreisel.de/item",
        )
        raw_pool = [listing, listing]
        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains",
            AsyncMock(return_value=([listing], True, raw_pool)),
        )
        filter_mock = AsyncMock(return_value=[listing])
        monkeypatch.setattr("backend.tools.product_finder.filter_category", filter_mock)

        await _lookup_secondhand_marketplaces("Mineral 89", "Vichy", ("kleiderkreisel.de",))

        filter_mock.assert_awaited_once_with(
            "Mineral 89",
            "Vichy",
            [listing],
            raw_pool,
            settings.product_max_listings_per_source,
            on_stage=None,
        )

    async def test_no_enrichment_stage_events_ever_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contrast with `TestLookupRetail`: this category never runs
        thumbnail/price enrichment, so neither stage event is ever emitted,
        no matter what `on_stage` sees from `_lookup_domains`/
        `filter_category`."""
        listing = ProductListing(
            type="used",
            title="Item",
            price=None,
            currency=None,
            source="kleiderkreisel.de",
            thumbnail_url=None,
            listing_url="https://kleiderkreisel.de/item",
        )

        async def fake_lookup_domains(name, brand, domains, listing_type, on_stage=None):
            if on_stage is not None:
                on_stage("domain_check", "Checking kleiderkreisel.de...")
            return [listing], True, [listing]

        async def fake_filter_category(name, brand, diversified, raw_pool, cap, on_stage=None):
            if on_stage is not None:
                on_stage("relevance_filter", "Checking listing relevance")
            return diversified

        monkeypatch.setattr(
            "backend.tools.product_finder._lookup_domains", AsyncMock(side_effect=fake_lookup_domains)
        )
        monkeypatch.setattr(
            "backend.tools.product_finder.filter_category", AsyncMock(side_effect=fake_filter_category)
        )

        events: list[str] = []

        def on_stage(stage: str, message: str) -> None:
            events.append(stage)

        await _lookup_secondhand_marketplaces(
            "Mineral 89", "Vichy", ("kleiderkreisel.de",), on_stage=on_stage
        )

        assert events == ["domain_check", "relevance_filter"]
        assert "thumbnail_enrichment" not in events
        assert "price_enrichment" not in events


def _aditem(
    *,
    title: str,
    price_text: str,
    href: str = "/s-anzeige/some-listing/123456789-25-1",
    img_src: str = "https://img.kleinanzeigen.de/api/v1/prod-ads/images/abc/def.jpg",
) -> str:
    """A single `article.aditem` card matching the markup verified against a
    live Kleinanzeigen search response during Task 10 implementation."""
    return f"""
    <article class="aditem" data-href="{href}">
      <div class="aditem-image">
        <img src="{img_src}" />
      </div>
      <div class="aditem-main">
        <div class="aditem-main--middle">
          <h2 class="text-module-begin"><a href="{href}">{title}</a></h2>
          <p class="aditem-main--middle--price-shipping--price">{price_text}</p>
        </div>
      </div>
    </article>
    """


def _kleinanzeigen_page(articles: list[str]) -> str:
    body = "\n".join(articles)
    return f"""<!doctype html>
    <html><body>
      <div class="srchrslt-content">
        {body}
      </div>
    </body></html>"""


def _make_kleinanzeigen_client(
    *,
    html: str | None = None,
    status_code: int = 200,
    get_side_effect: object = None,
) -> MagicMock:
    """A `httpx.Client(...)` stand-in (used as a context manager, matching
    `_search_kleinanzeigen_sync`'s `with httpx.Client(...) as client:`) whose
    `.get()` returns a response with `.text` set to `html`, or raises
    `get_side_effect` if given (e.g. a connection error)."""
    response = MagicMock()
    response.text = html if html is not None else ""
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} error", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None

    client = MagicMock()
    if get_side_effect is not None:
        client.get.side_effect = get_side_effect
    else:
        client.get.return_value = response

    client_cls = MagicMock()
    client_cls.return_value.__enter__.return_value = client
    client_cls.return_value.__exit__.return_value = False
    return client_cls


def _make_og_image_client(
    *,
    html: str | None = None,
    status_code: int = 200,
    get_side_effect: object = None,
) -> MagicMock:
    """An `httpx.AsyncClient(...)` stand-in (used as an async context
    manager, matching `_fetch_og_image`'s
    `async with httpx.AsyncClient(...) as client:`) whose `.get()` returns a
    response with `.text` set to `html`, or raises `get_side_effect` if
    given (e.g. a timeout)."""
    response = MagicMock()
    response.text = html if html is not None else ""
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} error", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None

    client = MagicMock()
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=response)

    client_cls = MagicMock()
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return client_cls


class TestFetchOgImage:
    """`_fetch_og_image()`: best-effort per-listing thumbnail enrichment for
    retail results, since neither Tavily nor DuckDuckGo return one. Must
    never raise — any failure (missing tag, HTTP error, timeout, connection
    error) degrades to `None`, matching `_lookup_retail`'s expectation that
    a broken listing page only costs that listing its thumbnail."""

    async def test_extracts_og_image_when_present(self) -> None:
        html = '<html><head><meta property="og:image" content="https://img.example.com/a.jpg"></head></html>'
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-a")

        assert result == "https://img.example.com/a.jpg"

    async def test_falls_back_to_twitter_image_when_og_image_absent(self) -> None:
        html = '<html><head><meta name="twitter:image" content="https://img.example.com/b.jpg"></head></html>'
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-b")

        assert result == "https://img.example.com/b.jpg"

    async def test_no_matching_tag_returns_none(self) -> None:
        html = "<html><head><title>No image here</title></head></html>"
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-c")

        assert result is None

    async def test_ld_json_product_image_fallback_when_no_og_or_twitter_tag(self) -> None:
        """Regression test: verified live that dm.de emits neither `og:image`
        nor `twitter:image`, but does emit a schema.org `Product` JSON-LD
        block with an `image` field."""
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@context": "https://schema.org", "@type": "Product", '
            '"name": "CeraVe Feuchtigkeitslotion", '
            '"image": "https://products.dm-static.com/cerave.jpg", '
            '"offers": {"@type": "Offer", "price": 12.45, "priceCurrency": "EUR"}}'
            "</script>"
            "</head></html>"
        )
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-f")

        assert result == "https://products.dm-static.com/cerave.jpg"

    async def test_ld_json_product_wrapped_in_graph_array(self) -> None:
        """Some sites wrap `Product` inside a top-level `@graph` array
        alongside unrelated types (`BreadcrumbList`, `WebSite`, etc.)."""
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@context": "https://schema.org", "@graph": ['
            '{"@type": "BreadcrumbList", "itemListElement": []}, '
            '{"@type": "Product", "name": "Toner", '
            '"image": {"@type": "ImageObject", "url": "https://example.de/toner.jpg"}}'
            "]}"
            "</script>"
            "</head></html>"
        )
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.example.de/toner")

        assert result == "https://example.de/toner.jpg"

    async def test_og_image_takes_priority_over_ld_json(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:image" content="https://img.example.com/og.jpg">'
            '<script type="application/ld+json">'
            '{"@type": "Product", "image": "https://img.example.com/ld.jpg"}'
            "</script>"
            "</head></html>"
        )
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-g")

        assert result == "https://img.example.com/og.jpg"

    async def test_malformed_ld_json_is_skipped_not_raised(self) -> None:
        html = (
            "<html><head>"
            '<script type="application/ld+json">{not valid json</script>'
            "</head></html>"
        )
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-h")

        assert result is None

    async def test_amazon_landing_image_fallback_when_no_og_or_twitter_tag(self) -> None:
        """Regression test: verified live that real Amazon product pages
        carry neither `og:image` nor `twitter:image` — Amazon embeds the
        image URL in a `data-a-dynamic-image` JSON attribute on
        `#landingImage` instead. Amazon dominates real retail result counts,
        so without this fallback, enrichment silently does nothing for most
        listings in practice."""
        html = (
            '<html><body>'
            '<img id="landingImage" data-a-dynamic-image=\''
            '{"https://m.media-amazon.com/images/I/61rMh74ohJL._AC_SY355_.jpg": [355, 355], '
            '"https://m.media-amazon.com/images/I/61rMh74ohJL._AC_SY450_.jpg": [450, 450]}'
            "'>"
            "</body></html>"
        )
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.amazon.de/dp/B0932WNWLL")

        assert result == "https://m.media-amazon.com/images/I/61rMh74ohJL._AC_SY355_.jpg"

    async def test_http_error_returns_none(self) -> None:
        client_cls = _make_og_image_client(status_code=404)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-missing")

        assert result is None

    async def test_connection_error_returns_none(self) -> None:
        client_cls = _make_og_image_client(
            get_side_effect=httpx.ConnectError("connection refused")
        )

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-d")

        assert result is None

    async def test_timeout_returns_none(self) -> None:
        client_cls = _make_og_image_client(
            get_side_effect=httpx.TimeoutException("timed out")
        )

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_og_image("https://www.dm.de/product-e")

        assert result is None


class TestExtractPriceFromHtml:
    """`_extract_price_from_html()`: best-effort price extraction from a
    retail listing page's full HTML, used as a fallback when
    `_extract_price()` found nothing in the search result's title/snippet
    text (see `_lookup_retail`'s price-enrichment step)."""

    def test_extracts_open_graph_product_price(self) -> None:
        html = (
            "<html><head>"
            '<meta property="product:price:amount" content="19.99">'
            '<meta property="product:price:currency" content="EUR">'
            "</head></html>"
        )
        assert _extract_price_from_html(html) == (19.99, "EUR")

    def test_extracts_schema_org_itemprop_price(self) -> None:
        html = (
            "<html><body>"
            '<span itemprop="price" content="24.50"></span>'
            '<span itemprop="priceCurrency" content="EUR"></span>'
            "</body></html>"
        )
        assert _extract_price_from_html(html) == (24.50, "EUR")

    def test_extracts_ld_json_product_offer_price(self) -> None:
        """Regression test: verified live that dm.de exposes price via a
        schema.org `Product`/`Offer` JSON-LD block rather than either of the
        formats above."""
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@context": "https://schema.org", "@type": "Product", '
            '"name": "CeraVe Feuchtigkeitslotion", '
            '"offers": {"@type": "Offer", "price": 12.45, "priceCurrency": "EUR"}}'
            "</script>"
            "</head></html>"
        )
        assert _extract_price_from_html(html) == (12.45, "EUR")

    def test_extracts_ld_json_price_from_first_offer_in_list(self) -> None:
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type": "Product", "offers": ['
            '{"@type": "Offer", "price": 9.99, "priceCurrency": "EUR"}, '
            '{"@type": "Offer", "price": 11.99, "priceCurrency": "EUR"}'
            "]}"
            "</script>"
            "</head></html>"
        )
        assert _extract_price_from_html(html) == (9.99, "EUR")

    def test_extracts_ld_json_price_given_as_string(self) -> None:
        html = (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type": "Product", "offers": {"@type": "Offer", "price": "7,50", '
            '"priceCurrency": "EUR"}}'
            "</script>"
            "</head></html>"
        )
        assert _extract_price_from_html(html) == (7.50, "EUR")

    def test_meta_tag_price_takes_priority_over_ld_json(self) -> None:
        html = (
            "<html><head>"
            '<meta property="product:price:amount" content="19.99">'
            '<meta property="product:price:currency" content="EUR">'
            '<script type="application/ld+json">'
            '{"@type": "Product", "offers": {"@type": "Offer", "price": 5.00, '
            '"priceCurrency": "EUR"}}'
            "</script>"
            "</head></html>"
        )
        assert _extract_price_from_html(html) == (19.99, "EUR")

    def test_falls_back_to_amazon_offscreen_price_text(self) -> None:
        html = (
            "<html><body>"
            '<span class="a-price"><span class="a-offscreen">12,99 €</span></span>'
            "</body></html>"
        )
        assert _extract_price_from_html(html) == (12.99, "EUR")

    def test_no_matching_price_anywhere_returns_none_none(self) -> None:
        html = "<html><body><p>No price on this page</p></body></html>"
        assert _extract_price_from_html(html) == (None, None)


class TestFetchListingPrice:
    """`_fetch_listing_price()`: best-effort per-listing price re-fetch used
    only when the search snippet didn't yield one (Amazon's snippets rarely
    do). Must never raise — any failure degrades to `(None, None)`, matching
    `_lookup_retail`'s expectation that a broken listing page only costs
    that listing its price."""

    async def test_extracts_price_when_present(self) -> None:
        html = (
            "<html><body>"
            '<span class="a-price"><span class="a-offscreen">19,99 €</span></span>'
            "</body></html>"
        )
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_listing_price("https://www.amazon.de/dp/B0932WNWLL")

        assert result == (19.99, "EUR")

    async def test_no_matching_price_returns_none_none(self) -> None:
        html = "<html><body><p>No price here</p></body></html>"
        client_cls = _make_og_image_client(html=html)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_listing_price("https://www.dm.de/product-c")

        assert result == (None, None)

    async def test_http_error_returns_none_none(self) -> None:
        client_cls = _make_og_image_client(status_code=404)

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_listing_price("https://www.dm.de/product-missing")

        assert result == (None, None)

    async def test_connection_error_returns_none_none(self) -> None:
        client_cls = _make_og_image_client(
            get_side_effect=httpx.ConnectError("connection refused")
        )

        with patch("backend.tools.product_finder.httpx.AsyncClient", client_cls):
            result = await _fetch_listing_price("https://www.dm.de/product-d")

        assert result == (None, None)


class TestLookupKleinanzeigen:
    """Task 10: `_lookup_kleinanzeigen()`, with `httpx.Client` mocked at the
    boundary it's constructed from (`backend.tools.product_finder.httpx.Client`)
    so no real network access is used, per Req 10's Kleinanzeigen-specific
    criteria and Req 14's never-raise contract. The Germany-gate itself
    (whether this function is called at all) lives in the `/find` endpoint
    (Task 11), not here."""

    async def test_success_maps_results_to_used_listings_with_price_extraction(
        self,
    ) -> None:
        html = _kleinanzeigen_page(
            [
                _aditem(
                    title="Vichy Mineral 89 Serum",
                    price_text="15 €",
                    href="/s-anzeige/vichy-mineral-89-serum/123456789-25-1",
                    img_src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/aaa/bbb.jpg",
                ),
                _aditem(
                    title="La Roche-Posay Creme",
                    price_text="35 € VB",
                    href="/s-anzeige/la-roche-posay-creme/987654321-25-2",
                    img_src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/ccc/ddd.jpg",
                ),
            ]
        )
        client_cls = _make_kleinanzeigen_client(html=html)

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert ok is True
        assert len(listings) == 2

        first, second = listings
        assert first.type == "used"
        assert first.source == "Kleinanzeigen"
        assert first.currency == "EUR"
        assert first.title == "Vichy Mineral 89 Serum"
        assert first.price == 15.0
        assert first.thumbnail_url == "https://img.kleinanzeigen.de/api/v1/prod-ads/images/aaa/bbb.jpg"
        assert first.listing_url == "https://www.kleinanzeigen.de/s-anzeige/vichy-mineral-89-serum/123456789-25-1"

        assert second.type == "used"
        assert second.source == "Kleinanzeigen"
        assert second.title == "La Roche-Posay Creme"
        # "35 € VB" still yields a clean numeric price alongside the
        # negotiable marker.
        assert second.price == 35.0
        assert second.currency == "EUR"

    async def test_negotiable_price_with_no_numeric_amount_is_none(self) -> None:
        html = _kleinanzeigen_page(
            [_aditem(title="Dyson Airwrap", price_text="VB")]
        )
        client_cls = _make_kleinanzeigen_client(html=html)

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            listings, ok = await _lookup_kleinanzeigen("Airwrap", "Dyson")

        assert ok is True
        assert len(listings) == 1
        assert listings[0].price is None
        # Currency is still EUR (a Kleinanzeigen-fixed market) even without a
        # clean numeric price.
        assert listings[0].currency == "EUR"
        assert listings[0].title == "Dyson Airwrap"

    async def test_empty_response_body_returns_empty_and_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client_cls = _make_kleinanzeigen_client(html="")

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert listings == []
        assert ok is False
        assert "kleinanzeigen" in caplog.text.lower()

    async def test_html_with_no_matching_selectors_returns_empty_and_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Well-formed HTML, but none of it matches `article.aditem` (e.g. the
        # site's markup drifted, or we were served a bot-gated placeholder
        # page) - must not crash, and must not be reported as a confident
        # zero-result success.
        html = "<!doctype html><html><body><p>Unexpected page layout</p></body></html>"
        client_cls = _make_kleinanzeigen_client(html=html)

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert listings == []
        assert ok is False
        assert "kleinanzeigen" in caplog.text.lower()

    async def test_http_error_returns_empty_and_false(self, caplog: pytest.LogCaptureFixture) -> None:
        client_cls = _make_kleinanzeigen_client(status_code=503)

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert listings == []
        assert ok is False
        assert "kleinanzeigen" in caplog.text.lower()

    async def test_connection_error_returns_empty_and_false(self, caplog: pytest.LogCaptureFixture) -> None:
        client_cls = _make_kleinanzeigen_client(
            get_side_effect=httpx.ConnectError("connection refused")
        )

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert listings == []
        assert ok is False
        assert "kleinanzeigen" in caplog.text.lower()

    async def test_timeout_returns_empty_and_false_with_no_retry(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(settings, "product_lookup_timeout_seconds", 0.05)

        def _slow_get(*args: object, **kwargs: object) -> MagicMock:
            import time

            time.sleep(0.5)
            response = MagicMock()
            response.text = _kleinanzeigen_page([_aditem(title="Slow", price_text="5 €")])
            response.raise_for_status.return_value = None
            return response

        client_cls = _make_kleinanzeigen_client()
        client_cls.return_value.__enter__.return_value.get.side_effect = _slow_get

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert listings == []
        assert ok is False
        assert "kleinanzeigen" in caplog.text.lower()
        # No retry: the client is only ever constructed once.
        client_cls.assert_called_once()

    async def test_malformed_parsed_items_returns_empty_and_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression test (sibling of Vinted's/retail's malformed-response
        cases): `_search_kleinanzeigen_sync()` succeeding but returning items
        that don't have the expected dict shape must be caught by the same
        try/except as the network call, not just it — Req 14's never-raise
        contract covers result *processing* too."""
        with patch(
            "backend.tools.product_finder._search_kleinanzeigen_sync",
            return_value=["not-a-dict"],
        ):
            with caplog.at_level("ERROR"):
                listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert listings == []
        assert ok is False
        assert "kleinanzeigen" in caplog.text.lower()

    async def test_results_are_capped_to_configured_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "product_max_listings_per_source", 3)
        html = _kleinanzeigen_page(
            [
                _aditem(
                    title=f"Item {i}",
                    price_text="5 €",
                    href=f"/s-anzeige/item-{i}/{i}-25-1",
                )
                for i in range(6)
            ]
        )
        client_cls = _make_kleinanzeigen_client(html=html)

        with patch("backend.tools.product_finder.httpx.Client", client_cls):
            listings, ok = await _lookup_kleinanzeigen("Mineral 89", "Vichy")

        assert ok is True
        assert len(listings) == 3


class TestFindProductEndpoint:
    """GET /api/products/find — cache short-circuit, the discovery gate (Req
    12.3), concurrent Vinted/secondhand-marketplace/retail/Kleinanzeigen
    orchestration, and failure handling (Req 7, 8, 9, 12, 13, 14). Mirrors
    `tests/test_api_routines.py`'s house style: `get_current_user` is
    overridden to a fixed user_id, and the real `ProfileStore`/
    `ProductCacheStore`/`SourceDiscoveryStore` (per-test temporary SQLite)
    are used instead of mocks, so only `get_or_discover_sources` and the four
    lookup coroutines are mocked at the module boundary."""

    @pytest.fixture
    def cache_store(self, tmp_path):
        return ProductCacheStore(db_path=str(tmp_path / "product_cache.db"))

    @pytest.fixture
    def discovery_store(self, tmp_path):
        return SourceDiscoveryStore(db_path=str(tmp_path / "source_discovery.db"))

    @staticmethod
    def _make_client(
        profile_store, cache_store, discovery_store, user_id: str = "uid-alice"
    ) -> TestClient:
        app = FastAPI()
        app.include_router(product_finder_router)
        app.dependency_overrides[get_profile_store] = lambda: profile_store
        app.dependency_overrides[get_product_cache_store] = lambda: cache_store
        app.dependency_overrides[get_source_discovery_store] = lambda: discovery_store
        app.dependency_overrides[get_current_user] = lambda: user_id
        return TestClient(app)

    @staticmethod
    def _make_unauthenticated_client(profile_store, cache_store, discovery_store) -> TestClient:
        # No get_current_user override: the real JWTAuthMiddleware guards the
        # route, so a request without a Bearer token never even reaches the
        # endpoint's dependencies.
        app = FastAPI()
        app.add_middleware(JWTAuthMiddleware)
        app.include_router(product_finder_router)
        app.dependency_overrides[get_profile_store] = lambda: profile_store
        app.dependency_overrides[get_product_cache_store] = lambda: cache_store
        app.dependency_overrides[get_source_discovery_store] = lambda: discovery_store
        return TestClient(app)

    @staticmethod
    def _setup_user(profile_store, user_id: str = "uid-alice", location: str | None = "Germany") -> None:
        profile_store.get_or_create_user_by_id(user_id, f"{user_id}@example.com", user_id)
        if location is not None:
            profile_store.update_location(user_id, location)

    @staticmethod
    def _listing(source: str, type_: str = "used") -> ProductListing:
        return ProductListing(
            type=type_,
            title=f"{source} item",
            price=9.99,
            currency="EUR",
            source=source,
            thumbnail_url=None,
            listing_url=f"https://example.com/{source.lower()}",
        )

    @staticmethod
    def _discovered(
        retailer_domains: tuple[str, ...] = (),
        vinted_domain: str | None = None,
        secondhand_domains: tuple[str, ...] = (),
    ) -> DiscoveredSources:
        return DiscoveredSources(
            retailer_domains=retailer_domains,
            vinted_domain=vinted_domain,
            secondhand_domains=secondhand_domains,
        )

    @staticmethod
    def _cache_key(
        name: str, brand: str | None, normalized_location: str, source: str | None
    ) -> str:
        return ProductCacheStore.make_key(name, brand, f"{normalized_location}:{source or 'all'}")

    # ── Baseline behavior (cache, per-source scoping, failure handling) ─────

    def test_cache_hit_skips_all_lookups_and_discovery(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        cached = ProductFindResponse(
            listings=[self._listing("Vinted")], retail_ok=True, secondhand_ok=True
        )
        cache_key = self._cache_key("Retinol Serum", None, "germany", None)
        cache_store.set(cache_key, cached, name="Retinol Serum", brand=None, market_code="germany:all")

        client = self._make_client(profile_store, cache_store, discovery_store)
        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        assert response.json() == cached.model_dump()
        discover_mock.assert_not_called()
        vinted_mock.assert_not_called()
        marketplaces_mock.assert_not_called()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

    def test_cache_miss_non_germany_skips_kleinanzeigen(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Nowhereland")
        vinted_listing = self._listing("Vinted")
        retail_listing = self._listing("example.com", type_="new")
        discovered = self._discovered(retailer_domains=("example.com",), vinted_domain="vinted.com")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([vinted_listing], True)),
            ) as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([retail_listing], True)),
            ) as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "brand": "CeraVe"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is True
        assert body["secondhand_ok"] is True
        titles = {listing["source"] for listing in body["listings"]}
        assert titles == {"Vinted", "example.com"}
        vinted_mock.assert_awaited_once()
        retail_mock.assert_awaited_once()
        kleinanzeigen_mock.assert_not_called()

    def test_cache_miss_germany_calls_all_sources(self, profile_store, cache_store, discovery_store):
        self._setup_user(profile_store, location="Germany")
        vinted_listing = self._listing("Vinted")
        marketplace_listing = self._listing("kleiderkreisel.de")
        retail_listing = self._listing("dm.de", type_="new")
        kleinanzeigen_listing = self._listing("Kleinanzeigen")
        discovered = self._discovered(
            retailer_domains=("dm.de",),
            vinted_domain="vinted.de",
            secondhand_domains=("kleiderkreisel.de",),
        )

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([vinted_listing], True)),
            ) as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([marketplace_listing], True)),
            ) as marketplaces_mock,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([retail_listing], True)),
            ) as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ) as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is True
        assert body["secondhand_ok"] is True
        sources = {listing["source"] for listing in body["listings"]}
        assert sources == {"Vinted", "kleiderkreisel.de", "dm.de", "Kleinanzeigen"}
        vinted_mock.assert_awaited_once()
        marketplaces_mock.assert_awaited_once()
        retail_mock.assert_awaited_once()
        kleinanzeigen_mock.assert_awaited_once()

    def test_partial_failure_returns_200_with_ok_flags_and_is_cached(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        vinted_listing = self._listing("Vinted")
        kleinanzeigen_listing = self._listing("Kleinanzeigen")
        discovered = self._discovered(retailer_domains=("dm.de",), vinted_domain="vinted.de")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([vinted_listing], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_retail", AsyncMock(return_value=([], False))
            ) as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ),
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is False
        assert body["secondhand_ok"] is True
        sources = {listing["source"] for listing in body["listings"]}
        assert sources == {"Vinted", "Kleinanzeigen"}
        assert retail_mock.await_count == 1

        # At least one source succeeded, so the response must be cached.
        cache_key = self._cache_key("Retinol Serum", None, "germany", None)
        cached = cache_store.get(cache_key)
        assert cached is not None
        assert cached.retail_ok is False
        assert cached.secondhand_ok is True

    def test_total_failure_returns_200_but_is_not_cached(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        discovered = self._discovered(
            retailer_domains=("dm.de",),
            vinted_domain="vinted.de",
            secondhand_domains=("kleiderkreisel.de",),
        )

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand", AsyncMock(return_value=([], False))
            ) as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], False)),
            ) as marketplaces_mock,
            patch(
                "backend.tools.product_finder._lookup_retail", AsyncMock(return_value=([], False))
            ) as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([], False)),
            ) as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

            assert response.status_code == 200
            body = response.json()
            assert body["retail_ok"] is False
            assert body["secondhand_ok"] is False
            assert body["listings"] == []

            cache_key = self._cache_key("Retinol Serum", None, "germany", None)
            assert cache_store.get(cache_key) is None

            # Re-invoking must hit the lookups again, not a frozen cache entry.
            response2 = client.get("/api/products/find", params={"name": "Retinol Serum"})
            assert response2.status_code == 200
            assert vinted_mock.await_count == 2
            assert marketplaces_mock.await_count == 2
            assert retail_mock.await_count == 2
            assert kleinanzeigen_mock.await_count == 2

    def test_unauthenticated_request_is_rejected(self, profile_store, cache_store, discovery_store):
        client = self._make_unauthenticated_client(profile_store, cache_store, discovery_store)

        response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 401

    def test_brand_omitted_is_passed_through_as_none(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        discovered = self._discovered(
            retailer_domains=("dm.de",),
            vinted_domain="vinted.de",
            secondhand_domains=("kleiderkreisel.de",),
        )

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand", AsyncMock(return_value=([], True))
            ) as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], True)),
            ) as marketplaces_mock,
            patch(
                "backend.tools.product_finder._lookup_retail", AsyncMock(return_value=([], True))
            ) as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([], True)),
            ) as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        for mock in (vinted_mock, marketplaces_mock, retail_mock, kleinanzeigen_mock):
            args = mock.await_args.args
            assert args[0] == "Retinol Serum"
            assert args[1] is None

        cache_key = self._cache_key("Retinol Serum", None, "germany", None)
        assert cache_store.get(cache_key) is not None

    def test_source_retail_only_calls_retail_lookup(
        self, profile_store, cache_store, discovery_store
    ):
        """The `source` filter (added so the frontend can fire one request
        per source in parallel and render each as it lands, rather than the
        whole popover waiting on the slowest source) restricts execution to
        exactly the requested lookup."""
        self._setup_user(profile_store, location="Germany")
        retail_listing = self._listing("dm.de", type_="new")
        discovered = self._discovered(
            retailer_domains=("dm.de",),
            vinted_domain="vinted.de",
            secondhand_domains=("kleiderkreisel.de",),
        )

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ) as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([retail_listing], True)),
            ) as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "retail"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is True
        assert body["secondhand_ok"] is False
        assert {listing["source"] for listing in body["listings"]} == {"dm.de"}
        discover_mock.assert_awaited_once()
        retail_mock.assert_awaited_once()
        vinted_mock.assert_not_called()
        marketplaces_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

    def test_source_vinted_only_calls_secondhand_and_marketplace_lookups(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        vinted_listing = self._listing("Vinted")
        discovered = self._discovered(retailer_domains=("dm.de",), vinted_domain="vinted.de")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([vinted_listing], True)),
            ) as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "vinted"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is False
        assert body["secondhand_ok"] is True
        assert {listing["source"] for listing in body["listings"]} == {"Vinted"}
        vinted_mock.assert_awaited_once()
        # discovered.secondhand_domains is empty in this scenario, so the
        # marketplace sub-lookup is never attempted (Req 3.5's "not
        # attempted" degrade, not a crash).
        marketplaces_mock.assert_not_called()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

    def test_source_kleinanzeigen_only_calls_kleinanzeigen_lookup_on_germany_location(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        kleinanzeigen_listing = self._listing("Kleinanzeigen")

        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ) as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "kleinanzeigen"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["secondhand_ok"] is True
        assert {listing["source"] for listing in body["listings"]} == {"Kleinanzeigen"}
        kleinanzeigen_mock.assert_awaited_once()
        discover_mock.assert_not_called()
        vinted_mock.assert_not_called()
        retail_mock.assert_not_called()

    def test_source_kleinanzeigen_on_non_germany_location_short_circuits_without_network_call(
        self, profile_store, cache_store, discovery_store
    ):
        """Since the frontend always fires a `source=kleinanzeigen` request
        regardless of the user's location (it doesn't know the location's
        Germany-ness ahead of time), this must degrade to an empty/
        `ok=False` result with no network call at all, not an error."""
        self._setup_user(profile_store, location="Nowhereland")

        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "kleinanzeigen"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["listings"] == []
        assert body["retail_ok"] is False
        assert body["secondhand_ok"] is False
        discover_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()
        vinted_mock.assert_not_called()
        retail_mock.assert_not_called()

    def test_per_source_and_combined_requests_use_separate_cache_entries(
        self, profile_store, cache_store, discovery_store
    ):
        """The cache key folds `source` into the location slot so a
        `source=retail` request and a combined (`source=None`) request for
        the same product/location never collide or serve each other's
        cached response."""
        self._setup_user(profile_store, location="Germany")
        retail_listing = self._listing("dm.de", type_="new")
        vinted_listing = self._listing("Vinted")
        discovered = self._discovered(retailer_domains=("dm.de",), vinted_domain="vinted.de")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([vinted_listing], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([retail_listing], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([], True)),
            ),
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            retail_only = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "retail"}
            )
            combined = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert {listing["source"] for listing in retail_only.json()["listings"]} == {"dm.de"}
        assert {listing["source"] for listing in combined.json()["listings"]} == {
            "dm.de",
            "Vinted",
        }

        retail_key = self._cache_key("Retinol Serum", None, "germany", "retail")
        all_key = self._cache_key("Retinol Serum", None, "germany", None)
        assert retail_key != all_key
        assert cache_store.get(retail_key) is not None
        assert cache_store.get(all_key) is not None

    # ── Discovery gate (Req 12.3) and discovery-outcome-driven scoping ──────

    def test_discovery_runs_before_any_lookup_coroutine_is_constructed(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        manager = MagicMock()
        discover_mock = AsyncMock(
            return_value=self._discovered(
                retailer_domains=("dm.de",),
                vinted_domain="vinted.de",
                secondhand_domains=("kleiderkreisel.de",),
            )
        )
        vinted_mock = AsyncMock(return_value=([], True))
        marketplaces_mock = AsyncMock(return_value=([], True))
        retail_mock = AsyncMock(return_value=([], True))
        kleinanzeigen_mock = AsyncMock(return_value=([], True))
        manager.attach_mock(discover_mock, "discover")
        manager.attach_mock(vinted_mock, "vinted")
        manager.attach_mock(marketplaces_mock, "marketplaces")
        manager.attach_mock(retail_mock, "retail")
        manager.attach_mock(kleinanzeigen_mock, "kleinanzeigen")

        with (
            patch("backend.tools.product_finder.get_or_discover_sources", discover_mock),
            patch("backend.tools.product_finder._lookup_secondhand", vinted_mock),
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces", marketplaces_mock),
            patch("backend.tools.product_finder._lookup_retail", retail_mock),
            patch("backend.tools.product_finder._lookup_kleinanzeigen", kleinanzeigen_mock),
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        # `manager.mock_calls` records call order by when each mock was
        # *invoked* (i.e. when its coroutine object was constructed), not
        # when it was awaited — exactly what Req 12.3 requires: discovery
        # must complete before any lookup coroutine is even constructed.
        call_names = [call[0] for call in manager.mock_calls]
        assert call_names[0] == "discover"
        assert set(call_names[1:]) == {"vinted", "marketplaces", "retail", "kleinanzeigen"}

    def test_discovery_zero_retailer_domains_skips_retail_lookup(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        discovered = self._discovered(
            retailer_domains=(), vinted_domain="vinted.de", secondhand_domains=("kleiderkreisel.de",)
        )

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([self._listing("Vinted")], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([self._listing("kleiderkreisel.de")], True)),
            ),
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([], True)),
            ),
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is False
        retail_mock.assert_not_called()

    def test_discovery_zero_vinted_and_marketplace_domains_secondhand_ok_depends_on_kleinanzeigen_for_germany(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        discovered = self._discovered(retailer_domains=("dm.de",))
        kleinanzeigen_listing = self._listing("Kleinanzeigen")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([self._listing("dm.de", type_="new")], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ),
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["secondhand_ok"] is True
        vinted_mock.assert_not_called()
        marketplaces_mock.assert_not_called()

    def test_discovery_zero_vinted_and_marketplace_domains_non_germany_secondhand_ok_false(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Nowhereland")
        discovered = self._discovered(retailer_domains=("example.com",))

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([self._listing("example.com", type_="new")], True)),
            ),
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["secondhand_ok"] is False
        vinted_mock.assert_not_called()
        marketplaces_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

    def test_total_discovery_failure_non_germany(self, profile_store, cache_store, discovery_store):
        self._setup_user(profile_store, location="Nowhereland")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=DiscoveredSources()),
            ),
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is False
        assert body["secondhand_ok"] is False
        assert body["listings"] == []
        vinted_mock.assert_not_called()
        marketplaces_mock.assert_not_called()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

        cache_key = self._cache_key("Retinol Serum", None, "nowhereland", None)
        assert cache_store.get(cache_key) is None

    def test_total_discovery_failure_germany_uses_seed_domains_and_kleinanzeigen_still_attempted(
        self, profile_store, cache_store, discovery_store
    ):
        """A `get_or_discover_sources()` failure for Germany already resolves
        (per its own contract, tested in `tests/test_product_source_discovery.py`)
        to the literal seed `DiscoveredSources` — this test asserts
        `find_product()`'s consumption of that result: the seed domains feed
        retail/Vinted, and Kleinanzeigen is attempted regardless (Req 8.1's
        gate is `is_germany` alone, independent of discovery's outcome)."""
        self._setup_user(profile_store, location="Germany")
        seed = self._discovered(
            retailer_domains=_GERMANY_SEED_RETAILER_DOMAINS,
            vinted_domain=_GERMANY_SEED_VINTED_DOMAIN,
            secondhand_domains=(),
        )
        kleinanzeigen_listing = self._listing("Kleinanzeigen")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources", AsyncMock(return_value=seed)
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([self._listing("Vinted")], True)),
            ) as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([self._listing("dm.de", type_="new")], True)),
            ) as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ) as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert response.status_code == 200
        body = response.json()
        assert body["retail_ok"] is True
        assert body["secondhand_ok"] is True
        vinted_mock.assert_awaited_once_with(
            "Retinol Serum", None, _GERMANY_SEED_VINTED_DOMAIN
        )
        retail_mock.assert_awaited_once_with(
            "Retinol Serum", None, _GERMANY_SEED_RETAILER_DOMAINS, on_stage=None
        )
        kleinanzeigen_mock.assert_awaited_once()

    @pytest.mark.parametrize("location", ["Germany", "Nowhereland"])
    def test_source_kleinanzeigen_never_calls_discovery(
        self, profile_store, cache_store, discovery_store, location
    ):
        self._setup_user(profile_store, location=location)

        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([self._listing("Kleinanzeigen")], True)),
            ) as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "kleinanzeigen"}
            )

        assert response.status_code == 200
        discover_mock.assert_not_called()
        vinted_mock.assert_not_called()
        retail_mock.assert_not_called()
        if location == "Germany":
            kleinanzeigen_mock.assert_awaited_once()
        else:
            kleinanzeigen_mock.assert_not_called()

    def test_normalized_identical_locations_share_one_product_cache_entry(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        discovered = self._discovered(retailer_domains=("dm.de",), vinted_domain="vinted.de")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([self._listing("Vinted")], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([self._listing("dm.de", type_="new")], True)),
            ),
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([], True)),
            ),
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            first = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert first.status_code == 200

        # "Germany" vs "  germany " normalize to the same string (Req 6.3) -
        # a second request for the differently-spelled-but-equivalent
        # location must hit the same product-listing cache entry Alice's
        # first request populated, so none of the lookups (bare MagicMocks
        # that would fail loudly if awaited) are ever invoked.
        profile_store.update_location("uid-alice", "  germany ")
        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            second = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert second.status_code == 200
        assert first.json() == second.json()
        discover_mock.assert_not_called()
        vinted_mock.assert_not_called()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

    def test_different_unrecognized_spellings_do_not_share_cache_entry(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Atlantis")
        discovered = self._discovered(retailer_domains=("example.com",))

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ) as discover_mock_1,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([self._listing("example.com", type_="new")], True)),
            ),
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            first = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert first.status_code == 200
        discover_mock_1.assert_called_once()
        vinted_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()

        # "Atlantis" vs "Atlantis Prime" normalize to different strings, so
        # this is a genuine cache miss for the second request too - discovery
        # runs again, and a second, distinct cache entry is created.
        profile_store.update_location("uid-alice", "Atlantis Prime")
        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ) as discover_mock_2,
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(return_value=([self._listing("example.com", type_="new")], True)),
            ),
        ):
            second = client.get("/api/products/find", params={"name": "Retinol Serum"})

        assert second.status_code == 200
        discover_mock_2.assert_called_once()

        key_first = self._cache_key("Retinol Serum", None, "atlantis", None)
        key_second = self._cache_key("Retinol Serum", None, "atlantis prime", None)
        assert key_first != key_second
        assert cache_store.get(key_first) is not None
        assert cache_store.get(key_second) is not None

    def test_source_vinted_combines_vinted_and_secondhand_marketplace_results(
        self, profile_store, cache_store, discovery_store
    ):
        self._setup_user(profile_store, location="Germany")
        discovered = self._discovered(vinted_domain="vinted.de", secondhand_domains=("kleiderkreisel.de",))
        vinted_listing = self._listing("Vinted")
        marketplace_listing = self._listing("kleiderkreisel.de")

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch(
                "backend.tools.product_finder._lookup_secondhand",
                AsyncMock(return_value=([vinted_listing], True)),
            ) as vinted_mock,
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([marketplace_listing], True)),
            ) as marketplaces_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            client = self._make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "source": "vinted"}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["secondhand_ok"] is True
        assert body["retail_ok"] is False
        sources = {listing["source"] for listing in body["listings"]}
        assert sources == {"Vinted", "kleiderkreisel.de"}
        assert all(listing["type"] == "used" for listing in body["listings"])
        vinted_mock.assert_awaited_once()
        marketplaces_mock.assert_awaited_once()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()
