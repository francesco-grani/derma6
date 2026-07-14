"""Unit tests for backend.db.product_cache_store.ProductCacheStore.

Uses a per-test tmp_path SQLite file (matches the fixture style in
tests/test_session_store.py) rather than the shared engine — ProductCacheStore
deliberately owns its own disposable sqlite3 file (see design.md, Requirement
13.5) instead of the shared SQLAlchemy engine in backend/db/models.py.
"""

import sqlite3
import time

import pytest

from backend.db.product_cache_store import ProductCacheStore
from backend.schemas import ProductFindResponse, ProductListing


@pytest.fixture
def cache_store(tmp_path):
    db_path = str(tmp_path / "product_cache.db")
    return ProductCacheStore(db_path=db_path)


def _sample_response() -> ProductFindResponse:
    return ProductFindResponse(
        listings=[
            ProductListing(
                type="new",
                title="Widget Pro",
                price=19.99,
                currency="EUR",
                source="example-retailer",
                thumbnail_url="https://example.com/thumb.jpg",
                listing_url="https://example.com/widget-pro",
            ),
            ProductListing(
                type="used",
                title="Widget Pro (used)",
                price=None,
                currency=None,
                source="vinted",
                thumbnail_url=None,
                listing_url="https://vinted.de/items/1",
            ),
        ],
        retail_ok=True,
        secondhand_ok=True,
    )


class TestSetGetRoundTrip:
    def test_round_trip_returns_equivalent_response(self, cache_store):
        key = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        response = _sample_response()

        cache_store.set(key, response, name="Widget Pro", brand="Acme", market_code="DE")
        result = cache_store.get(key)

        assert result is not None
        assert result == response

    def test_get_miss_returns_none(self, cache_store):
        assert cache_store.get("nonexistent-key") is None

    def test_set_upserts_existing_key(self, cache_store):
        key = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        first = _sample_response()
        cache_store.set(key, first, name="Widget Pro", brand="Acme", market_code="DE")

        second = ProductFindResponse(listings=[], retail_ok=False, secondhand_ok=False)
        cache_store.set(key, second, name="Widget Pro", brand="Acme", market_code="DE")

        result = cache_store.get(key)
        assert result == second

        # Confirm there's exactly one row for the key (upsert, not insert).
        with sqlite3.connect(cache_store._db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM product_cache WHERE cache_key = ?", (key,)
            ).fetchone()[0]
        assert count == 1

    def test_set_with_default_debug_columns(self, cache_store):
        """set() with only (cache_key, response) — the minimal signature called
        out in tasks.md/design.md — still round-trips correctly even though the
        debug-only name/market_code columns fall back to empty-string defaults."""
        key = ProductCacheStore.make_key("Widget Pro", None, "DE")
        response = _sample_response()

        cache_store.set(key, response)
        result = cache_store.get(key)

        assert result == response


class TestTtlExpiry:
    def test_expired_entry_is_a_miss(self, cache_store, monkeypatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "product_cache_ttl_seconds", 600)

        key = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        response = _sample_response()
        cache_store.set(key, response, name="Widget Pro", brand="Acme", market_code="DE")

        # Backdate created_at directly in the DB to simulate an expired entry.
        backdated = time.time() - 700  # older than the 600s TTL
        with sqlite3.connect(cache_store._db_path) as conn:
            conn.execute(
                "UPDATE product_cache SET created_at = ? WHERE cache_key = ?",
                (backdated, key),
            )
            conn.commit()

        assert cache_store.get(key) is None

    def test_fresh_entry_within_ttl_is_a_hit(self, cache_store, monkeypatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "product_cache_ttl_seconds", 600)

        key = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        response = _sample_response()
        cache_store.set(key, response, name="Widget Pro", brand="Acme", market_code="DE")

        # Backdate, but still within the TTL window.
        recent = time.time() - 100
        with sqlite3.connect(cache_store._db_path) as conn:
            conn.execute(
                "UPDATE product_cache SET created_at = ? WHERE cache_key = ?",
                (recent, key),
            )
            conn.commit()

        assert cache_store.get(key) == response


class TestMakeKey:
    def test_stable_across_calls(self):
        key1 = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        key2 = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        assert key1 == key2

    def test_brand_none_equivalent_to_empty_string(self):
        key_none = ProductCacheStore.make_key("Widget Pro", None, "DE")
        key_empty = ProductCacheStore.make_key("Widget Pro", "", "DE")
        assert key_none == key_empty

    def test_normalizes_case_and_whitespace(self):
        key_a = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        key_b = ProductCacheStore.make_key("  widget pro  ", "  ACME  ", "DE")
        assert key_a == key_b

    def test_different_market_code_yields_different_key(self):
        key_de = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        key_fr = ProductCacheStore.make_key("Widget Pro", "Acme", "FR")
        assert key_de != key_fr

    def test_different_name_yields_different_key(self):
        key_a = ProductCacheStore.make_key("Widget Pro", "Acme", "DE")
        key_b = ProductCacheStore.make_key("Widget Max", "Acme", "DE")
        assert key_a != key_b
