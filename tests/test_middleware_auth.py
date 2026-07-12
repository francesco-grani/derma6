"""Unit tests for backend.middleware.auth — JWTAuthMiddleware (Bundle 2, Task 15).

Exercises the middleware in isolation via a minimal Starlette app so these
tests don't depend on backend.main's full router set (several routers still
reference the pre-rekey `get_current_user`/`username` contract until Tasks
16-22 land). Verification itself is exercised through the real
`verify_supabase_jwt()` against a mocked JWKS endpoint, matching the
approach in tests/test_auth.py.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwk, jwt
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import backend.auth as auth_module
import backend.middleware.auth as middleware_auth_module
from backend.middleware.auth import JWTAuthMiddleware, _PUBLIC_PATHS

_ISSUER = "https://test-project.supabase.co/auth/v1"
_KID = "test-kid-1"


def _generate_es256_keypair() -> tuple[str, dict]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    public_jwk = jwk.construct(public_pem, algorithm="ES256").to_dict()
    public_jwk["kid"] = _KID
    return private_pem, public_jwk


_PRIVATE_PEM, _PUBLIC_JWK = _generate_es256_keypair()


def _make_token(
    sub: str = "user-123",
    *,
    exp_delta: int = 3600,
    email: str | None = "user@example.com",
    user_metadata: dict | None = None,
) -> str:
    claims = {
        "sub": sub,
        "exp": int(time.time()) + exp_delta,
        "aud": "authenticated",
        "iss": _ISSUER,
    }
    if email is not None:
        claims["email"] = email
    if user_metadata is not None:
        claims["user_metadata"] = user_metadata
    return jwt.encode(claims, _PRIVATE_PEM, algorithm="ES256", headers={"kid": _KID})


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    # Also reset the Task 70 refresh-throttle clock: each test in this file
    # clears `_jwks_cache`, so a `kid` that verified cleanly in one test is a
    # fresh cache-miss in the next — without resetting the throttle too,
    # that legitimate next-test refresh would be wrongly suppressed as "too
    # soon after" the previous test's refresh.
    auth_module._jwks_cache.clear()
    auth_module._last_refresh_attempt = None
    auth_module._cache_fetched_at = None
    yield
    auth_module._jwks_cache.clear()
    auth_module._last_refresh_attempt = None
    auth_module._cache_fetched_at = None


@pytest.fixture
def configure_supabase(monkeypatch):
    monkeypatch.setattr(auth_module.settings, "supabase_url", "https://test-project.supabase.co")
    monkeypatch.setattr(
        auth_module.settings,
        "supabase_jwks_url",
        "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setattr(auth_module.settings, "supabase_jwt_secret", "")


@pytest.fixture
def mock_jwks_endpoint(monkeypatch, configure_supabase):
    def _fake_get(url, timeout=None):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"keys": [_PUBLIC_JWK]}
        return response

    fake_client = MagicMock()
    fake_client.__enter__.return_value.get.side_effect = _fake_get
    fake_client.__exit__.return_value = False

    monkeypatch.setattr(auth_module.httpx, "Client", MagicMock(return_value=fake_client))


async def _echo_user_id(request):
    """Test-only route: echoes back whatever the middleware stashed on state."""
    return JSONResponse({
        "user_id": getattr(request.state, "user_id", None),
        "user_claims": getattr(request.state, "user_claims", None),
    })


def _make_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/api/protected", _echo_user_id),
            Route("/health", _echo_user_id),
        ],
    )
    app.add_middleware(JWTAuthMiddleware)
    return app


@pytest.fixture
def client():
    return TestClient(_make_app())


class TestPublicPaths:
    """Req 6.3/6.4/21.1: the old locally-issued-token routes no longer exist
    as public paths. `/api/auth/complete-signup` also requires a Bearer
    token now (security-remediation Req 21.1 — see backend/api/auth.py's
    Task 61 spike-finding comment for why it moved off this list)."""

    def test_login_and_register_are_no_longer_public(self):
        assert "/api/auth/login" not in _PUBLIC_PATHS
        assert "/api/auth/register" not in _PUBLIC_PATHS

    def test_complete_signup_is_no_longer_public(self):
        assert "/api/auth/complete-signup" not in _PUBLIC_PATHS

    def test_health_still_public(self, client):
        response = client.get("/health")

        assert response.status_code == 200


class TestProtectedPaths:
    """Req 6.3/6.4: non-public routes require a valid Supabase JWT, verified
    via verify_supabase_jwt(), and stash the sub claim as request.state.user_id."""

    def test_valid_token_passes_through_and_sets_user_id(self, client, mock_jwks_endpoint):
        token = _make_token(sub="abc-123")

        response = client.get("/api/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["user_id"] == "abc-123"

    def test_missing_authorization_header_returns_401(self, client):
        response = client.get("/api/protected")

        assert response.status_code == 401

    def test_non_bearer_authorization_header_returns_401(self, client):
        response = client.get("/api/protected", headers={"Authorization": "Basic abc123"})

        assert response.status_code == 401

    def test_malformed_token_returns_401(self, client, mock_jwks_endpoint):
        response = client.get(
            "/api/protected", headers={"Authorization": "Bearer not-a-jwt-at-all"}
        )

        assert response.status_code == 401

    def test_expired_token_returns_401(self, client, mock_jwks_endpoint):
        token = _make_token(exp_delta=-3600)

        response = client.get("/api/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_dispatch_calls_verify_supabase_jwt(self, client, mock_jwks_endpoint, monkeypatch):
        """Locks in the Task 15 contract: dispatch must call
        verify_supabase_jwt (not the removed decode_access_token)."""
        called_with = {}
        original = middleware_auth_module.verify_supabase_jwt

        def _spy(token):
            called_with["token"] = token
            return original(token)

        monkeypatch.setattr(middleware_auth_module, "verify_supabase_jwt", _spy)
        token = _make_token(sub="spy-user")

        response = client.get("/api/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert called_with["token"] == token

    def test_valid_token_sets_full_user_claims(self, client, mock_jwks_endpoint):
        """Req 21.1: `complete-signup` needs `email`/`user_metadata.username`
        from the verified token, not just `sub` — the middleware must stash
        the full claim set, not a trimmed-down subset."""
        token = _make_token(
            sub="abc-123", email="abc@example.com", user_metadata={"username": "abcuser"}
        )

        response = client.get("/api/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        claims = response.json()["user_claims"]
        assert claims["sub"] == "abc-123"
        assert claims["email"] == "abc@example.com"
        assert claims["user_metadata"] == {"username": "abcuser"}
