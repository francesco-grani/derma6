"""Unit tests for backend.db.profile_store.ProfileStore (in-memory SQLite)."""

import pytest

from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import (
    IntroductionPlanSchema,
    IntroductionWeek,
    RoutineSchema,
    RoutineStepSchema,
    UserProfile,
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


# ── User CRUD ─────────────────────────────────────────────────────────────────


class TestGetOrCreateUser:
    def test_creates_new_user(self, profile_store):
        profile = profile_store.get_or_create_user("alice")
        assert profile.username == "alice"
        assert profile.onboarding_complete is False

    def test_returns_existing_user(self, profile_store):
        profile_store.get_or_create_user("alice")
        profile_store.update_skin_type("alice", "oily")
        profile = profile_store.get_or_create_user("alice")
        assert profile.skin_type == "oily"

    def test_different_users_independent(self, profile_store):
        profile_store.get_or_create_user("alice")
        profile_store.get_or_create_user("bob")
        profile_store.update_skin_type("alice", "dry")
        bob = profile_store.get_or_create_user("bob")
        assert bob.skin_type is None


class TestGetProfile:
    def test_existing_user_returned(self, profile_store):
        profile_store.get_or_create_user("carol")
        profile = profile_store.get_profile("carol")
        assert profile.username == "carol"

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError, match="not found"):
            profile_store.get_profile("nonexistent_user")

    def test_lazy_repair_sets_onboarding(self, profile_store):
        profile_store.get_or_create_user("dave")
        profile_store.update_skin_type("dave", "oily")
        profile_store.update_skin_concerns("dave", ["acne"])
        profile_store.update_has_shaving_routine("dave", True)
        # Manually set onboarding to False (as if created before the fix)
        from sqlalchemy.orm import Session
        from backend.db.models import User
        with Session(profile_store._engine) as s:
            u = s.query(User).filter_by(username="dave").first()
            u.onboarding_complete = False
            s.commit()

        profile = profile_store.get_profile("dave")
        assert profile.onboarding_complete is True


# ── Field updates ─────────────────────────────────────────────────────────────


class TestUpdateSkinType:
    def test_sets_skin_type(self, profile_store):
        profile_store.get_or_create_user("eve")
        profile_store.update_skin_type("eve", "combination")
        assert profile_store.get_profile("eve").skin_type == "combination"

    def test_overrides_existing(self, profile_store):
        profile_store.get_or_create_user("frank")
        profile_store.update_skin_type("frank", "oily")
        profile_store.update_skin_type("frank", "dry")
        assert profile_store.get_profile("frank").skin_type == "dry"

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.update_skin_type("ghost", "oily")


class TestUpdateSkinConcerns:
    def test_saves_concerns(self, profile_store):
        profile_store.get_or_create_user("grace")
        profile_store.update_skin_concerns("grace", ["acne", "dark spots"])
        profile = profile_store.get_profile("grace")
        assert "acne" in profile.skin_concerns
        assert "dark spots" in profile.skin_concerns

    def test_replaces_existing_concerns(self, profile_store):
        profile_store.get_or_create_user("henry")
        profile_store.update_skin_concerns("henry", ["acne"])
        profile_store.update_skin_concerns("henry", ["dryness"])
        assert profile_store.get_profile("henry").skin_concerns == ["dryness"]

    def test_empty_list_clears(self, profile_store):
        profile_store.get_or_create_user("ivan")
        profile_store.update_skin_concerns("ivan", ["acne"])
        profile_store.update_skin_concerns("ivan", [])
        assert profile_store.get_profile("ivan").skin_concerns == []


class TestUpdateHasShavingRoutine:
    def test_sets_true(self, profile_store):
        profile_store.get_or_create_user("jake")
        profile_store.update_has_shaving_routine("jake", True)
        assert profile_store.get_profile("jake").has_shaving_routine is True

    def test_sets_false(self, profile_store):
        profile_store.get_or_create_user("kim")
        profile_store.update_has_shaving_routine("kim", False)
        assert profile_store.get_profile("kim").has_shaving_routine is False


class TestAddMedicalFlag:
    def test_adds_flag(self, profile_store):
        profile_store.get_or_create_user("leo")
        profile_store.add_medical_flag("leo", "eczema")
        assert "eczema" in profile_store.get_profile("leo").medical_flags

    def test_duplicate_flag_ignored(self, profile_store):
        profile_store.get_or_create_user("mia")
        profile_store.add_medical_flag("mia", "rosacea")
        profile_store.add_medical_flag("mia", "rosacea")
        flags = profile_store.get_profile("mia").medical_flags
        assert flags.count("rosacea") == 1

    def test_multiple_flags(self, profile_store):
        profile_store.get_or_create_user("ned")
        profile_store.add_medical_flag("ned", "eczema")
        profile_store.add_medical_flag("ned", "rosacea")
        flags = profile_store.get_profile("ned").medical_flags
        assert "eczema" in flags
        assert "rosacea" in flags


