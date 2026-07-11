"""Model-level tests for backend.db.models's UUID primary-key rework (Bundle 2).

Locks in the new `User.id`/`*.user_id` string-typed schema — and the removal of
`password_hash` in favour of a Supabase-issued identity — before the Alembic
migration (Task 12) and store rekeying (Task 16) land on top of it.
"""

import uuid

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from backend.db.models import (
    Base,
    ChatSession,
    IntroductionPlan,
    Routine,
    SkinAnalysis,
    User,
)


@pytest.fixture
def engine():
    """Fresh in-memory SQLite engine with all tables created."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def _make_user(user_id: str, username: str = "alice", email: str = "alice@example.com") -> User:
    return User(id=user_id, username=username, email=email)


class TestUserPrimaryKey:
    def test_accepts_string_uuid_id(self, engine):
        """User.id is a plain string PK — a Supabase UUID, never locally generated."""
        user_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(_make_user(user_id))
            session.commit()

            fetched = session.get(User, user_id)
            assert fetched is not None
            assert fetched.id == user_id
            assert isinstance(fetched.id, str)

    def test_id_column_is_not_autoincrement(self, engine):
        """The PK must always be supplied at insert time — no local generation.
        `autoincrement` only ever applies to single-column integer PKs in
        SQLAlchemy, so the real guarantee is behavioural: a String PK column
        never gets a value generated for it, and omitting `id` fails outright."""
        col = User.__table__.c.id
        assert col.primary_key is True
        assert col.type.python_type is str

        with Session(engine) as session:
            session.add(User(username="nouid", email="nouid@example.com"))
            with pytest.raises(Exception):
                session.commit()

    def test_password_hash_removed(self):
        """Supabase owns credentials now; no local password_hash column remains."""
        assert not hasattr(User, "password_hash")
        assert "password_hash" not in User.__table__.c

    def test_email_column_unique_and_indexed(self):
        col = User.__table__.c.email
        assert col.unique is True
        assert col.index is True

    def test_username_is_not_unique(self):
        """Username is a plain display name (e.g. first name), not an identifier."""
        col = User.__table__.c.username
        assert col.unique is not True
        assert col.primary_key is False

    def test_duplicate_email_rejected(self, engine):
        with Session(engine) as session:
            session.add(_make_user(str(uuid.uuid4()), username="alice", email="dup@example.com"))
            session.commit()

            session.add(_make_user(str(uuid.uuid4()), username="bob", email="dup@example.com"))
            with pytest.raises(Exception):
                session.commit()

    def test_duplicate_username_allowed(self, engine):
        with Session(engine) as session:
            session.add(_make_user(str(uuid.uuid4()), username="alice", email="a1@example.com"))
            session.commit()

            session.add(_make_user(str(uuid.uuid4()), username="alice", email="a2@example.com"))
            session.commit()  # no IntegrityError


class TestForeignKeyTypesCascade:
    """Routine/ChatSession/IntroductionPlan/SkinAnalysis.user_id all follow User.id's
    type (Req 7.2) — every dependent table accepts and round-trips string values."""

    @pytest.fixture
    def user_id(self, engine) -> str:
        uid = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(_make_user(uid))
            session.commit()
        return uid

    def test_routine_user_id_accepts_string(self, engine, user_id):
        with Session(engine) as session:
            routine = Routine(user_id=user_id, name="Morning")
            session.add(routine)
            session.commit()
            session.refresh(routine)

            assert routine.user_id == user_id
            assert isinstance(routine.user_id, str)

    def test_chat_session_user_id_accepts_string(self, engine, user_id):
        with Session(engine) as session:
            chat_session = ChatSession(id=str(uuid.uuid4()), user_id=user_id)
            session.add(chat_session)
            session.commit()
            session.refresh(chat_session)

            assert chat_session.user_id == user_id
            assert isinstance(chat_session.user_id, str)

    def test_introduction_plan_user_id_accepts_string(self, engine, user_id):
        with Session(engine) as session:
            plan = IntroductionPlan(
                user_id=user_id,
                plan_json="[]",
                actives_list="[]",
            )
            session.add(plan)
            session.commit()
            session.refresh(plan)

            assert plan.user_id == user_id
            assert isinstance(plan.user_id, str)

    def test_skin_analysis_user_id_accepts_string(self, engine, user_id):
        with Session(engine) as session:
            analysis = SkinAnalysis(
                user_id=user_id,
                condition="Acne",
                confidence=0.9,
                alternatives_json="[]",
                reasoning="Test reasoning",
                disclaimer="Not medical advice.",
            )
            session.add(analysis)
            session.commit()
            session.refresh(analysis)

            assert analysis.user_id == user_id
            assert isinstance(analysis.user_id, str)

    @pytest.mark.parametrize(
        "table_name",
        ["routines", "chat_sessions", "introduction_plans", "skin_analyses"],
    )
    def test_user_id_column_type_is_string(self, engine, table_name):
        """Cross-check the column's Python type directly via SQLAlchemy's inspector,
        independent of SQLite's loose type affinity (which would let an int silently
        round-trip even if the mapped type were wrong)."""
        inspector = inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        assert "user_id" in columns

        table = Base.metadata.tables[table_name]
        assert table.c.user_id.type.python_type is str

    def test_user_cascade_delete_removes_dependents(self, engine, user_id):
        """Sanity check that the relationship/cascade wiring still works after the
        FK type change (unrelated to the type itself, but cheap to lock in here)."""
        with Session(engine) as session:
            session.add(Routine(user_id=user_id, name="Evening"))
            session.commit()

            user = session.get(User, user_id)
            session.delete(user)
            session.commit()

            remaining = session.query(Routine).filter_by(user_id=user_id).all()
            assert remaining == []
