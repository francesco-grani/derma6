"""Tests for the `GET /api/products/find?stream=true` SSE transport (Part B
of product-finder-streaming, Task 8) — `QueuedStageEmitter`, `_sse`,
`_resolve_product_find`'s extraction, and `find_product`'s `stream` branch.

Mirrors `tests/test_api_products.py::TestFindProductEndpoint`'s house style
(a fresh `FastAPI()` app per test, `get_current_user` overridden to a fixed
user_id, real per-test-temporary-SQLite `ProfileStore`/`ProductCacheStore`/
`SourceDiscoveryStore`, only the network/LLM-boundary lookup coroutines and
`get_or_discover_sources` mocked at the module boundary) — extended here
with SSE-frame parsing (splitting the response body on `data: ...\n\n`,
matching the frontend's own parsing convention, Requirements Review Note
point 2) and a `stream=true` query parameter on every request.
"""

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

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
from backend.tools.product_finder import _resolve_product_find
from backend.tools.product_finder import router as product_finder_router


def _parse_sse(text: str) -> list[dict | str]:
    """Split an SSE response body on `\n\n`, matching the frontend's own
    parsing convention (`useProductFind`/`useStreamChat.ts`); returns each
    frame's decoded JSON payload, or the literal string `"[DONE]"` for the
    terminal sentinel."""
    frames: list[dict | str] = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip("\n")
        if not chunk.startswith("data: "):
            continue
        raw = chunk[len("data: ") :]
        frames.append("[DONE]" if raw == "[DONE]" else json.loads(raw))
    return frames


def _make_client(profile_store, cache_store, discovery_store, user_id: str = "uid-alice") -> TestClient:
    app = FastAPI()
    app.include_router(product_finder_router)
    app.dependency_overrides[get_profile_store] = lambda: profile_store
    app.dependency_overrides[get_product_cache_store] = lambda: cache_store
    app.dependency_overrides[get_source_discovery_store] = lambda: discovery_store
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _make_unauthenticated_client(profile_store, cache_store, discovery_store) -> TestClient:
    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware)
    app.include_router(product_finder_router)
    app.dependency_overrides[get_profile_store] = lambda: profile_store
    app.dependency_overrides[get_product_cache_store] = lambda: cache_store
    app.dependency_overrides[get_source_discovery_store] = lambda: discovery_store
    return TestClient(app)


def _setup_user(profile_store, user_id: str = "uid-alice", location: str | None = "Germany") -> None:
    profile_store.get_or_create_user_by_id(user_id, f"{user_id}@example.com", user_id)
    if location is not None:
        profile_store.update_location(user_id, location)


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


def _cache_key(name: str, brand: str | None, normalized_location: str, source: str | None) -> str:
    return ProductCacheStore.make_key(name, brand, f"{normalized_location}:{source or 'all'}")


@pytest.fixture
def cache_store(tmp_path):
    return ProductCacheStore(db_path=str(tmp_path / "product_cache.db"))


@pytest.fixture
def discovery_store(tmp_path):
    return SourceDiscoveryStore(db_path=str(tmp_path / "source_discovery.db"))


