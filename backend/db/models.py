"""SQLAlchemy ORM models for Derma6.

Uses SQLAlchemy 2.x declarative syntax with Mapped type annotations
and mapped_column for column definitions.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.config import settings


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
