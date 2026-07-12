"""Tests for backend.api.routines (capstone-round Bundle 2, Task 19, Req 7.1-7.3).

Route-level tests exercised through FastAPI's `TestClient`, mirroring
`tests/test_api_profile.py`'s pattern: `get_current_user` is overridden to
return a fixed `user_id` string directly, and `get_profile_store` is
overridden to return a `ProfileStore` backed by a per-test temporary SQLite
file — so these tests exercise the real `ProfileStore` routine methods
rekeyed to `user_id` rather than mocks.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routines import router as routines_router
from backend.auth import get_current_user
from backend.db.deps import get_profile_store
from backend.schemas import RoutineSchema, RoutineStepSchema


def _make_client(store, user_id: str = "uid-alice") -> TestClient:
    app = FastAPI()
    app.include_router(routines_router)
    app.dependency_overrides[get_profile_store] = lambda: store
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _make_routine(name: str) -> RoutineSchema:
    return RoutineSchema(
        name=name,
        steps=[RoutineStepSchema(position=1, ingredient="niacinamide", product_name="Foo Serum")],
    )


class TestListRoutines:
    """Req 7.1-7.3: routine listing is scoped to the authenticated user_id."""

    def test_returns_routines_for_authenticated_user(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.get("/api/me/routines")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["name"] == "Morning"

    def test_scoped_to_user_id_not_shared_across_users(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))

        client = _make_client(profile_store, user_id="uid-bob")
        response = client.get("/api/me/routines")

        assert response.status_code == 200
        assert response.json() == []

    def test_missing_user_returns_500(self, profile_store):
        client = _make_client(profile_store, user_id="uid-ghost")

        response = client.get("/api/me/routines")

        assert response.status_code == 500


class TestDeleteRoutine:
    """Req 7.1-7.3: routine deletion is scoped to the authenticated user_id."""

    def test_deletes_routine(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.delete("/api/me/routines/Morning")

        assert response.status_code == 204
        assert profile_store.get_all_routines("uid-alice") == []

    def test_missing_routine_returns_500(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.delete("/api/me/routines/Nonexistent")

        assert response.status_code == 500

    def test_cannot_delete_another_users_routine(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))

        client = _make_client(profile_store, user_id="uid-bob")
        response = client.delete("/api/me/routines/Morning")

        # Bob has no routine named "Morning" — deletion is scoped to his own
        # user_id, so this reports not-found rather than deleting alice's routine.
        assert response.status_code == 500
        assert profile_store.get_all_routines("uid-alice")[0].name == "Morning"


class TestRenameRoutine:
    """Req 7.1-7.3: routine rename is scoped to the authenticated user_id."""

    def test_renames_routine(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch("/api/me/routines/Morning", json={"new_name": "AM Routine"})

        assert response.status_code == 200
        assert response.json() == {"name": "AM Routine"}
        names = [r.name for r in profile_store.get_all_routines("uid-alice")]
        assert names == ["AM Routine"]

    def test_rejects_empty_new_name(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch("/api/me/routines/Morning", json={"new_name": "   "})

        assert response.status_code == 422

    def test_cannot_rename_another_users_routine(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))

        client = _make_client(profile_store, user_id="uid-bob")
        response = client.patch("/api/me/routines/Morning", json={"new_name": "Hijacked"})

        assert response.status_code == 500
        names = [r.name for r in profile_store.get_all_routines("uid-alice")]
        assert names == ["Morning"]

    def test_rename_colliding_with_existing_routine_returns_409(self, profile_store):
        # security-remediation Req 25.1, 25.3: renaming to a name that
        # collides (case-insensitively) with another of the user's own
        # routines is a structured 409, not a silently-committed duplicate.
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        profile_store.save_routine("uid-alice", _make_routine("Morning"))
        profile_store.save_routine("uid-alice", _make_routine("Evening"))
        client = _make_client(profile_store, user_id="uid-alice")

        response = client.patch("/api/me/routines/Morning", json={"new_name": "evening"})

        assert response.status_code == 409
        names = sorted(r.name for r in profile_store.get_all_routines("uid-alice"))
        assert names == ["Evening", "Morning"]