class TestResolveProductFindRegression:
    """Req 6.2/Focus-Area-5: `_resolve_product_find(..., on_stage=None)` must
    reproduce the non-streaming endpoint's behavior exactly, since
    `find_product`'s `stream=false` path calls it directly with no other
    logic in between. Verified here by running the identical mocked scenario
    through both the HTTP endpoint (`stream=false`) and a direct
    `_resolve_product_find` call against separate-but-identically-seeded
    stores, and asserting the two responses are byte-for-byte identical."""

    def test_direct_call_matches_non_streaming_endpoint_byte_for_byte(
        self, profile_store, tmp_path
    ) -> None:
        _setup_user(profile_store, location="Germany")
        vinted_listing = _listing("Vinted")
        marketplace_listing = _listing("kleiderkreisel.de")
        retail_listing = _listing("dm.de", type_="new")
        kleinanzeigen_listing = _listing("Kleinanzeigen")
        discovered = _discovered(
            retailer_domains=("dm.de",),
            vinted_domain="vinted.de",
            secondhand_domains=("kleiderkreisel.de",),
        )

        def _apply_patches(stack: ExitStack) -> None:
            stack.enter_context(
                patch(
                    "backend.tools.product_finder.get_or_discover_sources",
                    AsyncMock(return_value=discovered),
                )
            )
            stack.enter_context(
                patch(
                    "backend.tools.product_finder._lookup_secondhand",
                    AsyncMock(return_value=([vinted_listing], True)),
                )
            )
            stack.enter_context(
                patch(
                    "backend.tools.product_finder._lookup_secondhand_marketplaces",
                    AsyncMock(return_value=([marketplace_listing], True)),
                )
            )
            stack.enter_context(
                patch(
                    "backend.tools.product_finder._lookup_retail",
                    AsyncMock(return_value=([retail_listing], True)),
                )
            )
            stack.enter_context(
                patch(
                    "backend.tools.product_finder._lookup_kleinanzeigen",
                    AsyncMock(return_value=([kleinanzeigen_listing], True)),
                )
            )

        # Path 1: the HTTP endpoint, stream=false (today's unchanged contract).
        cache_store_1 = ProductCacheStore(db_path=str(tmp_path / "cache1.db"))
        discovery_store_1 = SourceDiscoveryStore(db_path=str(tmp_path / "discovery1.db"))
        client = _make_client(profile_store, cache_store_1, discovery_store_1)
        with ExitStack() as stack:
            _apply_patches(stack)
            http_response = client.get("/api/products/find", params={"name": "Retinol Serum"})
        assert http_response.status_code == 200

        # Path 2: _resolve_product_find called directly, on_stage=None.
        cache_store_2 = ProductCacheStore(db_path=str(tmp_path / "cache2.db"))
        discovery_store_2 = SourceDiscoveryStore(db_path=str(tmp_path / "discovery2.db"))
        profile = profile_store.get_profile("uid-alice")
        with ExitStack() as stack:
            _apply_patches(stack)
            direct_response: ProductFindResponse = asyncio.run(
                _resolve_product_find(
                    "Retinol Serum", None, None, profile, cache_store_2, discovery_store_2
                )
            )

        assert direct_response.model_dump() == http_response.json()


class TestFindProductStreamCacheHit:
    def test_cache_hit_yields_exactly_one_result_frame_then_done(
        self, profile_store, cache_store, discovery_store
    ) -> None:
        _setup_user(profile_store, location="Germany")
        cached = ProductFindResponse(
            listings=[_listing("Vinted")], retail_ok=True, secondhand_ok=True
        )
        cache_key = _cache_key("Retinol Serum", None, "germany", None)
        cache_store.set(cache_key, cached, name="Retinol Serum", brand=None, market_code="germany:all")

        client = _make_client(profile_store, cache_store, discovery_store)
        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_secondhand_marketplaces") as marketplaces_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch("backend.tools.product_finder._lookup_kleinanzeigen") as kleinanzeigen_mock,
        ):
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "stream": "true"}
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = _parse_sse(response.text)

        stage_frames = [f for f in frames if isinstance(f, dict) and f.get("type") == "stage"]
        result_frames = [f for f in frames if isinstance(f, dict) and f.get("type") == "result"]
        assert stage_frames == []
        assert len(result_frames) == 1
        assert result_frames[0]["result"] == cached.model_dump()
        assert frames[-1] == "[DONE]"
        assert frames[-2] == result_frames[0]

        discover_mock.assert_not_called()
        vinted_mock.assert_not_called()
        marketplaces_mock.assert_not_called()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_not_called()


