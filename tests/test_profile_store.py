"""Unit tests for backend.db.profile_store.ProfileStore (in-memory SQLite)."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import (
    IntroductionPlanSchema,
    IntroductionWeek,
    ProfilePatch,
    RoutineSchema,
    RoutineStepSchema,
)


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_routine(name: str, ingredients: list[str]) -> RoutineSchema:
    steps = [
        RoutineStepSchema(position=i + 1, ingredient=ing, product_name=None)
        for i, ing in enumerate(ingredients)
    ]
    return RoutineSchema(name=name, steps=steps)


def _make_plan(actives: list[str]) -> IntroductionPlanSchema:
    weeks = [
        IntroductionWeek(week=1, active=actives[0], frequency="2x/week", notes="Start"),
        IntroductionWeek(week=2, active=actives[0], frequency="2x/week", notes="Continue"),
    ]
    return IntroductionPlanSchema(actives=actives, weeks=weeks, status="active")


def _make_user(profile_store: ProfileStore, username: str, user_id: str | None = None):
    """Create a user keyed by a Supabase-style UUID string and return its UserProfile.

    `user_id` defaults to a deterministic id derived from the username so tests
    stay readable without needing real UUIDs.
    """
    uid = user_id or f"uid-{username}"
    return profile_store.get_or_create_user_by_id(uid, f"{username}@example.com", username)


# ── User CRUD ─────────────────────────────────────────────────────────────────


class TestGetOrCreateUserById:
    def test_creates_new_user(self, profile_store):
        profile = _make_user(profile_store, "alice")
        assert profile.user_id == "uid-alice"
        assert profile.username == "alice"
        assert profile.onboarding_complete is False

    def test_returns_existing_user_idempotently(self, profile_store):
        _make_user(profile_store, "alice")
        profile_store.update_skin_type("uid-alice", "oily")
        profile = _make_user(profile_store, "alice")
        assert profile.skin_type == "oily"

    def test_different_users_independent(self, profile_store):
        _make_user(profile_store, "alice")
        _make_user(profile_store, "bob")
        profile_store.update_skin_type("uid-alice", "dry")
        bob = profile_store.get_profile("uid-bob")
        assert bob.skin_type is None

    def test_duplicate_username_allowed(self, profile_store):
        one = profile_store.get_or_create_user_by_id("uid-1", "one@example.com", "samename")
        two = profile_store.get_or_create_user_by_id("uid-2", "two@example.com", "samename")
        assert one.username == two.username == "samename"
        assert one.user_id != two.user_id

    def test_duplicate_email_raises(self, profile_store):
        profile_store.get_or_create_user_by_id("uid-1", "same@example.com", "userone")
        with pytest.raises(ProfileStoreError, match="email already registered"):
            profile_store.get_or_create_user_by_id("uid-2", "same@example.com", "usertwo")


class TestGetProfile:
    def test_existing_user_returned(self, profile_store):
        _make_user(profile_store, "carol")
        profile = profile_store.get_profile("uid-carol")
        assert profile.username == "carol"
        assert profile.user_id == "uid-carol"

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError, match="not found"):
            profile_store.get_profile("nonexistent-uid")

    def test_lazy_repair_sets_onboarding(self, profile_store):
        _make_user(profile_store, "dave")
        profile_store.update_skin_type("uid-dave", "oily")
        profile_store.update_skin_concerns("uid-dave", ["acne"])
        profile_store.update_has_shaving_routine("uid-dave", True)
        # Manually set onboarding to False (as if created before the fix)
        from sqlalchemy.orm import Session
        from backend.db.models import User
        with Session(profile_store._engine) as s:
            u = s.get(User, "uid-dave")
            u.onboarding_complete = False
            s.commit()

        profile = profile_store.get_profile("uid-dave")
        assert profile.onboarding_complete is True

    def test_returns_is_admin(self, profile_store):
        _make_user(profile_store, "ivy")
        profile = profile_store.get_profile("uid-ivy")
        assert profile.is_admin is False


# ── Field updates ─────────────────────────────────────────────────────────────


class TestUpdateSkinType:
    def test_sets_skin_type(self, profile_store):
        _make_user(profile_store, "eve")
        profile_store.update_skin_type("uid-eve", "combination")
        assert profile_store.get_profile("uid-eve").skin_type == "combination"

    def test_overrides_existing(self, profile_store):
        _make_user(profile_store, "frank")
        profile_store.update_skin_type("uid-frank", "oily")
        profile_store.update_skin_type("uid-frank", "dry")
        assert profile_store.get_profile("uid-frank").skin_type == "dry"

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.update_skin_type("uid-ghost", "oily")


class TestUpdateSkinConcerns:
    def test_saves_concerns(self, profile_store):
        _make_user(profile_store, "grace")
        profile_store.update_skin_concerns("uid-grace", ["acne", "dark spots"])
        profile = profile_store.get_profile("uid-grace")
        assert "acne" in profile.skin_concerns
        assert "dark spots" in profile.skin_concerns

    def test_replaces_existing_concerns(self, profile_store):
        _make_user(profile_store, "henry")
        profile_store.update_skin_concerns("uid-henry", ["acne"])
        profile_store.update_skin_concerns("uid-henry", ["dryness"])
        assert profile_store.get_profile("uid-henry").skin_concerns == ["dryness"]

    def test_empty_list_clears(self, profile_store):
        _make_user(profile_store, "ivan")
        profile_store.update_skin_concerns("uid-ivan", ["acne"])
        profile_store.update_skin_concerns("uid-ivan", [])
        assert profile_store.get_profile("uid-ivan").skin_concerns == []

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.update_skin_concerns("uid-ghost", ["acne"])


class TestUpdateHasShavingRoutine:
    def test_sets_true(self, profile_store):
        _make_user(profile_store, "jake")
        profile_store.update_has_shaving_routine("uid-jake", True)
        assert profile_store.get_profile("uid-jake").has_shaving_routine is True

    def test_sets_false(self, profile_store):
        _make_user(profile_store, "kim")
        profile_store.update_has_shaving_routine("uid-kim", False)
        assert profile_store.get_profile("uid-kim").has_shaving_routine is False

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.update_has_shaving_routine("uid-ghost", True)


class TestUpdateBeardStyle:
    def test_sets_style_and_derives_shaving_routine(self, profile_store):
        _make_user(profile_store, "liam")
        profile_store.update_beard_style("uid-liam", "trim")
        profile = profile_store.get_profile("uid-liam")
        assert profile.beard_style == "trim"
        assert profile.has_shaving_routine is True

    def test_grow_style_means_no_shaving_routine(self, profile_store):
        _make_user(profile_store, "noah")
        profile_store.update_beard_style("uid-noah", "grow")
        profile = profile_store.get_profile("uid-noah")
        assert profile.beard_style == "grow"
        assert profile.has_shaving_routine is False

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.update_beard_style("uid-ghost", "trim")


class TestUpdateLocation:
    def test_sets_location(self, profile_store):
        _make_user(profile_store, "oscar")
        profile_store.update_location("uid-oscar", "Germany")
        assert profile_store.get_profile("uid-oscar").location == "Germany"

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.update_location("uid-ghost", "Germany")


class TestApplyPatch:
    """security-remediation Req 23.1, 23.2: apply_patch commits all fields
    from a PATCH in a single transaction, or none of them."""

    def test_applies_all_valid_fields_in_one_call(self, profile_store):
        _make_user(profile_store, "petra")
        patch = ProfilePatch(skin_type="oily", location="Berlin", skin_concerns=["acne"])

        profile = profile_store.apply_patch("uid-petra", patch)

        assert profile.skin_type == "oily"
        assert profile.location == "Berlin"
        assert profile.skin_concerns == ["acne"]

    def test_leaves_other_fields_in_same_request_uncommitted_on_invalid_field(self, profile_store):
        _make_user(profile_store, "quinn")
        patch = ProfilePatch(skin_type="oily", beard_style="bogus")

        with pytest.raises(ProfileStoreError, match="beard_style"):
            profile_store.apply_patch("uid-quinn", patch)

        # Nothing from the same request was committed — not even the
        # otherwise-valid skin_type field.
        profile = profile_store.get_profile("uid-quinn")
        assert profile.skin_type is None

    def test_beard_style_derives_has_shaving_routine(self, profile_store):
        _make_user(profile_store, "rosa")
        patch = ProfilePatch(beard_style="trim")

        profile = profile_store.apply_patch("uid-rosa", patch)

        assert profile.beard_style == "trim"
        assert profile.has_shaving_routine is True

    def test_unset_fields_are_left_unchanged(self, profile_store):
        _make_user(profile_store, "sam")
        profile_store.update_skin_type("uid-sam", "dry")
        patch = ProfilePatch(location="Spain")

        profile = profile_store.apply_patch("uid-sam", patch)

        assert profile.location == "Spain"
        assert profile.skin_type == "dry"

    def test_nonexistent_user_raises(self, profile_store):
        patch = ProfilePatch(skin_type="oily")
        with pytest.raises(ProfileStoreError):
            profile_store.apply_patch("uid-ghost", patch)


class TestAddMedicalFlag:
    def test_adds_flag(self, profile_store):
        _make_user(profile_store, "leo")
        profile_store.add_medical_flag("uid-leo", "eczema")
        assert "eczema" in profile_store.get_profile("uid-leo").medical_flags

    def test_duplicate_flag_ignored(self, profile_store):
        _make_user(profile_store, "mia")
        profile_store.add_medical_flag("uid-mia", "rosacea")
        profile_store.add_medical_flag("uid-mia", "rosacea")
        flags = profile_store.get_profile("uid-mia").medical_flags
        assert flags.count("rosacea") == 1

    def test_multiple_flags(self, profile_store):
        _make_user(profile_store, "ned")
        profile_store.add_medical_flag("uid-ned", "eczema")
        profile_store.add_medical_flag("uid-ned", "rosacea")
        flags = profile_store.get_profile("uid-ned").medical_flags
        assert "eczema" in flags
        assert "rosacea" in flags

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.add_medical_flag("uid-ghost", "eczema")


# ── Routine CRUD ──────────────────────────────────────────────────────────────


class TestSaveRoutine:
    def test_saves_routine(self, profile_store):
        _make_user(profile_store, "olivia")
        routine = _make_routine("Morning", ["cleanser", "spf"])
        profile_store.save_routine("uid-olivia", routine)
        result = profile_store.get_routine("uid-olivia", "Morning")
        assert result is not None
        assert result.name == "Morning"
        assert len(result.steps) == 2

    def test_upsert_replaces_steps(self, profile_store):
        _make_user(profile_store, "pat")
        profile_store.save_routine("uid-pat", _make_routine("Evening", ["cleanser"]))
        profile_store.save_routine("uid-pat", _make_routine("Evening", ["cleanser", "retinol"]))
        result = profile_store.get_routine("uid-pat", "Evening")
        assert len(result.steps) == 2

    def test_step_order_preserved(self, profile_store):
        _make_user(profile_store, "quinn")
        profile_store.save_routine("uid-quinn", _make_routine("AM", ["cleanser", "toner", "spf"]))
        result = profile_store.get_routine("uid-quinn", "AM")
        assert [s.ingredient for s in result.steps] == ["cleanser", "toner", "spf"]

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.save_routine("uid-ghost", _make_routine("Morning", ["spf"]))

    def test_same_name_upsert_still_allowed(self, profile_store):
        # An exact-name re-save is a legitimate upsert of the same routine,
        # not a collision (security-remediation Req 25.2).
        _make_user(profile_store, "xena")
        profile_store.save_routine("uid-xena", _make_routine("Morning", ["cleanser"]))
        profile_store.save_routine("uid-xena", _make_routine("Morning", ["cleanser", "spf"]))
        result = profile_store.get_routine("uid-xena", "Morning")
        assert len(result.steps) == 2

    def test_case_insensitive_collision_against_different_routine_rejected(self, profile_store):
        # security-remediation Req 25.2: saving "morning" when "Morning"
        # already exists must not create an ambiguous second entry.
        _make_user(profile_store, "yara")
        profile_store.save_routine("uid-yara", _make_routine("Morning", ["cleanser"]))

        with pytest.raises(ProfileStoreError, match="already exists"):
            profile_store.save_routine("uid-yara", _make_routine("morning", ["retinol"]))

        routines = profile_store.get_all_routines("uid-yara")
        assert len(routines) == 1
        assert routines[0].name == "Morning"


class TestGetAllRoutines:
    def test_returns_all(self, profile_store):
        _make_user(profile_store, "rose")
        profile_store.save_routine("uid-rose", _make_routine("Morning", ["cleanser"]))
        profile_store.save_routine("uid-rose", _make_routine("Evening", ["retinol"]))
        routines = profile_store.get_all_routines("uid-rose")
        assert len(routines) == 2

    def test_empty_for_new_user(self, profile_store):
        _make_user(profile_store, "sam")
        assert profile_store.get_all_routines("uid-sam") == []

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.get_all_routines("uid-ghost")


class TestGetRoutine:
    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.get_routine("uid-ghost", "Morning")

    def test_nonexistent_routine_returns_none(self, profile_store):
        _make_user(profile_store, "gwen")
        assert profile_store.get_routine("uid-gwen", "Ghost Routine") is None


class TestRenameRoutine:
    def test_renames(self, profile_store):
        _make_user(profile_store, "tara")
        profile_store.save_routine("uid-tara", _make_routine("Old Name", ["cleanser"]))
        profile_store.rename_routine("uid-tara", "Old Name", "New Name")
        assert profile_store.get_routine("uid-tara", "New Name") is not None
        assert profile_store.get_routine("uid-tara", "Old Name") is None

    def test_nonexistent_routine_raises(self, profile_store):
        _make_user(profile_store, "uma")
        with pytest.raises(ProfileStoreError, match="not found"):
            profile_store.rename_routine("uid-uma", "Nonexistent", "New")

    def test_rename_to_new_unique_name_succeeds(self, profile_store):
        _make_user(profile_store, "zack")
        profile_store.save_routine("uid-zack", _make_routine("Morning", ["cleanser"]))
        profile_store.rename_routine("uid-zack", "Morning", "AM Routine")
        assert profile_store.get_routine("uid-zack", "AM Routine") is not None

    def test_rename_colliding_case_insensitively_rejected_and_uncommitted(self, profile_store):
        # security-remediation Req 25.1, 25.3: rename must not commit when
        # the target name collides (case-insensitively) with another of the
        # user's own routines.
        _make_user(profile_store, "amy")
        profile_store.save_routine("uid-amy", _make_routine("Morning", ["cleanser"]))
        profile_store.save_routine("uid-amy", _make_routine("Evening", ["retinol"]))

        with pytest.raises(ProfileStoreError, match="already exists"):
            profile_store.rename_routine("uid-amy", "Morning", "evening")

        names = sorted(r.name for r in profile_store.get_all_routines("uid-amy"))
        assert names == ["Evening", "Morning"]

    def test_rename_to_same_name_different_case_is_not_self_collision(self, profile_store):
        # Renaming a routine to a case-variant of its OWN current name must
        # not be rejected as a collision against itself.
        _make_user(profile_store, "ben")
        profile_store.save_routine("uid-ben", _make_routine("morning", ["cleanser"]))
        profile_store.rename_routine("uid-ben", "morning", "Morning")
        assert profile_store.get_routine("uid-ben", "Morning") is not None


class TestDeleteRoutine:
    def test_deletes(self, profile_store):
        _make_user(profile_store, "vera")
        profile_store.save_routine("uid-vera", _make_routine("Morning", ["cleanser"]))
        profile_store.delete_routine("uid-vera", "Morning")
        assert profile_store.get_routine("uid-vera", "Morning") is None

    def test_nonexistent_routine_raises(self, profile_store):
        _make_user(profile_store, "will")
        with pytest.raises(ProfileStoreError, match="not found"):
            profile_store.delete_routine("uid-will", "Ghost Routine")


# ── Introduction plan CRUD ────────────────────────────────────────────────────


class TestIntroductionPlan:
    def test_save_and_retrieve(self, profile_store):
        _make_user(profile_store, "xena")
        plan = _make_plan(["retinol"])
        profile_store.save_introduction_plan("uid-xena", plan)
        retrieved = profile_store.get_introduction_plan("uid-xena")
        assert retrieved is not None
        assert retrieved.actives == ["retinol"]
        assert retrieved.status == "active"

    def test_upsert_replaces(self, profile_store):
        _make_user(profile_store, "yara")
        profile_store.save_introduction_plan("uid-yara", _make_plan(["retinol"]))
        profile_store.save_introduction_plan("uid-yara", _make_plan(["niacinamide"]))
        plan = profile_store.get_introduction_plan("uid-yara")
        assert plan.actives == ["niacinamide"]

    def test_none_when_no_plan(self, profile_store):
        _make_user(profile_store, "zach")
        assert profile_store.get_introduction_plan("uid-zach") is None

    def test_save_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.save_introduction_plan("uid-ghost", _make_plan(["retinol"]))

    def test_get_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.get_introduction_plan("uid-ghost")


# ── Complete onboarding ───────────────────────────────────────────────────────


class TestCompleteOnboarding:
    def test_sets_flag(self, profile_store):
        _make_user(profile_store, "ana")
        profile_store.complete_onboarding("uid-ana")
        assert profile_store.get_profile("uid-ana").onboarding_complete is True

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.complete_onboarding("uid-ghost")


# ── SQLAlchemyError wrapping ──────────────────────────────────────────────────
#
# Every public method wraps an unexpected SQLAlchemyError as ProfileStoreError.
# Almost all of them reach the database first via `_get_user_or_raise`'s
# `session.get(User, user_id)` call, so a single raising mock exercises each
# method's own `except SQLAlchemyError` branch.


def _mock_session_cm(session_mock: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value = session_mock
    cm.__exit__.return_value = False
    return cm


class TestSQLAlchemyErrorWrapping:
    @pytest.mark.parametrize(
        "method_name,args",
        [
            ("get_or_create_user_by_id", ("uid", "e@x.com", "name")),
            ("get_profile", ("uid",)),
            ("update_skin_type", ("uid", "oily")),
            ("update_skin_concerns", ("uid", ["acne"])),
            ("update_has_shaving_routine", ("uid", True)),
            ("update_beard_style", ("uid", "shave")),
            ("update_location", ("uid", "US")),
            ("apply_patch", ("uid", ProfilePatch())),
            ("add_medical_flag", ("uid", "eczema")),
            ("save_routine", ("uid", _make_routine("R", ["Cleanser"]))),
            ("rename_routine", ("uid", "old", "new")),
            ("delete_routine", ("uid", "R")),
            ("get_all_routines", ("uid",)),
            ("get_routine", ("uid", "R")),
            ("save_introduction_plan", ("uid", _make_plan(["Retinol"]))),
            ("get_introduction_plan", ("uid",)),
            ("complete_onboarding", ("uid",)),
        ],
    )
    def test_sqlalchemy_error_wrapped_as_profile_store_error(self, method_name, args):
        store = ProfileStore(engine=MagicMock())
        session_mock = MagicMock()
        session_mock.get.side_effect = SQLAlchemyError("db exploded")

        with patch("backend.db.profile_store.Session", return_value=_mock_session_cm(session_mock)):
            with pytest.raises(ProfileStoreError, match="db exploded"):
                getattr(store, method_name)(*args)

    def test_get_or_create_user_generic_integrity_error_wrapped(self):
        store = ProfileStore(engine=MagicMock())
        session_mock = MagicMock()
        session_mock.get.return_value = None  # no existing user
        session_mock.commit.side_effect = IntegrityError(
            "insert", {}, Exception("UNIQUE constraint failed: users.username")
        )

        with patch("backend.db.profile_store.Session", return_value=_mock_session_cm(session_mock)):
            with pytest.raises(ProfileStoreError, match="UNIQUE constraint failed"):
                store.get_or_create_user_by_id("uid", "e@x.com", "name")
