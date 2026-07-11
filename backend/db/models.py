"""SQLAlchemy ORM models for Derma6.

Uses SQLAlchemy 2.x declarative syntax with Mapped type annotations
and mapped_column for column definitions.
"""

from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.config import settings

# Verification spike finding (capstone-round Task 27, recorded 2026-07-11 against the
# live OpenRouter API): settings.embedding_model (qwen/qwen3-embedding-8b) produces
# 4096-dimensional vectors — vector(4096) width confirmed empirically, not assumed.
# Re-run the embed_documents() check (see .claude/specs/capstone-round/task-27-findings.md)
# and update this constant, plus alembic/versions/*_user_memory_facts.py, if
# EMBEDDING_MODEL is ever changed — a width change requires a new migration and a full
# re-embed/backfill of existing facts, not just an env var change.
MEMORY_EMBEDDING_DIM = 4096


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class User(Base):
    """Represents a user account with skincare profile information."""

    __tablename__ = "users"

    # Supabase-issued UUID string; always supplied at insert time, never
    # generated locally. Username is a plain, non-unique display name (e.g.
    # first name only) — not an identifier.
    id: Mapped[str] = mapped_column(primary_key=True)
    username: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True, index=True)
    skin_type: Mapped[Optional[str]] = mapped_column(default=None)
    skin_concerns: Mapped[Optional[str]] = mapped_column(default=None)  # JSON-serialised list[str]
    has_shaving_routine: Mapped[Optional[bool]] = mapped_column(default=None)
    beard_style: Mapped[Optional[str]] = mapped_column(default=None)  # "shave" | "trim" | "grow"
    location: Mapped[Optional[str]] = mapped_column(default=None)  # country / region
    medical_flags: Mapped[Optional[str]] = mapped_column(default=None)  # JSON-serialised list[str]
    onboarding_complete: Mapped[bool] = mapped_column(default=False)
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    routines: Mapped[list["Routine"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    introduction_plans: Mapped[list["IntroductionPlan"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    skin_analyses: Mapped[list["SkinAnalysis"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="SkinAnalysis.created_at",
    )
    memory_facts: Mapped[list["UserMemoryFact"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Routine(Base):
    """Represents a skincare routine (e.g., Morning, Evening)."""

    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str]  # e.g., "Morning", "Evening"
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="routines")
    steps: Mapped[list["RoutineStep"]] = relationship(
        back_populates="routine",
        cascade="all, delete-orphan",
    )


class RoutineStep(Base):
    """Represents a single step in a skincare routine."""

    __tablename__ = "routine_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id"))
    position: Mapped[int]  # 1-based canonical order
    ingredient: Mapped[str]
    product_name: Mapped[Optional[str]] = mapped_column(default=None)
    budget_product: Mapped[Optional[str]] = mapped_column(default=None)

    # Relationships
    routine: Mapped["Routine"] = relationship(back_populates="steps")


class ChatSession(Base):
    """Represents a named conversation session for a user."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(primary_key=True)  # UUID string
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[Optional[str]] = mapped_column(default=None)
    total_prompt_tokens: Mapped[int] = mapped_column(default=0)
    total_completion_tokens: Mapped[int] = mapped_column(default=0)
    total_cost_usd: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="chat_sessions")


class IntroductionPlan(Base):
    """Represents a phased introduction plan for new skincare actives."""

    __tablename__ = "introduction_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    plan_json: Mapped[str]  # JSON-serialised list[IntroductionWeek]
    actives_list: Mapped[str]  # JSON-serialised list[str]
    status: Mapped[str] = mapped_column(default="active")  # "active"|"completed"|"paused"
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="introduction_plans")


class SkinAnalysis(Base):
    """Stores a skin analysis snapshot with both a full image and a thumbnail."""

    __tablename__ = "skin_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    condition: Mapped[str]
    confidence: Mapped[float]
    alternatives_json: Mapped[str]  # JSON-serialised list[{condition, probability}]
    reasoning: Mapped[str]
    disclaimer: Mapped[str]
    image_b64: Mapped[Optional[str]] = mapped_column(default=None)      # full-size JPEG (≤2048px)
    thumbnail_b64: Mapped[Optional[str]] = mapped_column(default=None)  # 256px JPEG for list view
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="skin_analyses")


class UserMemoryFact(Base):
    """A durably-stored freeform fact captured from a past conversation
    (capstone-round Bundle 3, Req 9-12) — profile fields already tracked on
    `User` (skin type, concerns, etc.) are deliberately excluded, see
    `backend/agent/memory_extraction.py::filter_denylisted_facts`."""

    __tablename__ = "user_memory_facts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fact_text: Mapped[str]
    # vector(4096) width is fixed to the EMBEDDING_MODEL configured at migration time
    # (MEMORY_EMBEDDING_DIM above, confirmed via capstone-round Task 27's live spike,
    # not guessed) — changing EMBEDDING_MODEL later requires a new migration plus a
    # full re-embed/backfill of existing facts, not just an env var change.
    embedding: Mapped[list[float]] = mapped_column(Vector(MEMORY_EMBEDDING_DIM))
    # Nullable + ON DELETE SET NULL: a fact outlives the session it was extracted
    # from if that session is later deleted (unlike user_id's CASCADE above).
    source_session_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="memory_facts")

    # No ANN index (HNSW/ivfflat) on `embedding`: pgvector caps both at 2000
    # dimensions, but MEMORY_EMBEDDING_DIM is 4096 (verified empirically, Task
    # 27) — `CREATE INDEX ... USING hnsw` fails outright at this width
    # ("column cannot have more than 2000 dimensions for hnsw index",
    # discovered running Task 38's live-Postgres regression pass). Not a
    # practical problem: MemoryStore.search_facts()/find_nearest() always
    # filter by user_id first, so cosine-distance is computed over one user's
    # handful of facts, not the whole table — an unindexed sequential scan is
    # fine at this scale. Revisit only if per-user fact counts grow large
    # enough for that scan to matter (e.g. via a halfvec-typed index, which
    # supports higher dimensionality at reduced precision).


# Database engine — module-level singleton; tables are NOT created here.
# Call init_db() once at application startup (via FastAPI lifespan).
from sqlalchemy import create_engine

engine = create_engine(settings.sqlalchemy_database_url)


def init_db() -> None:
    """Create all tables. Call once at application startup.

    Schema evolution after the initial deployment is handled by Alembic
    migrations (alembic/), not here.
    """
    Base.metadata.create_all(engine)
