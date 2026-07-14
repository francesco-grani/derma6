"""Product cache store: TTL cache for GET /api/products/find results.

Deliberately built on the stdlib `sqlite3` module directly rather than the shared
SQLAlchemy `engine` from `backend/db/models.py` — this is a disposable, short-TTL
(10 minutes by default) lookup cache, not durable application data, so it doesn't
need Postgres, migrations, or the ORM. TTL is enforced lazily at read time (same
shape as the JWKS cache age-check in backend/auth.py) — no background sweeper.
"""

import hashlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.schemas import ProductFindResponse

logger = logging.getLogger(__name__)


class ProductCacheStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or settings.product_cache_db_path
        # Ensure the parent directory exists (e.g. ./data/) — sqlite3 won't
        # create it for us. Skip for the special ":memory:" path used in tests.
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS product_cache (
                    cache_key     TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    brand         TEXT,
                    market_code   TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at    REAL NOT NULL
                )
                """
            )
            conn.commit()

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, cache_key: str) -> Optional[ProductFindResponse]:
        """Return the cached response if present and not older than
        settings.product_cache_ttl_seconds, else None. Expired rows are not
        actively purged here — a later set() for the same key overwrites them
        (lazy eviction)."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT response_json, created_at FROM product_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            logger.error("product_cache get failed for %s: %s", cache_key, exc)
            return None

        if row is None:
            return None

        response_json, created_at = row
        if time.time() - created_at > settings.product_cache_ttl_seconds:
            return None

        return ProductFindResponse.model_validate_json(response_json)

    def set(
        self,
        cache_key: str,
        response: ProductFindResponse,
        name: str = "",
        brand: Optional[str] = None,
        market_code: str = "",
    ) -> None:
        """Upsert the response, stamped with the current time.

        `name`/`brand`/`market_code` are optional and only populate the
        debug-only columns on the row (see the table docstring) — `cache_key`
        is a one-way sha256 hash, so the original query terms can't be
        recovered from it if the caller doesn't pass them back in. Callers
        are expected to pass them; the defaults exist only so the primary
        `(cache_key, response)` signature required by the design/tasks spec
        still works standalone.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO product_cache
                        (cache_key, name, brand, market_code, response_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        name = excluded.name,
                        brand = excluded.brand,
                        market_code = excluded.market_code,
                        response_json = excluded.response_json,
                        created_at = excluded.created_at
                    """,
                    (
                        cache_key,
                        name,
                        brand,
                        market_code,
                        response.model_dump_json(),
                        time.time(),
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.error("product_cache set failed for %s: %s", cache_key, exc)

    @staticmethod
    def make_key(name: str, brand: Optional[str], market_code: str) -> str:
        """sha256 of normalized(name) | normalized(brand) | market_code.

        Keying by resolved market_code (e.g. "DE"), not the user's raw
        `location` string, means two users whose different `location` values
        both fall back to the same default market share one cache entry
        instead of fragmenting the cache.
        """
        normalized_name = name.strip().lower()
        normalized_brand = (brand or "").strip().lower()
        raw = f"{normalized_name}|{normalized_brand}|{market_code}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