class TestFindProductStreamCacheMiss:
    def test_cache_miss_emits_stage_frames_then_terminal_result_matching_non_streaming(
        self, profile_store, cache_store, discovery_store, tmp_path
    ) -> None:
        _setup_user(profile_store, location="Germany")
        retail_listing = _listing("dm.de", type_="new")
        vinted_listing = _listing("Vinted")
        marketplace_listing = _listing("kleiderkreisel.de")
        kleinanzeigen_listing = _listing("Kleinanzeigen")
        discovered = _discovered(
            retailer_domains=("dm.de",),
            vinted_domain="vinted.de",
            secondhand_domains=("kleiderkreisel.de",),
        )

        async def fake_lookup_retail(name, brand, domains, on_stage=None):
            if on_stage is not None:
                on_stage("domain_check", "Checking dm.de...")
                on_stage("relevance_filter", "Checking listing relevance")
                on_stage("thumbnail_enrichment", "Fetching thumbnails")
            return [retail_listing], True

        async def fake_lookup_marketplaces(name, brand, domains, on_stage=None):
            if on_stage is not None:
                on_stage("domain_check", "Checking kleiderkreisel.de...")
                on_stage("relevance_filter", "Checking listing relevance")
            return [marketplace_listing], True

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
                AsyncMock(side_effect=fake_lookup_marketplaces),
            ),
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(side_effect=fake_lookup_retail),
            ),
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ),
        ):
            client = _make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find", params={"name": "Retinol Serum", "stream": "true"}
            )

        assert response.status_code == 200
        frames = _parse_sse(response.text)
        assert frames[-1] == "[DONE]"

        result_frames = [f for f in frames if isinstance(f, dict) and f.get("type") == "result"]
        assert len(result_frames) == 1
        assert frames[-2] == result_frames[0]

        stage_frames = [f for f in frames if isinstance(f, dict) and f.get("type") == "stage"]
        stages = [f["stage"] for f in stage_frames]
        # At least one domain_check per domain queried.
        assert stages.count("domain_check") == 2
        # relevance_filter fired for both retail and the secondhand marketplace.
        assert stages.count("relevance_filter") == 2
        # Enrichment frames only for retail.
        assert "thumbnail_enrichment" in stages
        assert stages.index("thumbnail_enrichment") < len(stages)
        # No stage frame appears after the terminal result frame.
        assert stage_frames == frames[: len(stage_frames)]

        # Payload matches what the non-streaming call for the same query
        # returns (Req 8.1) — verified against a second, freshly-seeded set
        # of stores/mocks for an equivalent non-streaming request.
        cache_store_2 = ProductCacheStore(db_path=str(tmp_path / "cache_nonstream.db"))
        discovery_store_2 = SourceDiscoveryStore(db_path=str(tmp_path / "discovery_nonstream.db"))
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
                AsyncMock(side_effect=fake_lookup_marketplaces),
            ),
            patch(
                "backend.tools.product_finder._lookup_retail",
                AsyncMock(side_effect=fake_lookup_retail),
            ),
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ),
        ):
            client_2 = _make_client(profile_store, cache_store_2, discovery_store_2)
            non_streaming_response = client_2.get(
                "/api/products/find", params={"name": "Retinol Serum"}
            )

        assert result_frames[0]["result"] == non_streaming_response.json()


class TestFindProductStreamKleinanzeigen:
    def test_source_kleinanzeigen_emits_zero_stage_frames(
        self, profile_store, cache_store, discovery_store
    ) -> None:
        _setup_user(profile_store, location="Germany")
        kleinanzeigen_listing = _listing("Kleinanzeigen")

        with (
            patch("backend.tools.product_finder.get_or_discover_sources") as discover_mock,
            patch("backend.tools.product_finder._lookup_secondhand") as vinted_mock,
            patch("backend.tools.product_finder._lookup_retail") as retail_mock,
            patch(
                "backend.tools.product_finder._lookup_kleinanzeigen",
                AsyncMock(return_value=([kleinanzeigen_listing], True)),
            ) as kleinanzeigen_mock,
        ):
            client = _make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find",
                params={"name": "Retinol Serum", "source": "kleinanzeigen", "stream": "true"},
            )

        assert response.status_code == 200
        frames = _parse_sse(response.text)
        stage_frames = [f for f in frames if isinstance(f, dict) and f.get("type") == "stage"]
        result_frames = [f for f in frames if isinstance(f, dict) and f.get("type") == "result"]

        assert stage_frames == []
        assert len(result_frames) == 1
        assert {listing["source"] for listing in result_frames[0]["result"]["listings"]} == {
            "Kleinanzeigen"
        }
        assert frames[-1] == "[DONE]"
        discover_mock.assert_not_called()
        vinted_mock.assert_not_called()
        retail_mock.assert_not_called()
        kleinanzeigen_mock.assert_awaited_once()


