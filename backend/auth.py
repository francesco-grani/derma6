"""Supabase JWT verification (Bundle 2 — Supabase Auth / UUID PK rework).

Replaces the project's previously self-issued username/password/JWT stack.
Supabase now owns credentials and token issuance entirely; this module only
verifies tokens Supabase already issued and resolves the corresponding local
`users` row. `hash_password`/`verify_password`/`create_access_token`/
`decode_access_token` no longer exist anywhere in this codebase.
"""

import logging
import time
from typing import Any, Optional

import httpx
from fastapi import HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import User, engine

logger = logging.getLogger(__name__)

# Module-level JWKS cache, keyed by `kid`. Refreshed wholesale (never merged)
# on a cache miss (e.g. Supabase rotates its signing key) so a `kid` that has
# rolled out of the live JWKS document stops being trusted immediately after
# the next refresh (Req 24.1, 24.2).
_jwks_cache: dict[str, dict[str, Any]] = {}

# Throttle for unknown-`kid`-triggered refreshes (Req 24.4): repeated requests
# bearing bogus/unknown `kid` values must not each force a live HTTP fetch
# against the JWKS endpoint. Tracks the monotonic time of the last *attempted*
# refresh (successful or not) — a burst of bogus kids within the interval
# reuses the (still-missing) cache result instead of refetching.
_JWKS_REFRESH_MIN_INTERVAL_SECONDS = 30
_last_refresh_attempt: float | None = None

# security-remediation deepsec-revalidation finding (Task 79, recorded
# 2026-07-12): the original "refreshed on kid cache-miss, no TTL needed"
# design left a gap — a `kid` that keeps hitting the cache is trusted
# indefinitely between misses, even after Supabase revokes/rotates it out of
# the live JWKS, since nothing ever forces a re-check of an already-cached
# entry. `_cache_fetched_at` tracks the last *successful* fetch (distinct
# from `_last_refresh_attempt`, which tracks attempts including failures);
# once the cache is older than this, even a hit is treated as stale and
# forces a refresh (still subject to the throttle above).
_JWKS_CACHE_MAX_AGE_SECONDS = 300
_cache_fetched_at: float | None = None


