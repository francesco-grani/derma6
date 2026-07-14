"""Profile store: CRUD layer for user skincare profiles.

All public methods accept/return plain Pydantic objects (never ORM instances).
JSON serialisation/deserialisation is handled transparently for list fields.
SQLAlchemy errors are caught, logged at ERROR, and re-raised as ProfileStoreError.
"""

import json
import logging
from typing import Optional

from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Base, IntroductionPlan, Routine, RoutineStep, User
from backend.schemas import (
    IntroductionPlanSchema,
    IntroductionWeek,
    ProfilePatch,
    RoutineSchema,
    RoutineStepSchema,
    UserProfile,
)

logger = logging.getLogger(__name__)

VALID_BEARD_STYLES = {"shave", "trim", "grow"}


class ProfileStoreError(Exception):
    """Raised when a ProfileStore operation fails."""

    pass


class ProfileStore:
    """CRUD interface over the SQLite user/profile tables."""

    def __init__(self, db_url: Optional[str] = None, engine=None) -> None:
        if engine is not None:
            self._engine = engine
        else:
            url = db_url or settings.sqlalchemy_database_url
            self._engine = create_engine(url)
            Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # User helpers
    # ------------------------------------------------------------------

    def get_or_create_user_by_id(self, user_id: str, email: str, username: str) -> UserProfile:
        """The ONLY user-creation path (replaces get_or_create_user's old
        create-with-just-a-key semantics). `user_id` is the Supabase-issued UUID,
        supplied by the caller — never generated locally (Req 7.1).

        Idempotent: a repeat call with the same `user_id` (e.g. a retried
        /complete-signup request for the same Supabase identity) returns the
        existing row rather than erroring.

        Raises:
            ProfileStoreError: 'email already registered' when the uniqueness
                constraint on email is violated by a different user_id.
                Username is not unique and never raises.
        """
        try:
            with Session(self._engine) as session:
                existing = session.get(User, user_id)
                if existing is not None:
                    return self._user_to_profile(existing)

                user = User(
                    id=user_id,
                    username=username,
                    email=email,
                    onboarding_complete=False,
                    medical_flags=None,
                )
                session.add(user)
                try:
                    session.commit()
                except IntegrityError as exc:
                    session.rollback()
                    detail = str(exc.orig).lower()
                    if "email" in detail:
                        raise ProfileStoreError("email already registered") from exc
                    raise ProfileStoreError(str(exc)) from exc
                session.refresh(user)
                return self._user_to_profile(user)
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_or_create_user_by_id failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_profile(self, user_id: str) -> UserProfile:
        """Return UserProfile for an existing user.

        Raises:
            ProfileStoreError: if the user does not exist.
        """
        try:
            with Session(self._engine) as session:
                user = session.get(User, user_id)
                if user is None:
                    raise ProfileStoreError(f"User '{user_id}' not found.")
                # Lazy repair: correct the flag for accounts onboarded before the
                # medical_flags bug was fixed (they have all 3 fields but flag=False).
                if not user.onboarding_complete and (
                    user.skin_type is not None
                    and user.skin_concerns is not None
                    and user.has_shaving_routine is not None
                ):
                    user.onboarding_complete = True
                    session.commit()
                return self._user_to_profile(user)
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_profile failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Field-level updates
    # ------------------------------------------------------------------

    def update_skin_type(self, user_id: str, skin_type: str) -> None:
        """Set the user's skin type."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                user.skin_type = skin_type
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_skin_type failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def update_skin_concerns(self, user_id: str, concerns: list[str]) -> None:
        """Replace the user's skin concerns list."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                user.skin_concerns = json.dumps(concerns)
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_skin_concerns failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def update_has_shaving_routine(self, user_id: str, has_shaving: bool) -> None:
        """Set whether the user has a shaving routine."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                user.has_shaving_routine = has_shaving
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_has_shaving_routine failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def update_beard_style(self, user_id: str, style: str) -> None:
        """Set the user's facial hair style ('shave', 'trim', or 'grow')."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                user.beard_style = style
                user.has_shaving_routine = style in ("shave", "trim")
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_beard_style failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def update_location(self, user_id: str, location: str) -> None:
        """Set the user's country for product availability filtering."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                user.location = location
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_location failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def apply_patch(self, user_id: str, patch: ProfilePatch) -> UserProfile:
        """Apply a `PATCH /api/me/profile` request atomically (security-
        remediation Req 23.1, 23.2): every field on `patch` is validated
        before any of them are written, and all writes commit in a single
        transaction — an invalid field can never leave previously-valid
        fields from the same request partially committed, the way calling
        the field-level `update_*` methods above in sequence could.
        """
        if patch.beard_style is not None and patch.beard_style not in VALID_BEARD_STYLES:
            raise ProfileStoreError(f"beard_style must be one of {VALID_BEARD_STYLES}")

        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                if patch.skin_type is not None:
                    user.skin_type = patch.skin_type.strip()
                if patch.beard_style is not None:
                    user.beard_style = patch.beard_style
                    user.has_shaving_routine = patch.beard_style in ("shave", "trim")
                if patch.location is not None:
                    user.location = patch.location.strip()
                if patch.skin_concerns is not None:
                    user.skin_concerns = json.dumps(
                        [c.strip() for c in patch.skin_concerns if c.strip()]
                    )
                self._check_onboarding_complete(session, user)
                session.commit()
                session.refresh(user)
                return self._user_to_profile(user)
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("apply_patch failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def add_medical_flag(self, user_id: str, flag: str) -> None:
        """Append a medical flag, ignoring duplicates."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                existing: list[str] = (
                    json.loads(user.medical_flags) if user.medical_flags else []
                )
                if flag not in existing:
                    existing.append(flag)
                user.medical_flags = json.dumps(existing)
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("add_medical_flag failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Routine CRUD
    # ------------------------------------------------------------------

    def _find_colliding_routine(
        self, session: Session, user_id: str, name: str, exclude_routine_id: Optional[int] = None
    ) -> Optional[Routine]:
        """Return an existing routine of `user_id` whose name matches `name`
        case-insensitively, other than `exclude_routine_id` itself, or None
        (security-remediation Req 25.1, 25.2)."""
        query = session.query(Routine).filter(
            Routine.user_id == user_id, func.lower(Routine.name) == name.lower()
        )
        if exclude_routine_id is not None:
            query = query.filter(Routine.id != exclude_routine_id)
        return query.first()

    def save_routine(self, user_id: str, routine: RoutineSchema) -> None:
        """Upsert a routine by name: delete existing steps, recreate everything.

        A case-insensitive name collision against a *different* existing
        routine is rejected (security-remediation Req 25.2) — an exact-name
        match is still treated as an upsert of that same routine, not a
        collision.
        """
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                existing = (
                    session.query(Routine)
                    .filter_by(user_id=user.id, name=routine.name)
                    .first()
                )
                if existing is None:
                    collision = self._find_colliding_routine(session, user.id, routine.name)
                    if collision is not None:
                        raise ProfileStoreError(
                            f"A routine named '{collision.name}' already exists "
                            "(names must be unique, case-insensitive)."
                        )
                else:
                    session.delete(existing)
                    session.flush()

                new_routine = Routine(user_id=user.id, name=routine.name)
                session.add(new_routine)
                session.flush()  # populate new_routine.id

                for step in routine.steps:
                    session.add(
                        RoutineStep(
                            routine_id=new_routine.id,
                            position=step.position,
                            ingredient=step.ingredient,
                            product_name=step.product_name,
                            budget_product=step.budget_product,
                        )
                    )
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("save_routine failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def rename_routine(self, user_id: str, old_name: str, new_name: str) -> None:
        """Rename a routine by its current name.

        Rejects a case-insensitive collision against another of the user's
        existing routines (security-remediation Req 25.1) without
        committing.
        """
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                routine = (
                    session.query(Routine)
                    .filter_by(user_id=user.id, name=old_name)
                    .first()
                )
                if routine is None:
                    raise ProfileStoreError(f"Routine '{old_name}' not found.")
                collision = self._find_colliding_routine(
                    session, user.id, new_name, exclude_routine_id=routine.id
                )
                if collision is not None:
                    raise ProfileStoreError(
                        f"A routine named '{collision.name}' already exists "
                        "(names must be unique, case-insensitive)."
                    )
                routine.name = new_name
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("rename_routine failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def delete_routine(self, user_id: str, name: str) -> None:
        """Delete a routine and all its steps by name."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                routine = (
                    session.query(Routine)
                    .filter_by(user_id=user.id, name=name)
                    .first()
                )
                if routine is None:
                    raise ProfileStoreError(f"Routine '{name}' not found.")
                session.delete(routine)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("delete_routine failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_all_routines(self, user_id: str) -> list[RoutineSchema]:
        """Return all saved routines for a user, ordered by creation time."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                routines = (
                    session.query(Routine)
                    .filter_by(user_id=user.id)
                    .order_by(Routine.created_at)
                    .all()
                )
                result = []
                for routine in routines:
                    steps = [
                        RoutineStepSchema(
                            position=s.position,
                            ingredient=s.ingredient,
                            product_name=s.product_name,
                            budget_product=s.budget_product,
                        )
                        for s in sorted(routine.steps, key=lambda s: s.position)
                    ]
                    result.append(RoutineSchema(name=routine.name, steps=steps))
                return result
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_all_routines failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_routine(self, user_id: str, name: str) -> Optional[RoutineSchema]:
        """Return a RoutineSchema by name, or None if not found."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                routine = (
                    session.query(Routine)
                    .filter_by(user_id=user.id, name=name)
                    .first()
                )
                if routine is None:
                    return None
                steps = [
                    RoutineStepSchema(
                        position=s.position,
                        ingredient=s.ingredient,
                        product_name=s.product_name,
                        budget_product=s.budget_product,
                    )
                    for s in sorted(routine.steps, key=lambda s: s.position)
                ]
                return RoutineSchema(name=routine.name, steps=steps)
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_routine failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Introduction plan CRUD
    # ------------------------------------------------------------------

    def save_introduction_plan(self, user_id: str, plan: IntroductionPlanSchema) -> None:
        """Upsert the introduction plan for a user (one plan per user)."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                existing = (
                    session.query(IntroductionPlan).filter_by(user_id=user.id).first()
                )
                if existing is not None:
                    session.delete(existing)
                    session.flush()

                weeks_data = [w.model_dump() for w in plan.weeks]
                new_plan = IntroductionPlan(
                    user_id=user.id,
                    plan_json=json.dumps(weeks_data),
                    actives_list=json.dumps(plan.actives),
                    status=plan.status,
                )
                session.add(new_plan)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("save_introduction_plan failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_introduction_plan(self, user_id: str) -> Optional[IntroductionPlanSchema]:
        """Return the user's introduction plan, or None if not found."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                plan = (
                    session.query(IntroductionPlan).filter_by(user_id=user.id).first()
                )
                if plan is None:
                    return None
                weeks = [IntroductionWeek(**w) for w in json.loads(plan.plan_json)]
                actives = json.loads(plan.actives_list)
                return IntroductionPlanSchema(
                    actives=actives,
                    weeks=weeks,
                    status=plan.status,
                )
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_introduction_plan failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_user_or_raise(self, session: Session, user_id: str) -> User:
        """Return the User ORM object or raise ProfileStoreError."""
        user = session.get(User, user_id)
        if user is None:
            raise ProfileStoreError(f"User '{user_id}' not found.")
        return user

    def complete_onboarding(self, user_id: str) -> None:
        """Explicitly mark onboarding as complete (called by finalize_onboarding_tool after HITL review)."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, user_id)
                user.onboarding_complete = True
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("complete_onboarding failed for '%s': %s", user_id, exc)
            raise ProfileStoreError(str(exc)) from exc

    def _check_onboarding_complete(self, session: Session, user: User) -> None:
        """No-op: onboarding_complete is now set only via complete_onboarding() after HITL review.

        medical_flags is intentionally excluded: the agent skips add_medical_flag_tool
        when the user has no conditions, so it may remain None for healthy users.
        """

    @staticmethod
    def _user_to_profile(user: User) -> UserProfile:
        """Convert a User ORM object to a UserProfile Pydantic schema."""
        skin_concerns = (
            json.loads(user.skin_concerns) if user.skin_concerns else []
        )
        medical_flags = (
            json.loads(user.medical_flags) if user.medical_flags else []
        )
        return UserProfile(
            user_id=user.id,
            username=user.username,
            skin_type=user.skin_type,
            skin_concerns=skin_concerns,
            has_shaving_routine=user.has_shaving_routine,
            beard_style=getattr(user, "beard_style", None),
            location=getattr(user, "location", None),
            medical_flags=medical_flags,
            onboarding_complete=user.onboarding_complete,
            is_admin=user.is_admin,
        )