class TestFindProductStreamFailure:
    def test_unexpected_exception_ends_stream_with_done_and_no_result_frame(
        self, profile_store, cache_store, discovery_store, caplog: pytest.LogCaptureFixture
    ) -> None:
        _setup_user(profile_store, location="Germany")

        with patch(
            "backend.tools.product_finder._resolve_product_find",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            client = _make_client(profile_store, cache_store, discovery_store)
            with caplog.at_level("ERROR"):
                response = client.get(
                    "/api/products/find", params={"name": "Retinol Serum", "stream": "true"}
                )

        assert response.status_code == 200
        frames = _parse_sse(response.text)
        assert frames == ["[DONE]"]
        assert "product find stream ended unexpectedly" in caplog.text.lower()


class TestFindProductStreamConcurrency:
    def test_stage_event_arrival_order_matches_completion_order_not_domains_order(
        self, profile_store, cache_store, discovery_store
    ) -> None:
        """Req 7.4: per-domain queries run concurrently, so stage-event
        arrival order (as observed by the SSE stream) must track actual
        completion order, not the `domains` tuple's declared order — proven
        here by making the domain listed *first* the slowest."""
        _setup_user(profile_store, location="Germany")
        discovered = _discovered(retailer_domains=("slow.de", "fast.de"))

        async def fake_query_domain(query, domain, listing_type, max_results, on_stage=None):
            delay = {"slow.de": 0.15, "fast.de": 0.01}[domain]
            await asyncio.sleep(delay)
            if on_stage is not None:
                on_stage("domain_check", f"Checking {domain}...")
            return [], True

        with (
            patch(
                "backend.tools.product_finder.get_or_discover_sources",
                AsyncMock(return_value=discovered),
            ),
            patch("backend.tools.product_finder._lookup_secondhand", AsyncMock(return_value=([], False))),
            patch(
                "backend.tools.product_finder._lookup_secondhand_marketplaces",
                AsyncMock(return_value=([], False)),
            ),
            patch("backend.tools.product_finder._lookup_kleinanzeigen", AsyncMock(return_value=([], False))),
            patch("backend.tools.product_finder._query_domain", AsyncMock(side_effect=fake_query_domain)),
        ):
            client = _make_client(profile_store, cache_store, discovery_store)
            response = client.get(
                "/api/products/find",
                params={"name": "Retinol Serum", "source": "retail", "stream": "true"},
            )

        assert response.status_code == 200
        frames = _parse_sse(response.text)
        domain_check_frames = [
            f for f in frames if isinstance(f, dict) and f.get("stage") == "domain_check"
        ]
        # fast.de's query resolves first despite being declared second in
        # `domains` — its event must arrive first in the stream.
        assert [f["message"] for f in domain_check_frames] == [
            "Checking fast.de...",
            "Checking slow.de...",
        ]


class TestFindProductStreamAuth:
    def test_unauthenticated_stream_request_is_rejected_identically(
        self, profile_store, cache_store, discovery_store
    ) -> None:
        client = _make_unauthenticated_client(profile_store, cache_store, discovery_store)

        response = client.get(
            "/api/products/find", params={"name": "Retinol Serum", "stream": "true"}
        )

        assert response.status_code == 401
