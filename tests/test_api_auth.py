"""Tests for backend.api.auth.

`POST /api/auth/complete-signup` now requires a verified Supabase Bearer
token (security-remediation Req 21.1 — see backend/api/auth.py's Task 61
spike-finding comment). These are route-level tests exercised through
FastAPI's `TestClient` against a minimal app that mounts only
`backend.api.auth.router`, with a lightweight fake auth middleware standing
in for `JWTAuthMiddleware` so tests can control `request.state.user_id`/
`user_claims` directly without a real JWT (JWT verification itself is
covered by `tests/test_middleware_auth.py`).

`get_profile_store` is overridden via FastAPI's `dependency_overrides` to
return a `ProfileStore` backed by a per-test temporary SQLite file (matching
the `profile_store` fixture already used in `tests/test_profile_store.py`),
so these tests exercise the real `ProfileStore.get_or_create_user_by_id`
method rather than mocks.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.auth import router as auth_router
from backend.db.deps import get_profile_store


class _FakeAuthMiddleware(BaseHTTPMiddleware):
    """Stands in for JWTAuthMiddleware: reads pre-baked identity out of a
    custom header instead of verifying a real JWT, so these route tests can
    focus on complete_signup's own logic."""

    async def dispatch(self, request: Request, call_next):
        user_id = request.headers.get("X-Test-User-Id")
        if user_id is None:
            return await call_next(request)
        request.state.user_id = user_id
        claims = {"sub": user_id}
        email = request.headers.get("X-Test-Email")
        if email is not None:
            claims["email"] = email
        username = request.headers.get("X-Test-Username")
        if username is not None:
            claims["user_metadata"] = {"username": username}
        request.state.user_claims = claims
        return await call_next(request)


def _make_client(store) -> TestClient:
    app = FastAPI()
    app.add_middleware(_FakeAuthMiddleware)
    app.include_router(auth_router)
    app.dependency_overrides[get_profile_store] = lambda: store
    return TestClient(app)


def _headers(user_id: str, email: str, username: str) -> dict:
    return {"X-Test-User-Id": user_id, "X-Test-Email": email, "X-Test-Username": username}


class TestCompleteSignup:
    """Req 21.1, 21.2, 21.3: identity is derived entirely from the verified
    token's claims — never from a client-supplied request body."""

    def test_successful_signup_completion_returns_201(self, profile_store):
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            headers=_headers(
                "11111111-1111-1111-1111-111111111111", "new@example.com", "newuser"
            ),
        )

        assert response.status_code == 201
        assert response.json() == {
            "user_id": "11111111-1111-1111-1111-111111111111",
            "username": "newuser",
        }

    def test_signup_provisions_row_readable_via_profile_store(self, profile_store):
        client = _make_client(profile_store)

        client.post(
            "/api/auth/complete-signup",
            headers=_headers(
                "22222222-2222-2222-2222-222222222222", "provisioned@example.com", "provisioned"
            ),
        )

        profile = profile_store.get_profile("22222222-2222-2222-2222-222222222222")
        assert profile.username == "provisioned"
        assert profile.user_id == "22222222-2222-2222-2222-222222222222"

    def test_duplicate_username_allowed(self, profile_store):
        profile_store.get_or_create_user_by_id(
            "33333333-3333-3333-3333-333333333333", "first@example.com", "duplicate"
        )
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            headers=_headers(
                "44444444-4444-4444-4444-444444444444", "second@example.com", "duplicate"
            ),
        )

        assert response.status_code == 201
        assert response.json()["username"] == "duplicate"

    def test_email_taken_returns_409(self, profile_store):
        profile_store.get_or_create_user_by_id(
            "77777777-7777-7777-7777-777777777777", "dup@example.com", "userone"
        )
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            headers=_headers(
                "88888888-8888-8888-8888-888888888888", "dup@example.com", "usertwo"
            ),
        )

        assert response.status_code == 409
        assert "already" in response.json()["detail"]

    def test_idempotent_recall_with_same_verified_identity_returns_201(self, profile_store):
        client = _make_client(profile_store)
        headers = _headers(
            "55555555-5555-5555-5555-555555555555", "retry@example.com", "retryuser"
        )

        first = client.post("/api/auth/complete-signup", headers=headers)
        second = client.post("/api/auth/complete-signup", headers=headers)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json() == second.json()

    def test_missing_username_in_claims_returns_422(self, profile_store):
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            headers={
                "X-Test-User-Id": "66666666-6666-6666-6666-666666666666",
                "X-Test-Email": "short@example.com",
                # No X-Test-Username header set — claims carry no user_metadata.
            },
        )

        assert response.status_code == 422

    def test_short_username_in_claims_returns_422(self, profile_store):
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            headers=_headers(
                "99999999-9999-9999-9999-999999999999", "short2@example.com", "a"
            ),
        )

        assert response.status_code == 422