# ── Routine CRUD ──────────────────────────────────────────────────────────────


class TestSaveRoutine:
    def test_saves_routine(self, profile_store):
        profile_store.get_or_create_user("olivia")
        routine = _make_routine("Morning", ["cleanser", "spf"])
        profile_store.save_routine("olivia", routine)
        result = profile_store.get_routine("olivia", "Morning")
        assert result is not None
        assert result.name == "Morning"
        assert len(result.steps) == 2

    def test_upsert_replaces_steps(self, profile_store):
        profile_store.get_or_create_user("pat")
        profile_store.save_routine("pat", _make_routine("Evening", ["cleanser"]))
        profile_store.save_routine("pat", _make_routine("Evening", ["cleanser", "retinol"]))
        result = profile_store.get_routine("pat", "Evening")
        assert len(result.steps) == 2

    def test_step_order_preserved(self, profile_store):
        profile_store.get_or_create_user("quinn")
        profile_store.save_routine("quinn", _make_routine("AM", ["cleanser", "toner", "spf"]))
        result = profile_store.get_routine("quinn", "AM")
        assert [s.ingredient for s in result.steps] == ["cleanser", "toner", "spf"]

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.save_routine("ghost", _make_routine("Morning", ["spf"]))


class TestGetAllRoutines:
    def test_returns_all(self, profile_store):
        profile_store.get_or_create_user("rose")
        profile_store.save_routine("rose", _make_routine("Morning", ["cleanser"]))
        profile_store.save_routine("rose", _make_routine("Evening", ["retinol"]))
        routines = profile_store.get_all_routines("rose")
        assert len(routines) == 2

    def test_empty_for_new_user(self, profile_store):
        profile_store.get_or_create_user("sam")
        assert profile_store.get_all_routines("sam") == []


class TestRenameRoutine:
    def test_renames(self, profile_store):
        profile_store.get_or_create_user("tara")
        profile_store.save_routine("tara", _make_routine("Old Name", ["cleanser"]))
        profile_store.rename_routine("tara", "Old Name", "New Name")
        assert profile_store.get_routine("tara", "New Name") is not None
        assert profile_store.get_routine("tara", "Old Name") is None

    def test_nonexistent_routine_raises(self, profile_store):
        profile_store.get_or_create_user("uma")
        with pytest.raises(ProfileStoreError, match="not found"):
            profile_store.rename_routine("uma", "Nonexistent", "New")


class TestDeleteRoutine:
    def test_deletes(self, profile_store):
        profile_store.get_or_create_user("vera")
        profile_store.save_routine("vera", _make_routine("Morning", ["cleanser"]))
        profile_store.delete_routine("vera", "Morning")
        assert profile_store.get_routine("vera", "Morning") is None

    def test_nonexistent_routine_raises(self, profile_store):
        profile_store.get_or_create_user("will")
        with pytest.raises(ProfileStoreError, match="not found"):
            profile_store.delete_routine("will", "Ghost Routine")


# ── Introduction plan CRUD ────────────────────────────────────────────────────


class TestIntroductionPlan:
    def test_save_and_retrieve(self, profile_store):
        profile_store.get_or_create_user("xena")
        plan = _make_plan(["retinol"])
        profile_store.save_introduction_plan("xena", plan)
        retrieved = profile_store.get_introduction_plan("xena")
        assert retrieved is not None
        assert retrieved.actives == ["retinol"]
        assert retrieved.status == "active"

    def test_upsert_replaces(self, profile_store):
        profile_store.get_or_create_user("yara")
        profile_store.save_introduction_plan("yara", _make_plan(["retinol"]))
        profile_store.save_introduction_plan("yara", _make_plan(["niacinamide"]))
        plan = profile_store.get_introduction_plan("yara")
        assert plan.actives == ["niacinamide"]

    def test_none_when_no_plan(self, profile_store):
        profile_store.get_or_create_user("zach")
        assert profile_store.get_introduction_plan("zach") is None


# ── Complete onboarding ───────────────────────────────────────────────────────


class TestCompleteOnboarding:
    def test_sets_flag(self, profile_store):
        profile_store.get_or_create_user("ana")
        profile_store.complete_onboarding("ana")
        assert profile_store.get_profile("ana").onboarding_complete is True

    def test_nonexistent_user_raises(self, profile_store):
        with pytest.raises(ProfileStoreError):
            profile_store.complete_onboarding("ghost_user")
