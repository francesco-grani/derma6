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

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.admin import _eval_state, router as admin_router
from backend.api.admin import run_eval
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


class TestRunEvalLaunchRace:
    """Task 73, Req 26.1/26.2: `run_eval()` flips `_eval_state["status"]` to
    "running" synchronously, before scheduling the background task — not only
    inside `_run_eval_background()` after it starts — so two near-simultaneous
    requests can't both observe "idle" and both launch a run.

    `run_eval()` is called directly (not through `TestClient`) so these tests
    exercise the race at the coroutine level without also running the real
    `_run_eval_background()` (which shells out to the eval runner subprocess).
    """

    @pytest.fixture(autouse=True)
    def _reset_eval_state(self):
        original = dict(_eval_state)
        yield
        _eval_state.clear()
        _eval_state.update(original)

    @pytest.mark.asyncio
    async def test_flips_status_synchronously_before_returning(self):
        _eval_state["status"] = "idle"
        background_tasks = MagicMock()

        await run_eval(background_tasks=background_tasks, _="uid-admin")

        assert _eval_state["status"] == "running"
        background_tasks.add_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_two_rapid_fire_calls_only_one_schedules_background_task(self):
        """Simulates two near-simultaneous `POST /api/admin/eval/run` calls via
        `asyncio.gather` — since `run_eval()` has no `await` between its status
        check and its flip, the first call to actually run always completes
        before the second call's check executes, so this reproduces the same
        interleaving a real concurrent-request race would hit."""
        _eval_state["status"] = "idle"
        background_tasks_a = MagicMock()
        background_tasks_b = MagicMock()

        results = await asyncio.gather(
            run_eval(background_tasks=background_tasks_a, _="uid-admin"),
            run_eval(background_tasks=background_tasks_b, _="uid-admin"),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], HTTPException)
        assert failures[0].status_code == 409

        scheduled_count = sum(
            1 for bg in (background_tasks_a, background_tasks_b) if bg.add_task.called
        )
        assert scheduled_count == 1

    @pytest.mark.asyncio
    async def test_second_call_rejected_while_already_running(self):
        _eval_state["status"] = "running"
        background_tasks = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await run_eval(background_tasks=background_tasks, _="uid-admin")

        assert exc_info.value.status_code == 409
        background_tasks.add_task.assert_not_called()
