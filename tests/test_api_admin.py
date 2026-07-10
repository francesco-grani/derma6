"""Tests for backend.api.admin's `require_admin` guard (capstone-round Bundle 2,
Task 26, Req 8.2/8.3).

Route-level tests exercised through FastAPI's `TestClient` against a minimal
app that mounts only `backend.api.admin.router` (mirroring
`tests/test_api_profile.py`'s approach). `get_current_user` is overridden via
`dependency_overrides` to return a fixed `user_id` string directly — note this
override has no notion of an `is_admin` claim at all, since Supabase JWTs
never carry one (Req 8.2). `get_db` is overridden to point at a per-test
temporary SQLite engine (shared with a `ProfileStore` used to create users),
so `require_admin`'s `db.get(User, user_id).is_admin` check exercises the
real ORM column rather than a mock.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.admin import router as admin_router
from backend.auth import get_current_user
from backend.db.deps import get_db
from backend.db.models import User


def _make_client(engine, user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)

    def _get_db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = _get_db_override
    # This override — the sole source of `user_id` for every admin route —
    # returns a bare string. It carries no `is_admin` field or JWT claim of
    # any kind, so any test where the admin decision comes out correctly
    # here is proof the decision was sourced from the DB, not the token.
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _set_is_admin(engine, user_id: str, value: bool) -> None:
    with Session(engine) as session:
        user = session.get(User, user_id)
        user.is_admin = value
        session.commit()


class TestRequireAdminDefaultsToNonAdmin:
    """Req 8.3: a user record with no administrator flag explicitly set
    defaults to non-administrator status, and is therefore denied."""

    def test_freshly_created_user_is_denied_admin_routes(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-alice", "alice@example.com", "alice")
        # Sanity check on the default itself before exercising the route.
        assert profile_store.get_profile("uid-alice").is_admin is False

        client = _make_client(profile_store._engine, user_id="uid-alice")
        response = client.get("/api/admin/eval/status")

        assert response.status_code == 403

    def test_unknown_user_id_is_denied(self, profile_store):
        # No row exists at all for this id — require_admin's `if not user`
        # branch must deny, not raise.
        client = _make_client(profile_store._engine, user_id="uid-ghost")

        response = client.get("/api/admin/eval/status")

        assert response.status_code == 403


class TestRequireAdminSourcedFromDbNotJwt:
    """Req 8.2: the administrator flag is evaluated from the app's own
    `users.is_admin` column, never from the auth provider's token — the
    token (represented here by the get_current_user override) carries no
    role information at all, so a correct grant/revoke decision can only
    come from the DB row."""

    def test_admin_flag_in_db_grants_access(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-bob", "bob@example.com", "bob")
        _set_is_admin(profile_store._engine, "uid-bob", True)

        client = _make_client(profile_store._engine, user_id="uid-bob")
        response = client.get("/api/admin/eval/status")

        assert response.status_code == 200

    def test_revoking_db_flag_revokes_access_with_identical_token_identity(self, profile_store):
        # Same user_id throughout (i.e. the same "token" identity per the
        # get_current_user override) — only the DB row changes. If admin
        # status came from anywhere but the DB, this flip would have no
        # effect on the route's behaviour.
        profile_store.get_or_create_user_by_id("uid-carol", "carol@example.com", "carol")
        client = _make_client(profile_store._engine, user_id="uid-carol")

        _set_is_admin(profile_store._engine, "uid-carol", True)
        assert client.get("/api/admin/eval/status").status_code == 200

        _set_is_admin(profile_store._engine, "uid-carol", False)
        assert client.get("/api/admin/eval/status").status_code == 403
