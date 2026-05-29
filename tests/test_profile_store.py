"""Tests for ProfileStore CRUD layer.

All tests use an in-memory SQLite database so they are isolated, fast,
and leave no filesystem side-effects.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import (
    IntroductionPlanSchema,
    IntroductionWeek,
    RoutineSchema,
    RoutineStepSchema,
)

IN_MEMORY = "sqlite:///:memory:"


@pytest.fixture
def store() -> ProfileStore:
    """Fresh ProfileStore backed by in-memory SQLite for each test."""
    return ProfileStore(db_url=IN_MEMORY)


# ---------------------------------------------------------------------------
# User creation / retrieval
# ---------------------------------------------------------------------------


def test_create_new_user(store: ProfileStore) -> None:
    profile = store.get_or_create_user("alice")
    assert profile.username == "alice"
    assert profile.onboarding_complete is False


def test_get_existing_user(store: ProfileStore) -> None:
    p1 = store.get_or_create_user("bob")
    p2 = store.get_or_create_user("bob")
    assert p1.username == p2.username == "bob"
    # No duplicate row — both calls return the same logical user
    profile = store.get_profile("bob")
    assert profile.username == "bob"


def test_get_profile_not_found(store: ProfileStore) -> None:
    with pytest.raises(ProfileStoreError):
        store.get_profile("nonexistent_user")


# ---------------------------------------------------------------------------
# Field-level updates
# ---------------------------------------------------------------------------


def test_update_skin_type(store: ProfileStore) -> None:
    store.get_or_create_user("charlie")
    store.update_skin_type("charlie", "oily")
    profile = store.get_profile("charlie")
    assert profile.skin_type == "oily"


def test_update_skin_concerns(store: ProfileStore) -> None:
    store.get_or_create_user("dana")
    store.update_skin_concerns("dana", ["acne", "redness"])
    profile = store.get_profile("dana")
    assert profile.skin_concerns == ["acne", "redness"]


def test_update_has_shaving_routine(store: ProfileStore) -> None:
    store.get_or_create_user("evan")
    store.update_has_shaving_routine("evan", True)
    profile = store.get_profile("evan")
    assert profile.has_shaving_routine is True


def test_add_medical_flag(store: ProfileStore) -> None:
    store.get_or_create_user("fiona")
    store.add_medical_flag("fiona", "eczema")
    store.add_medical_flag("fiona", "rosacea")
    # Duplicate should be ignored
    store.add_medical_flag("fiona", "eczema")
    profile = store.get_profile("fiona")
    assert sorted(profile.medical_flags) == ["eczema", "rosacea"]


# ---------------------------------------------------------------------------
# Onboarding completion trigger
# ---------------------------------------------------------------------------


def test_onboarding_complete_when_all_fields_set(store: ProfileStore) -> None:
    store.get_or_create_user("grace")
    assert store.get_profile("grace").onboarding_complete is False

    store.update_skin_type("grace", "dry")
    store.update_skin_concerns("grace", ["sensitivity"])
    store.update_has_shaving_routine("grace", False)
    # onboarding_complete should flip True only after medical_flags is non-null
    assert store.get_profile("grace").onboarding_complete is False
    store.add_medical_flag("grace", "none")
    assert store.get_profile("grace").onboarding_complete is True


# ---------------------------------------------------------------------------
# Null / partial profile tolerance
# ---------------------------------------------------------------------------


def test_null_field_tolerance(store: ProfileStore) -> None:
    """get_profile with a partially filled profile should not crash."""
    store.get_or_create_user("henry")
    store.update_skin_type("henry", "combination")
    # skin_concerns, has_shaving_routine, medical_flags are still None
    profile = store.get_profile("henry")
    assert profile.skin_type == "combination"
    assert profile.skin_concerns == []
    assert profile.has_shaving_routine is None
    assert profile.medical_flags == []
    assert profile.onboarding_complete is False


# ---------------------------------------------------------------------------
# Routine CRUD
# ---------------------------------------------------------------------------


def test_save_and_get_routine(store: ProfileStore) -> None:
    store.get_or_create_user("iris")
    routine = RoutineSchema(
        name="Morning",
        steps=[
            RoutineStepSchema(position=1, ingredient="Cleanser", product_name="CeraVe Hydrating"),
            RoutineStepSchema(position=2, ingredient="Moisturiser", product_name=None),
        ],
    )
    store.save_routine("iris", routine)
    retrieved = store.get_routine("iris", "Morning")

    assert retrieved is not None
    assert retrieved.name == "Morning"
    assert len(retrieved.steps) == 2
    assert retrieved.steps[0].position == 1
    assert retrieved.steps[0].ingredient == "Cleanser"
    assert retrieved.steps[0].product_name == "CeraVe Hydrating"
    assert retrieved.steps[1].ingredient == "Moisturiser"
    assert retrieved.steps[1].product_name is None


def test_save_routine_upserts(store: ProfileStore) -> None:
    """Saving a routine with the same name replaces the previous one."""
    store.get_or_create_user("jack")
    store.save_routine(
        "jack",
        RoutineSchema(
            name="Evening",
            steps=[RoutineStepSchema(position=1, ingredient="Cleanser")],
        ),
    )
    store.save_routine(
        "jack",
        RoutineSchema(
            name="Evening",
            steps=[
                RoutineStepSchema(position=1, ingredient="Micellar Water"),
                RoutineStepSchema(position=2, ingredient="Retinol"),
            ],
        ),
    )
    retrieved = store.get_routine("jack", "Evening")
    assert retrieved is not None
    assert len(retrieved.steps) == 2
    assert retrieved.steps[0].ingredient == "Micellar Water"


def test_get_routine_not_found(store: ProfileStore) -> None:
    store.get_or_create_user("karen")
    result = store.get_routine("karen", "Ghost Routine")
    assert result is None


# ---------------------------------------------------------------------------
# Introduction plan CRUD
# ---------------------------------------------------------------------------


def test_save_introduction_plan(store: ProfileStore) -> None:
    store.get_or_create_user("leo")
    plan = IntroductionPlanSchema(
        actives=["niacinamide", "retinol"],
        weeks=[
            IntroductionWeek(week=1, active="niacinamide", frequency="daily", notes="AM only"),
            IntroductionWeek(week=2, active="retinol", frequency="2x per week", notes="PM only"),
        ],
        status="active",
    )
    store.save_introduction_plan("leo", plan)
    retrieved = store.get_introduction_plan("leo")

    assert retrieved is not None
    assert retrieved.actives == ["niacinamide", "retinol"]
    assert retrieved.status == "active"
    assert len(retrieved.weeks) == 2
    assert retrieved.weeks[0].week == 1
    assert retrieved.weeks[0].active == "niacinamide"
    assert retrieved.weeks[1].frequency == "2x per week"


def test_save_introduction_plan_upserts(store: ProfileStore) -> None:
    """Saving a new plan replaces the previous one."""
    store.get_or_create_user("mia")
    store.save_introduction_plan(
        "mia",
        IntroductionPlanSchema(
            actives=["vitamin-c"],
            weeks=[IntroductionWeek(week=1, active="vitamin-c", frequency="daily", notes="")],
            status="active",
        ),
    )
    store.save_introduction_plan(
        "mia",
        IntroductionPlanSchema(
            actives=["AHA"],
            weeks=[IntroductionWeek(week=1, active="AHA", frequency="1x per week", notes="PM")],
            status="paused",
        ),
    )
    retrieved = store.get_introduction_plan("mia")
    assert retrieved is not None
    assert retrieved.actives == ["AHA"]
    assert retrieved.status == "paused"


def test_get_introduction_plan_not_found(store: ProfileStore) -> None:
    store.get_or_create_user("noah")
    result = store.get_introduction_plan("noah")
    assert result is None


# ---------------------------------------------------------------------------
# Routine rename / delete / list
# ---------------------------------------------------------------------------


def _make_routine(name: str, *ingredients: str) -> RoutineSchema:
    return RoutineSchema(
        name=name,
        steps=[
            RoutineStepSchema(position=i + 1, ingredient=ing)
            for i, ing in enumerate(ingredients)
        ],
    )


def test_rename_routine(store: ProfileStore) -> None:
    store.get_or_create_user("oliver")
    store.save_routine("oliver", _make_routine("Morning", "Cleanser", "SPF"))
    store.rename_routine("oliver", "Morning", "AM Routine")
    assert store.get_routine("oliver", "Morning") is None
    renamed = store.get_routine("oliver", "AM Routine")
    assert renamed is not None
    assert renamed.name == "AM Routine"


def test_rename_routine_not_found_raises(store: ProfileStore) -> None:
    store.get_or_create_user("petra")
    with pytest.raises(ProfileStoreError):
        store.rename_routine("petra", "Ghost", "New Name")


def test_delete_routine(store: ProfileStore) -> None:
    store.get_or_create_user("quinn")
    store.save_routine("quinn", _make_routine("Evening", "Retinol", "Moisturiser"))
    store.delete_routine("quinn", "Evening")
    assert store.get_routine("quinn", "Evening") is None


def test_delete_routine_not_found_raises(store: ProfileStore) -> None:
    store.get_or_create_user("ruth")
    with pytest.raises(ProfileStoreError):
        store.delete_routine("ruth", "NonExistent")


def test_get_all_routines_empty(store: ProfileStore) -> None:
    store.get_or_create_user("sam")
    assert store.get_all_routines("sam") == []


def test_get_all_routines_multiple(store: ProfileStore) -> None:
    store.get_or_create_user("tara")
    store.save_routine("tara", _make_routine("Morning", "Cleanser", "SPF"))
    store.save_routine("tara", _make_routine("Evening", "Retinol"))
    routines = store.get_all_routines("tara")
    assert len(routines) == 2
    names = {r.name for r in routines}
    assert names == {"Morning", "Evening"}


# ---------------------------------------------------------------------------
# Error paths (nonexistent user propagates ProfileStoreError)
# ---------------------------------------------------------------------------


def test_update_skin_type_missing_user_raises(store: ProfileStore) -> None:
    with pytest.raises(ProfileStoreError):
        store.update_skin_type("ghost", "oily")


def test_update_skin_concerns_missing_user_raises(store: ProfileStore) -> None:
    with pytest.raises(ProfileStoreError):
        store.update_skin_concerns("ghost", ["acne"])


def test_update_has_shaving_routine_missing_user_raises(store: ProfileStore) -> None:
    with pytest.raises(ProfileStoreError):
        store.update_has_shaving_routine("ghost", True)


def test_add_medical_flag_missing_user_raises(store: ProfileStore) -> None:
    with pytest.raises(ProfileStoreError):
        store.add_medical_flag("ghost", "eczema")


# ---------------------------------------------------------------------------
# SQLAlchemy error propagation (engine-level errors wrapped as ProfileStoreError)
# ---------------------------------------------------------------------------


def _store_with_bad_commit() -> ProfileStore:
    """Return a ProfileStore whose Session.commit always raises SQLAlchemyError."""
    store = ProfileStore(db_url="sqlite:///:memory:")
    original_session = store._engine.connect

    real_session_cls = Session

    class _BadSession(real_session_cls):
        def commit(self):
            raise SQLAlchemyError("simulated DB error")

    return store, _BadSession


def test_update_skin_type_sqlalchemy_error_raises(store: ProfileStore) -> None:
    store.get_or_create_user("ua")
    with patch("backend.db.profile_store.Session") as MockSession:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=MagicMock(
            query=MagicMock(return_value=MagicMock(
                filter_by=MagicMock(return_value=MagicMock(first=MagicMock(return_value=MagicMock(id=1))))
            )),
            commit=MagicMock(side_effect=SQLAlchemyError("db error")),
        ))
        ctx.__exit__ = MagicMock(return_value=False)
        MockSession.return_value = ctx
        with pytest.raises(ProfileStoreError):
            store.update_skin_type("ua", "oily")


def test_save_routine_sqlalchemy_error_raises(store: ProfileStore) -> None:
    store.get_or_create_user("ub")
    with patch("backend.db.profile_store.Session") as MockSession:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=MagicMock(
            query=MagicMock(return_value=MagicMock(
                filter_by=MagicMock(return_value=MagicMock(first=MagicMock(return_value=MagicMock(id=1))))
            )),
            commit=MagicMock(side_effect=SQLAlchemyError("db error")),
            flush=MagicMock(),
            add=MagicMock(),
            delete=MagicMock(),
        ))
        ctx.__exit__ = MagicMock(return_value=False)
        MockSession.return_value = ctx
        with pytest.raises(ProfileStoreError):
            store.save_routine("ub", _make_routine("Test", "Cleanser"))
