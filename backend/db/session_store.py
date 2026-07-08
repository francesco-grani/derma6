"""Session store: CRUD for chat sessions.

Each user can have multiple named sessions. session_id is a UUID string used
as the key in SQLChatMessageHistory (message_store table).

Migration: existing users with legacy username-keyed history get a
"Previous conversations" session created lazily on first call to get_sessions().
"""

import logging
import uuid
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Base, ChatSession, User

logger = logging.getLogger(__name__)


class SessionStoreError(Exception):
    pass


class SessionStore:
    def __init__(self, db_url: Optional[str] = None, engine=None) -> None:
        if engine is not None:
            # Shared engine path: init_db() already ran create_all.
            self._engine = engine
        else:
            url = db_url or settings.sqlalchemy_database_url
            self._engine = create_engine(url)
            Base.metadata.create_all(self._engine)

    # ── Public API ──────────────────────────────────────────────────────────

    def create_session(self, username: str) -> str:
        """Create a new session for user and return its session_id (UUID)."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                session_id = str(uuid.uuid4())
                session.add(ChatSession(id=session_id, user_id=user.id, title=None))
                session.commit()
                logger.info("Created session %s for %s", session_id, username)
                return session_id
        except SessionStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("create_session failed for %s: %s", username, exc)
            raise SessionStoreError(str(exc)) from exc

    def get_sessions(self, username: str) -> list[dict]:
        """Return all sessions for a user ordered by updated_at desc.

        On first call, lazily migrates existing legacy history (session_id=username)
        by creating a 'Previous conversations' session entry for it.
        """
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                self._maybe_migrate_legacy(session, user, username)
                rows = (
                    session.query(ChatSession)
                    .filter_by(user_id=user.id)
                    .order_by(ChatSession.updated_at.desc())
                    .all()
                )
                return [
                    {
                        "session_id": r.id,
                        "title": r.title,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    }
                    for r in rows
                ]
        except SessionStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("get_sessions failed for %s: %s", username, exc)
            raise SessionStoreError(str(exc)) from exc

    def get_active_session_id(self, username: str) -> Optional[str]:
        """Return the most recently updated session_id, or None if no sessions exist."""
        sessions = self.get_sessions(username)
        return sessions[0]["session_id"] if sessions else None

    def update_title(self, session_id: str, title: str) -> None:
        """Set or replace the title of a session."""
        try:
            with Session(self._engine) as session:
                row = session.get(ChatSession, session_id)
                if row is None:
                    return
                row.title = title[:80]
                session.commit()
        except SQLAlchemyError as exc:
            logger.error("update_title failed for session %s: %s", session_id, exc)

    def touch_session(self, session_id: str) -> None:
        """Update updated_at so the session rises to the top of the list."""
        try:
            with Session(self._engine) as session:
                row = session.get(ChatSession, session_id)
                if row is None:
                    return
                # Force updated_at to refresh by writing a no-op change
                row.title = row.title
                session.commit()
        except SQLAlchemyError as exc:
            logger.error("touch_session failed for %s: %s", session_id, exc)

    def delete_session(self, session_id: str, username: str) -> None:
        """Delete a session (and its messages via message_store cascade in code)."""
        try:
            with Session(self._engine) as session:
                user = self._get_user_or_raise(session, username)
                row = (
                    session.query(ChatSession)
                    .filter_by(id=session_id, user_id=user.id)
                    .first()
                )
                if row is None:
                    raise SessionStoreError(f"Session {session_id!r} not found.")
                session.delete(row)
                # Also remove messages from LangChain's message_store table
                session.execute(
                    text("DELETE FROM message_store WHERE session_id = :sid"),
                    {"sid": session_id},
                )
                session.commit()
                logger.info("Deleted session %s for %s", session_id, username)
        except SessionStoreError:
            raise
        except SQLAlchemyError as exc:
            logger.error("delete_session failed for %s/%s: %s", username, session_id, exc)
            raise SessionStoreError(str(exc)) from exc

    def add_token_usage(
        self,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        """Accumulate token counts and cost onto the session row."""
        try:
            with Session(self._engine) as session:
                row = session.get(ChatSession, session_id)
                if row is None:
                    return
                row.total_prompt_tokens += prompt_tokens
                row.total_completion_tokens += completion_tokens
                row.total_cost_usd += cost_usd
                session.commit()
        except SQLAlchemyError as exc:
            logger.error("add_token_usage failed for %s: %s", session_id, exc)

    def session_message_count(self, session_id: str) -> int:
        """Return the number of messages stored for this session_id."""
        try:
            with Session(self._engine) as session:
                result = session.execute(
                    text("SELECT COUNT(*) FROM message_store WHERE session_id = :sid"),
                    {"sid": session_id},
                )
                row = result.fetchone()
                return row[0] if row else 0
        except SQLAlchemyError:
            return 0

    # ── Private helpers ─────────────────────────────────────────────────────

    def _get_user_or_raise(self, session: Session, username: str) -> User:
        user = session.query(User).filter_by(username=username).first()
        if user is None:
            raise SessionStoreError(f"User '{username}' not found.")
        return user

    def _maybe_migrate_legacy(self, session: Session, user: User, username: str) -> None:
        """If legacy message_store rows exist (session_id=username) and no ChatSession
        covers them yet, create a 'Previous conversations' session for them."""
        existing_ids = {r.id for r in session.query(ChatSession).filter_by(user_id=user.id).all()}
        if username in existing_ids:
            return  # already migrated

        try:
            result = session.execute(
                text("SELECT COUNT(*) FROM message_store WHERE session_id = :sid"),
                {"sid": username},
            )
            count = result.fetchone()[0]
        except Exception:
            return  # message_store doesn't exist yet

        if count > 0:
            legacy = ChatSession(
                id=username,
                user_id=user.id,
                title="Previous conversations",
            )
            session.add(legacy)
            session.commit()
            logger.info("Migrated legacy history for %s (%d messages)", username, count)
