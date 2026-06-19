"""Profile store: CRUD layer for user skincare profiles.

All public methods accept/return plain Pydantic objects (never ORM instances).
JSON serialisation/deserialisation is handled transparently for list fields.
SQLAlchemy errors are caught, logged at ERROR, and re-raised as ProfileStoreError.
"""

import json
import logging
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Base, IntroductionPlan, Routine, RoutineStep, User
from backend.schemas import (
    IntroductionPlanSchema,
    IntroductionWeek,
    RoutineSchema,
    RoutineStepSchema,
    UserProfile,
)

logger = logging.getLogger(__name__)


class ProfileStoreError(Exception):
    """Raised when a ProfileStore operation fails."""

    pass


class ProfileStore:
    """CRUD interface over the SQLite user/profile tables."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        resolved_url = db_url or settings.sqlite_url
        self._engine = create_engine(resolved_url)
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # User helpers
    # ------------------------------------------------------------------

    def get_or_create_user(self, username: str) -> UserProfile:
        """Return existing user or create a new one with default values."""
        try:
            with Session(self._engine) as session:
                user = session.query(User).filter_by(username=username).first()
                if user is None:
                    user = User(
                        username=username,
                        onboarding_complete=False,
                        medical_flags=None,
                    )
                    session.add(user)
                    session.commit()
                    session.refresh(user)
                return self._user_to_profile(user)
        except SQLAlchemyError as exc:
            logger.error("get_or_create_user failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_profile(self, username: str) -> UserProfile:
        """Return UserProfile for an existing user.

        Raises:
            ProfileStoreError: if the user does not exist.
        """
        try:
            with Session(self._engine) as session:
                user = session.query(User).filter_by(username=username).first()
                if user is None:
                    raise ProfileStoreError(f"User '{username}' not found.")
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
            logger.error("get_profile failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Field-level updates
    # ------------------------------------------------------------------

    def update_skin_type(self, username: str, skin_type: str) -> None:
        """Set the user's skin type."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                user.skin_type = skin_type
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_skin_type failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def update_skin_concerns(self, username: str, concerns: list[str]) -> None:
        """Replace the user's skin concerns list."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                user.skin_concerns = json.dumps(concerns)
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_skin_concerns failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def update_has_shaving_routine(self, username: str, has_shaving: bool) -> None:
        """Set whether the user has a shaving routine."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                user.has_shaving_routine = has_shaving
                self._check_onboarding_complete(session, user)
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("update_has_shaving_routine failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def add_medical_flag(self, username: str, flag: str) -> None:
        """Append a medical flag, ignoring duplicates."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
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
            logger.error("add_medical_flag failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Routine CRUD
    # ------------------------------------------------------------------

    def save_routine(self, username: str, routine: RoutineSchema) -> None:
        """Upsert a routine by name: delete existing steps, recreate everything."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                existing = (
                    session.query(Routine)
                    .filter_by(user_id=user.id, name=routine.name)
                    .first()
                )
                if existing is not None:
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
                        )
                    )
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("save_routine failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def rename_routine(self, username: str, old_name: str, new_name: str) -> None:
        """Rename a routine by its current name."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                routine = (
                    session.query(Routine)
                    .filter_by(user_id=user.id, name=old_name)
                    .first()
                )
                if routine is None:
                    raise ProfileStoreError(f"Routine '{old_name}' not found.")
                routine.name = new_name
                session.commit()
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("rename_routine failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def delete_routine(self, username: str, name: str) -> None:
        """Delete a routine and all its steps by name."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
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
            logger.error("delete_routine failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_all_routines(self, username: str) -> list[RoutineSchema]:
        """Return all saved routines for a user, ordered by creation time."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
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
                        )
                        for s in sorted(routine.steps, key=lambda s: s.position)
                    ]
                    result.append(RoutineSchema(name=routine.name, steps=steps))
                return result
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_all_routines failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_routine(self, username: str, name: str) -> Optional[RoutineSchema]:
        """Return a RoutineSchema by name, or None if not found."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
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
                    )
                    for s in sorted(routine.steps, key=lambda s: s.position)
                ]
                return RoutineSchema(name=routine.name, steps=steps)
        except ProfileStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_routine failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Introduction plan CRUD
    # ------------------------------------------------------------------

    def save_introduction_plan(self, username: str, plan: IntroductionPlanSchema) -> None:
        """Upsert the introduction plan for a user (one plan per user)."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
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
            logger.error("save_introduction_plan failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    def get_introduction_plan(self, username: str) -> Optional[IntroductionPlanSchema]:
        """Return the user's introduction plan, or None if not found."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
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
            logger.error("get_introduction_plan failed for '%s': %s", username, exc)
            raise ProfileStoreError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_user_or_raise(self, session: Session, username: str) -> User:
        """Return the User ORM object or raise ProfileStoreError."""
        user = session.query(User).filter_by(username=username).first()
        if user is None:
            raise ProfileStoreError(f"User '{username}' not found.")
        return user

    def _check_onboarding_complete(self, session: Session, user: User) -> None:
        """Set onboarding_complete=True when the three mandatory profile fields are set.

        medical_flags is intentionally excluded: the agent skips add_medical_flag_tool
        when the user has no conditions, so it may remain None for healthy users.
        """
        if (
            user.skin_type is not None
            and user.skin_concerns is not None
            and user.has_shaving_routine is not None
        ):
            user.onboarding_complete = True

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
            username=user.username,
            skin_type=user.skin_type,
            skin_concerns=skin_concerns,
            has_shaving_routine=user.has_shaving_routine,
            medical_flags=medical_flags,
            onboarding_complete=user.onboarding_complete,
        )
