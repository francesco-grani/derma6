"""Unit tests for backend.db.profile_store.ProfileStore (in-memory SQLite)."""

import pytest

from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import (
    IntroductionPlanSchema,
    IntroductionWeek,
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


class TestUpdateHasShavingRoutine:
    def test_sets_true(self, profile_store):
        _make_user(profile_store, "jake")
        profile_store.update_has_shaving_routine("uid-jake", True)
        assert profile_store.get_profile("uid-jake").has_shaving_routine is True

    def test_sets_false(self, profile_store):
        _make_user(profile_store, "kim")
        profile_store.update_has_shaving_routine("uid-kim", False)
        assert profile_store.get_profile("uid-kim").has_shaving_routine is False


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


class TestUpdateLocation:
    def test_sets_location(self, profile_store):
        _make_user(profile_store, "oscar")
        profile_store.update_location("uid-oscar", "Germany")
        assert profile_store.get_profile("uid-oscar").location == "Germany"


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


# ── Complete onboarding ───────────────────────────────────────────────────────


class TestCompleteOnboarding:
    def test_sets_flag(self, profile_store):
        _make_user(profile_store, "ana")
        profile_store.complete_onboarding("uid-ana")
        assert profile_store.get_profile("uid-ana").onboarding_complete is True

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.complete_onboarding("uid-ghost")
