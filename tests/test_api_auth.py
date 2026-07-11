"""Tests for backend.api.auth.

These are route-level tests exercised through FastAPI's `TestClient` against
a minimal app that mounts only `backend.api.auth.router` (mirroring
`tests/test_middleware_auth.py`'s approach of avoiding `backend.main`'s full
router set, since several other routers still reference the pre-rekey
`get_current_user`/`username` contract until Tasks 19-22 land). The route
under test is public (no JWT/Bearer token involved), so the auth middleware
itself is intentionally not mounted here — that behavior is covered by
`tests/test_middleware_auth.py`.

`get_profile_store` is overridden via FastAPI's `dependency_overrides` to
return a `ProfileStore` backed by a per-test temporary SQLite file (matching
the `profile_store` fixture already used in `tests/test_profile_store.py`),
so these tests exercise the real `ProfileStore.get_or_create_user_by_id`
method rather than mocks.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.auth import router as auth_router
from backend.db.deps import get_profile_store


def _make_client(store) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_profile_store] = lambda: store
    return TestClient(app)


class TestCompleteSignup:
    """Req 4.1, 4.4, 4.5, 4.6: provisions the local row using the
    Supabase-issued UUID, submitted email, and explicitly-chosen username."""

    def test_successful_signup_completion_returns_201(self, profile_store):
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            json={
                "supabase_user_id": "11111111-1111-1111-1111-111111111111",
                "email": "new@example.com",
                "username": "newuser",
            },
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
            json={
                "supabase_user_id": "22222222-2222-2222-2222-222222222222",
                "email": "provisioned@example.com",
                "username": "provisioned",
            },
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
            json={
                "supabase_user_id": "44444444-4444-4444-4444-444444444444",
                "email": "second@example.com",
                "username": "duplicate",
            },
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
            json={
                "supabase_user_id": "88888888-8888-8888-8888-888888888888",
                "email": "dup@example.com",
                "username": "usertwo",
            },
        )

        assert response.status_code == 409
        assert "already" in response.json()["detail"]

    def test_idempotent_recall_with_same_supabase_user_id_returns_201(self, profile_store):
        client = _make_client(profile_store)
        payload = {
            "supabase_user_id": "55555555-5555-5555-5555-555555555555",
            "email": "retry@example.com",
            "username": "retryuser",
        }

        first = client.post("/api/auth/complete-signup", json=payload)
        second = client.post("/api/auth/complete-signup", json=payload)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json() == second.json()

    def test_invalid_username_returns_422(self, profile_store):
        client = _make_client(profile_store)

        response = client.post(
            "/api/auth/complete-signup",
            json={
                "supabase_user_id": "66666666-6666-6666-6666-666666666666",
                "email": "short@example.com",
                "username": "a",
            },
        )

        assert response.status_code == 422
