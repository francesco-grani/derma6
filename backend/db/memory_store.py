"""Memory store: CRUD + similarity search for cross-session memory facts.

Requires a live Postgres with the `vector` extension enabled (capstone-round
Bundle 3) — `.cosine_distance()` is a pgvector-SQLAlchemy operator with no
SQLite equivalent, unlike ProfileStore/SessionStore's plain-column CRUD.
"""

import logging
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Base, User, UserMemoryFact
from backend.schemas import MemoryFactSchema

logger = logging.getLogger(__name__)


class MemoryStoreError(Exception):
    pass


class MemoryStore:
    def __init__(self, db_url: Optional[str] = None, engine=None) -> None:
        if engine is not None:
            # Shared engine path: init_db() already ran create_all.
            self._engine = engine
        else:
            url = db_url or settings.sqlalchemy_database_url
            self._engine = create_engine(url)
            Base.metadata.create_all(self._engine)

    # ── Public API ──────────────────────────────────────────────────────────

    def add_fact(
        self,
        user_id: str,
        session_id: Optional[str],
        fact_text: str,
        embedding: list[float],
    ) -> MemoryFactSchema:
        """Persist a new fact for a user."""
        try:
            with Session(self._engine) as session:
                self._get_user_or_raise(session, user_id)
                row = UserMemoryFact(
                    user_id=user_id,
                    fact_text=fact_text,
                    embedding=embedding,
                    source_session_id=session_id,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._row_to_schema(row)
        except MemoryStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("add_fact failed for %s: %s", user_id, exc)
            raise MemoryStoreError(str(exc)) from exc

    def search_facts(
        self, user_id: str, query_embedding: list[float], top_k: int
    ) -> list[MemoryFactSchema]:
        """Return up to `top_k` facts for `user_id` nearest to `query_embedding`
        (cosine distance, ascending — nearest first).

        The `filter_by(user_id=user_id)` WHERE clause is what enforces
        per-user isolation (Req 11.5) — a query for one user must never
        surface another user's facts.
        """
        try:
            with Session(self._engine) as session:
                rows = (
                    session.query(UserMemoryFact)
                    .filter_by(user_id=user_id)
                    .order_by(UserMemoryFact.embedding.cosine_distance(query_embedding))
                    .limit(top_k)
                    .all()
                )
                return [self._row_to_schema(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error("search_facts failed for %s: %s", user_id, exc)
            raise MemoryStoreError(str(exc)) from exc

    def find_nearest(
        self, user_id: str, candidate_embedding: list[float]
    ) -> Optional[tuple[MemoryFactSchema, float]]:
        """Return the single nearest existing fact for `user_id` and its cosine
        distance to `candidate_embedding`, or None if the user has no facts yet.
        Used to dedup a newly-extracted fact against what is already stored
        (see `backend/agent/memory_extraction.py::is_near_duplicate`)."""
        try:
            with Session(self._engine) as session:
                distance_col = UserMemoryFact.embedding.cosine_distance(
                    candidate_embedding
                ).label("distance")
                row = (
                    session.query(UserMemoryFact, distance_col)
                    .filter_by(user_id=user_id)
                    .order_by(distance_col)
                    .first()
                )
                if row is None:
                    return None
                fact_row, distance = row
                return self._row_to_schema(fact_row), float(distance)
        except SQLAlchemyError as exc:
            logger.error("find_nearest failed for %s: %s", user_id, exc)
            raise MemoryStoreError(str(exc)) from exc

    def get_all_facts(self, user_id: str) -> list[MemoryFactSchema]:
        """Return every fact stored for a user, newest first."""
        try:
            with Session(self._engine) as session:
                rows = (
                    session.query(UserMemoryFact)
                    .filter_by(user_id=user_id)
                    .order_by(UserMemoryFact.created_at.desc())
                    .all()
                )
                return [self._row_to_schema(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error("get_all_facts failed for %s: %s", user_id, exc)
            raise MemoryStoreError(str(exc)) from exc

    def delete_all_for_user(self, user_id: str) -> None:
        """Delete every fact stored for a user."""
        try:
            with Session(self._engine) as session:
                session.query(UserMemoryFact).filter_by(user_id=user_id).delete()
                session.commit()
        except SQLAlchemyError as exc:
            logger.error("delete_all_for_user failed for %s: %s", user_id, exc)
            raise MemoryStoreError(str(exc)) from exc

    # ── Private helpers ─────────────────────────────────────────────────────

    def _get_user_or_raise(self, session: Session, user_id: str) -> User:
        user = session.get(User, user_id)
        if user is None:
            raise MemoryStoreError(f"User '{user_id}' not found.")
        return user

    @staticmethod
    def _row_to_schema(row: UserMemoryFact) -> MemoryFactSchema:
        return MemoryFactSchema(
            id=row.id,
            fact_text=row.fact_text,
            source_session_id=row.source_session_id,
            created_at=row.created_at,
        )
