"""Unit tests for backend.db.source_discovery_store.SourceDiscoveryStore.

Uses a per-test tmp_path SQLite file (matches the fixture style in
tests/test_product_cache_store.py) rather than the shared engine —
SourceDiscoveryStore deliberately owns its own disposable sqlite3 file (see
design.md, "Why a new sibling store, not extending ProductCacheStore")
instead of the shared SQLAlchemy engine in backend/db/models.py.
"""

import sqlite3
import time

import pytest

from backend.db.deps import get_source_discovery_store
from backend.db.source_discovery_store import SourceDiscoveryStore
from backend.schemas import DiscoveredSources


@pytest.fixture
def discovery_store(tmp_path):
    db_path = str(tmp_path / "source_discovery.db")
    return SourceDiscoveryStore(db_path=db_path)


def _sample_result() -> DiscoveredSources:
    return DiscoveredSources(
        retailer_domains=("douglas.de", "flaconi.de"),
        vinted_domain="vinted.de",
        secondhand_domains=("kleinanzeigen.de",),
    )


def _normalize(location: str) -> str:
    """Mirrors the trim + casefold normalization the caller is expected to
    apply before passing a location_key (Req 6.3) — the store itself trusts
    an already-normalized key."""
    return location.strip().casefold()


class TestSetGetRoundTrip:
    def test_round_trip_returns_equivalent_result(self, discovery_store):
        key = _normalize("Germany")
        result = _sample_result()

        discovery_store.set(key, "Germany", result)
        fetched = discovery_store.get(key)

        assert fetched is not None
        assert fetched == result

    def test_get_miss_returns_none_without_raising(self, discovery_store):
        assert discovery_store.get("nonexistent-key") is None

    def test_set_upserts_existing_key(self, discovery_store):
        key = _normalize("Germany")
        first = _sample_result()
        discovery_store.set(key, "Germany", first)

        second = DiscoveredSources(retailer_domains=(), vinted_domain=None, secondhand_domains=())
        discovery_store.set(key, "Germany", second)

        fetched = discovery_store.get(key)
        assert fetched == second

        # Confirm there's exactly one row for the key (upsert, not insert).
        with sqlite3.connect(discovery_store._db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM source_discovery WHERE location_key = ?", (key,)
            ).fetchone()[0]
        assert count == 1


class TestTtlExpiry:
    def test_miss_just_past_ttl_boundary(self, discovery_store, monkeypatch):
        from backend.config import settings

        ttl = 7 * 24 * 60 * 60  # 7-day default
        monkeypatch.setattr(settings, "source_discovery_ttl_seconds", ttl)

        key = _normalize("Germany")
        result = _sample_result()
        discovery_store.set(key, "Germany", result)

        # Backdate created_at to just past the TTL boundary.
        backdated = time.time() - ttl - 1
        with sqlite3.connect(discovery_store._db_path) as conn:
            conn.execute(
                "UPDATE source_discovery SET created_at = ? WHERE location_key = ?",
                (backdated, key),
            )
            conn.commit()

        assert discovery_store.get(key) is None

    def test_hit_just_before_ttl_boundary(self, discovery_store, monkeypatch):
        from backend.config import settings

        ttl = 7 * 24 * 60 * 60  # 7-day default
        monkeypatch.setattr(settings, "source_discovery_ttl_seconds", ttl)

        key = _normalize("Germany")
        result = _sample_result()
        discovery_store.set(key, "Germany", result)

        # Backdate created_at to just inside the TTL boundary.
        recent = time.time() - ttl + 1
        with sqlite3.connect(discovery_store._db_path) as conn:
            conn.execute(
                "UPDATE source_discovery SET created_at = ? WHERE location_key = ?",
                (recent, key),
            )
            conn.commit()

        assert discovery_store.get(key) == result


class TestKeyStability:
    def test_trim_and_casefold_variants_hit_the_same_row(self, discovery_store):
        result = _sample_result()
        # Caller is responsible for normalizing before calling set()/get() —
        # verify all three raw variants normalize to the same location_key
        # and therefore address the same row.
        discovery_store.set(_normalize("Germany"), "Germany", result)

        assert discovery_store.get(_normalize(" germany ")) == result
        assert discovery_store.get(_normalize("GERMANY")) == result

        with sqlite3.connect(discovery_store._db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM source_discovery").fetchone()[0]
        assert count == 1


class TestGetSourceDiscoveryStoreDep:
    """Task 7: `backend.db.deps.get_source_discovery_store()` — mirrors the
    existing `_product_cache_store`/`get_product_cache_store` module-level
    singleton pattern exactly."""

    def test_returns_the_same_singleton_instance_across_repeated_calls(self):
        first = get_source_discovery_store()
        second = get_source_discovery_store()

        assert first is second
        assert isinstance(first, SourceDiscoveryStore)