def _fetch_jwks() -> dict[str, dict[str, Any]]:
    """Fetch Supabase's JWKS document, keyed by `kid`.

    Raises JWTError on any network/parse failure so callers only ever need
    to handle a single exception type for verification failures.
    """
    try:
        with httpx.Client() as client:
            response = client.get(settings.supabase_jwks_url, timeout=5.0)
            response.raise_for_status()
        keys = response.json().get("keys", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Failed to fetch Supabase JWKS from %s: %s", settings.supabase_jwks_url, exc)
        raise JWTError(f"Failed to fetch Supabase JWKS: {exc}") from exc
    return {key["kid"]: key for key in keys if "kid" in key}


def _get_jwk(kid: str) -> Optional[dict[str, Any]]:
    """Return the JWK for `kid`, refreshing the cache on a miss or once the
    cache has aged past `_JWKS_CACHE_MAX_AGE_SECONDS` (Task 79).

    A refresh replaces `_jwks_cache` wholesale rather than merging into it
    (Req 24.1), so a retired `kid` stops resolving as soon as a fresh fetch
    succeeds without it — unlike `.update()`, which would let a stale entry
    linger forever. A failed refresh leaves `_jwks_cache` (and
    `_cache_fetched_at`) untouched (Req 24.3): `_fetch_jwks()` raises before
    this function ever reassigns them, so a transient outage can't clear out
    currently-valid keys.

    Refresh attempts are throttled (Req 24.4): repeated lookups within
    `_JWKS_REFRESH_MIN_INTERVAL_SECONDS` of the last attempt reuse the
    existing cache instead of hitting the network again — this applies
    whether the refresh was triggered by an unknown `kid` or by the cache
    simply aging out, so a burst of requests during one slow refresh doesn't
    each trigger their own fetch.
    """
    global _jwks_cache, _last_refresh_attempt, _cache_fetched_at

    now = time.monotonic()
    cache_is_fresh = (
        _cache_fetched_at is not None and now - _cache_fetched_at < _JWKS_CACHE_MAX_AGE_SECONDS
    )
    if kid in _jwks_cache and cache_is_fresh:
        return _jwks_cache[kid]

    if (
        _last_refresh_attempt is not None
        and now - _last_refresh_attempt < _JWKS_REFRESH_MIN_INTERVAL_SECONDS
    ):
        logger.warning(
            "Skipping JWKS refresh for kid %r — throttled (last attempt %.1fs ago)",
            kid, now - _last_refresh_attempt,
        )
        return _jwks_cache.get(kid)

    _last_refresh_attempt = now
    _jwks_cache = _fetch_jwks()
    _cache_fetched_at = now
    return _jwks_cache.get(kid)


# Verification spike finding (capstone-round Task 9, recorded 2026-07-10): a direct
# unauthenticated GET to
# https://hadqrljodgffcdsitxrv.supabase.co/auth/v1/.well-known/jwks.json
# returned a valid JWKS document with exactly one ES256 key
# (kid e206c8f3-414a-452f-9b5e-f6cb786820a4). Project ref hadqrljodgffcdsitxrv was
# verified against this app's actual DATABASE_URL in .env, not any MCP-configured
# project, which may point elsewhere. This deployment uses per-project asymmetric
# JWKS (ES256) signing — JWKS verification is the primary and effectively only
# active path here. The shared-secret HS256 fallback below is implemented for
# portability/documentation completeness per the design, but is confirmed NOT the
# active mechanism for this project. Re-run this spike and update this comment if
# Supabase's signing scheme for this project ever changes.
def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase-issued JWT and return its claims.

    JWKS-based asymmetric verification (RS256/ES256) is the primary path,
    selected whenever the token header declares an algorithm other than
    HS256 — matching this deployment's confirmed signing scheme (see the
    spike finding above). A shared-secret HS256 fallback
    (`settings.supabase_jwt_secret`) is also implemented and selected when
    the token header declares HS256, keeping this function portable to
    Supabase deployments still using a shared project secret, per the
    design's documented fallback — even though it is confirmed NOT the
    active path for this deployment.

    Raises JWTError on any validation failure: invalid signature, expired
    token, malformed token, or an unknown key id / issuer.
    """
    # jwt.get_unverified_header() itself raises JWTError on a malformed token
    # (bad base64/JSON, missing segments, etc.) — no extra try/except needed.
    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg")
    issuer = f"{settings.supabase_url}/auth/v1"

    if algorithm == "HS256":
        if not settings.supabase_jwt_secret:
            raise JWTError(
                "Received an HS256 token but no supabase_jwt_secret is configured"
            )
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=issuer,
        )

    # JWKS path (RS256/ES256) — primary, and for this deployment the only
    # active signing scheme (see spike finding above).
    kid = header.get("kid")
    if not kid:
        raise JWTError("Token header is missing 'kid'; cannot select a JWKS key")

    key = _get_jwk(kid)
    if key is None:
        logger.warning("JWT verification failed: unknown key id %r after a JWKS cache refresh", kid)
        raise JWTError(f"Unknown key id: {kid}")

    return jwt.decode(
        token,
        key,
        algorithms=[algorithm],
        audience="authenticated",
        issuer=issuer,
    )


def get_current_user(request: Request) -> str:
    """FastAPI Depends() helper — resolves the local user row for the request.

    `request.state.user_id` is set by `JWTAuthMiddleware`, which has already
    called `verify_supabase_jwt()` and extracted the `sub` claim — no
    re-verification happens here, keeping route dependencies cheap.

    A verified Supabase identity does not by itself guarantee
    `/complete-signup` ever ran for it (e.g. the browser still holds a
    session, but local provisioning failed or was never attempted), so a
    missing local row is surfaced as a distinct, actionable error (Req 4.5)
    rather than silently auto-creating a blank profile.
    """
    user_id = request.state.user_id
    with Session(engine) as session:
        user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=412,
            detail="Account setup incomplete — complete signup first.",
        )
    return user_id
