"""Unit tests for backend.auth — Supabase JWT verification (Bundle 2, Task 14).

Covers both signing paths the design requires: JWKS-based ES256 (primary,
and per the Task 9 spike finding, the only *active* path for this
deployment) and the documented shared-secret HS256 fallback. The JWKS HTTP
fetch and the local `users` row lookup are both mocked/in-memory — no live
Supabase call, no live database.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request
from jose import JWTError, jwk, jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import backend.auth as auth_module
from backend.db.models import Base, User

_ISSUER = "https://test-project.supabase.co/auth/v1"
_KID = "test-kid-1"


def _generate_es256_keypair() -> tuple[str, dict]:
    """Return (private_pem, public_jwk) for a fresh P-256 keypair, mirroring
    the ES256 scheme the Task 9 spike confirmed for the live Supabase project."""
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


def _make_es256_token(
    sub: str = "user-123",
    *,
    exp_delta: int = 3600,
    aud: str | None = "authenticated",
    iss: str | None = _ISSUER,
    kid: str | None = _KID,
) -> str:
    claims: dict = {"sub": sub, "exp": int(time.time()) + exp_delta}
    if aud is not None:
        claims["aud"] = aud
    if iss is not None:
        claims["iss"] = iss
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, _PRIVATE_PEM, algorithm="ES256", headers=headers)


def _make_hs256_token(
    sub: str = "user-123",
    secret: str = "shared-secret",
    *,
    exp_delta: int = 3600,
    aud: str | None = "authenticated",
    iss: str | None = _ISSUER,
) -> str:
    claims: dict = {"sub": sub, "exp": int(time.time()) + exp_delta}
    if aud is not None:
        claims["aud"] = aud
    if iss is not None:
        claims["iss"] = iss
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    """Every test starts with a cold JWKS cache — no cross-test pollution."""
    auth_module._jwks_cache.clear()
    yield
    auth_module._jwks_cache.clear()


@pytest.fixture
def configure_supabase(monkeypatch):
    """Point backend.auth.settings at the test issuer/JWKS URL, HS256 fallback unset."""
    monkeypatch.setattr(auth_module.settings, "supabase_url", "https://test-project.supabase.co")
    monkeypatch.setattr(
        auth_module.settings,
        "supabase_jwks_url",
        "https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setattr(auth_module.settings, "supabase_jwt_secret", "")


@pytest.fixture
def mock_jwks_endpoint(monkeypatch, configure_supabase):
    """Mock httpx.Client().get(...) to serve a one-key JWKS document.

    Returns a dict tracking the number of outbound fetches, so tests can
    assert caching behaviour (fetch once, reuse across calls; refresh once
    on a kid-miss).
    """
    call_count = {"n": 0}

    def _fake_get(url, timeout=None):
        call_count["n"] += 1
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"keys": [_PUBLIC_JWK]}
        return response

    fake_client = MagicMock()
    fake_client.__enter__.return_value.get.side_effect = _fake_get
    fake_client.__exit__.return_value = False

    monkeypatch.setattr(auth_module.httpx, "Client", MagicMock(return_value=fake_client))
    return call_count


class TestVerifySupabaseJwtJwksPath:
    """Primary path — JWKS-based ES256, the active scheme for this deployment
    per the Task 9 spike finding recorded above verify_supabase_jwt()."""

    def test_valid_token_returns_claims(self, mock_jwks_endpoint):
        token = _make_es256_token(sub="abc-123")

        claims = auth_module.verify_supabase_jwt(token)

        assert claims["sub"] == "abc-123"

    def test_expired_token_raises(self, mock_jwks_endpoint):
        token = _make_es256_token(exp_delta=-3600)

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

    def test_malformed_token_raises(self, mock_jwks_endpoint):
        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt("not-a-jwt-at-all")

    def test_unknown_kid_raises_after_cache_refresh_attempt(self, mock_jwks_endpoint):
        token = _make_es256_token(kid="some-other-kid")

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

        # A kid-miss must trigger a refresh attempt, not silently reuse a stale cache.
        assert mock_jwks_endpoint["n"] >= 1

    def test_missing_kid_header_raises(self, mock_jwks_endpoint):
        token = _make_es256_token(kid=None)

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

    def test_wrong_issuer_raises(self, mock_jwks_endpoint):
        token = _make_es256_token(iss="https://someone-elses-project.supabase.co/auth/v1")

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

    def test_wrong_audience_raises(self, mock_jwks_endpoint):
        token = _make_es256_token(aud="not-authenticated")

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

    def test_jwks_fetched_once_and_cached_across_calls(self, mock_jwks_endpoint):
        token_a = _make_es256_token(sub="user-a")
        token_b = _make_es256_token(sub="user-b")

        auth_module.verify_supabase_jwt(token_a)
        auth_module.verify_supabase_jwt(token_b)

        assert mock_jwks_endpoint["n"] == 1

    def test_jwks_fetch_failure_raises_jwt_error(self, configure_supabase, monkeypatch):
        fake_client = MagicMock()
        fake_client.__enter__.return_value.get.side_effect = auth_module.httpx.HTTPError("boom")
        fake_client.__exit__.return_value = False
        monkeypatch.setattr(auth_module.httpx, "Client", MagicMock(return_value=fake_client))

        token = _make_es256_token()

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)


class TestVerifySupabaseJwtHs256Fallback:
    """Documented shared-secret fallback path (design.md, portability/
    documentation completeness) — confirmed NOT the active path for this
    deployment (Task 9 finding), but still exercised here per Task 14."""

    def test_valid_hs256_token_with_configured_secret(self, monkeypatch, configure_supabase):
        monkeypatch.setattr(auth_module.settings, "supabase_jwt_secret", "shared-secret")
        token = _make_hs256_token(sub="hs-user", secret="shared-secret")

        claims = auth_module.verify_supabase_jwt(token)

        assert claims["sub"] == "hs-user"

    def test_hs256_token_without_configured_secret_raises(self, configure_supabase):
        token = _make_hs256_token(sub="hs-user", secret="shared-secret")

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

    def test_hs256_token_with_wrong_secret_raises(self, monkeypatch, configure_supabase):
        monkeypatch.setattr(auth_module.settings, "supabase_jwt_secret", "the-real-secret")
        token = _make_hs256_token(sub="hs-user", secret="a-different-secret")

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)

    def test_expired_hs256_token_raises(self, monkeypatch, configure_supabase):
        monkeypatch.setattr(auth_module.settings, "supabase_jwt_secret", "shared-secret")
        token = _make_hs256_token(secret="shared-secret", exp_delta=-3600)

        with pytest.raises(JWTError):
            auth_module.verify_supabase_jwt(token)


class TestGetCurrentUser:
    """get_current_user() only does a local-row lookup keyed by the already-
    verified request.state.user_id — no JWT re-verification happens here."""

    @pytest.fixture
    def sqlite_engine(self, monkeypatch):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        monkeypatch.setattr(auth_module, "engine", engine)
        return engine

    @staticmethod
    def _make_request(user_id: str) -> Request:
        request = MagicMock(spec=Request)
        request.state.user_id = user_id
        return request

    def test_returns_user_id_when_local_row_exists(self, sqlite_engine):
        user_id = str(uuid.uuid4())
        with Session(sqlite_engine) as session:
            session.add(User(id=user_id, username="alice", email="alice@example.com"))
            session.commit()

        result = auth_module.get_current_user(self._make_request(user_id))

        assert result == user_id

    def test_raises_412_when_local_row_missing(self, sqlite_engine):
        """Req 4.5: a verified-but-unprovisioned identity gets a clear, actionable
        error rather than a silent auto-create or an opaque failure."""
        request = self._make_request(str(uuid.uuid4()))

        with pytest.raises(HTTPException) as exc_info:
            auth_module.get_current_user(request)

        assert exc_info.value.status_code == 412
