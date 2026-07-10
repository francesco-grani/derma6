"""Tests for backend.api.profile (capstone-round Bundle 2, Task 19, Req 7.1-7.3).

Route-level tests exercised through FastAPI's `TestClient` against a minimal
app that mounts only `backend.api.profile.router` (mirroring
`tests/test_api_auth.py`'s approach). `get_current_user` is overridden via
`dependency_overrides` to return a fixed `user_id` string directly (rather than
going through JWT verification/middleware, which is covered elsewhere), and
`get_profile_store` is overridden to return a `ProfileStore` backed by a
per-test temporary SQLite file — so these tests exercise the real
`ProfileStore` methods rekeyed to `user_id` rather than mocks.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.profile import router as profile_router
from backend.auth import get_current_user
from backend.db.deps import get_profile_store


def _make_client(store, user_id: str = "uid-alice") -> TestClient:
    app = FastAPI()
    app.include_router(profile_router)
    app.dependency_overrides[get_profile_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


class TestGetProfile:
    """Req 7.1-7.3: route resolves the caller's profile by user_id, not username."""

    def test_returns_profile_for_authenticated_user(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.get("/api/me/profile")

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == "uid-alice"
        assert body["username"] == "alice"

    def test_missing_user_returns_500(self, profile_store):
        # No user row exists for this user_id — ProfileStore.get_profile raises
        # ProfileStoreError, which the route surfaces as a 500.
        client = _make_client(profile_store, user_id="uid-ghost")

        response = client.get("/api/me/profile")

        assert response.status_code == 500

    def test_uses_user_id_not_username_to_scope_lookup(self, profile_store):
        # Two users exist; the route must return the profile matching the
        # authenticated user_id, never falling back to a username lookup.
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")

        client = _make_client(profile_store, user_id="uid-bob")
        response = client.get("/api/me/profile")

        assert response.status_code == 200
        assert response.json()["username"] == "bob"


class TestPatchProfile:
    """Req 7.1-7.3: profile mutations are scoped to the authenticated user_id."""

    def test_updates_skin_type(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch("/api/me/profile", json={"skin_type": "oily"})

        assert response.status_code == 200
        assert response.json()["skin_type"] == "oily"

    def test_updates_beard_style(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch("/api/me/profile", json={"beard_style": "trim"})

        assert response.status_code == 200
        assert response.json()["beard_style"] == "trim"
        assert response.json()["has_shaving_routine"] is True

    def test_rejects_invalid_beard_style(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch("/api/me/profile", json={"beard_style": "bogus"})

        assert response.status_code == 422

    def test_updates_location_and_skin_concerns(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch(
            "/api/me/profile",
            json={"location": "  Berlin  ", "skin_concerns": ["acne", "  ", "redness"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["location"] == "Berlin"
        assert body["skin_concerns"] == ["acne", "redness"]

    def test_patch_scoped_to_authenticated_user_id(self, profile_store):
        # Patching as bob must never affect alice's row.
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")

        client = _make_client(profile_store, user_id="uid-bob")
        client.patch("/api/me/profile", json={"skin_type": "dry"})

        alice_client = _make_client(profile_store, user_id="uid-alice")
        alice_profile = alice_client.get("/api/me/profile").json()
        assert alice_profile["skin_type"] is None
