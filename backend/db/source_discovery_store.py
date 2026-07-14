"""Source discovery store: TTL cache for LLM-discovered per-location product
sources (retailer/Vinted-locale/secondhand-marketplace domains).

Deliberately built on the stdlib `sqlite3` module directly rather than the
shared SQLAlchemy `engine` from `backend/db/models.py` — a sibling to
`backend/db/product_cache_store.py`, built the same way: own file, no
SQLAlchemy engine, lazy TTL-at-read-time (7 days by default), no background
sweeper. See product-source-agent design.md, "Why a new sibling store, not
extending ProductCacheStore".
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.schemas import DiscoveredSources

logger = logging.getLogger(__name__)


class SourceDiscoveryStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or settings.source_discovery_db_path
        # Ensure the parent directory exists (e.g. ./data/) — sqlite3 won't
        # create it for us. Skip for the special ":memory:" path used in tests.
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_discovery (
                    location_key  TEXT PRIMARY KEY,
                    location_raw  TEXT NOT NULL,
                    result_json   TEXT NOT NULL,
                    created_at    REAL NOT NULL
                )
                """
            )
            conn.commit()

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, location_key: str) -> Optional[DiscoveredSources]:
        """Return the cached discovery result if present and not older than
        settings.source_discovery_ttl_seconds, else None. Expired rows are not
        actively purged here — a later set() for the same key overwrites them
        (lazy eviction), same shape as ProductCacheStore.get()."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT result_json, created_at FROM source_discovery WHERE location_key = ?",
                    (location_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            logger.error("source_discovery get failed for %s: %s", location_key, exc)
            return None

        if row is None:
            return None

        result_json, created_at = row
        if time.time() - created_at > settings.source_discovery_ttl_seconds:
            return None

        return DiscoveredSources.model_validate_json(result_json)

    def set(self, location_key: str, location_raw: str, result: DiscoveredSources) -> None:
        """Upsert the discovery result, stamped with the current time.

        Never called for a failed discovery run or the Germany seed
        fallback — see get_or_discover_sources()'s docstring in
        backend/tools/product_source_discovery.py.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO source_discovery
                        (location_key, location_raw, result_json, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(location_key) DO UPDATE SET
                        location_raw = excluded.location_raw,
                        result_json = excluded.result_json,
                        created_at = excluded.created_at
                    """,
                    (
                        location_key,
                        location_raw,
                        result.model_dump_json(),
                        time.time(),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.error("source_discovery set failed for %s: %s", location_key, exc)
