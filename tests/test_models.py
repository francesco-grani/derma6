"""Model-level tests for backend.db.models's UUID primary-key rework (Bundle 2).

Locks in the new `User.id`/`*.user_id` string-typed schema — and the removal of
`password_hash` in favour of a Supabase-issued identity — before the Alembic
migration (Task 12) and store rekeying (Task 16) land on top of it.
"""

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import (
    Base,
    ChatSession,
    IntroductionPlan,
    MEMORY_EMBEDDING_DIM,
    Routine,
    SkinAnalysis,
    User,
    UserMemoryFact,
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


@pytest.mark.pgvector
class TestUserMemoryFact:
    """Requires a live Postgres with the `vector` extension available (Task 27
    confirmed 0.8.2 is available on the configured Supabase project) — the
    `Vector(4096)` column type has no SQLite equivalent, unlike the
    plain-String columns covered by the rest of this module. Opt-in via
    `pytest --run-pgvector` (see root conftest.py), matching the `eval` marker's
    opt-in convention for tests requiring live external state.

    Runs against a dedicated, disposable Postgres schema (not `public`) on the
    configured DATABASE_URL, torn down after each test — never touches
    pre-existing rows/tables in the target database's default schema."""

    _TEST_SCHEMA = "test_models_user_memory_fact"

    @pytest.fixture
    def pg_engine(self):
        bootstrap = create_engine(settings.sqlalchemy_database_url)
        with bootstrap.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {self._TEST_SCHEMA} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {self._TEST_SCHEMA}"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        bootstrap.dispose()

        eng = create_engine(
            settings.sqlalchemy_database_url,
            connect_args={"options": f"-csearch_path={self._TEST_SCHEMA},public"},
        )
        # checkfirst=False is required, not just an optimisation: with `public`
        # on the search_path (needed only so the `vector` type name resolves —
        # it lives in `public` from CREATE EXTENSION), checkfirst=True's
        # reflection can find same-named tables already in `public` and skip
        # creating them here — silently routing subsequent inserts into the
        # real `public.users`/`public.chat_sessions` tables instead of this
        # schema's fresh ones. Discovered running this bundle's live-Postgres
        # regression pass (Task 38) — caught, no data lost, but confirm with a
        # reflection check below rather than trusting search_path alone.
        Base.metadata.create_all(
            eng,
            tables=[User.__table__, ChatSession.__table__, UserMemoryFact.__table__],
            checkfirst=False,
        )
        with eng.begin() as conn:
            created_here = set(inspect(conn).get_table_names(schema=self._TEST_SCHEMA))
        assert {"users", "chat_sessions", "user_memory_facts"} <= created_here, (
            f"Expected tables were not created inside {self._TEST_SCHEMA} — refusing to "
            "run this test rather than risk operating against the wrong schema."
        )
        yield eng
        with create_engine(settings.sqlalchemy_database_url).begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {self._TEST_SCHEMA} CASCADE"))
        eng.dispose()

    @pytest.fixture
    def user_id(self, pg_engine) -> str:
        uid = str(uuid.uuid4())
        with Session(pg_engine) as session:
            session.add(User(id=uid, username="alice", email=f"{uid}@example.com"))
            session.commit()
        return uid

    def test_embedding_column_width_matches_verified_dimensionality(self):
        assert UserMemoryFact.__table__.c.embedding.type.dim == MEMORY_EMBEDDING_DIM

    def test_constructs_and_persists_row_with_embedding(self, pg_engine, user_id):
        embedding = [0.01] * MEMORY_EMBEDDING_DIM
        with Session(pg_engine) as session:
            fact = UserMemoryFact(
                user_id=user_id,
                fact_text="Prefers fragrance-free products",
                embedding=embedding,
                source_session_id=None,
            )
            session.add(fact)
            session.commit()
            session.refresh(fact)

            assert fact.id is not None
            assert fact.fact_text == "Prefers fragrance-free products"
            assert len(fact.embedding) == MEMORY_EMBEDDING_DIM

    def test_cascade_delete_on_user_removes_facts(self, pg_engine, user_id):
        with Session(pg_engine) as session:
            session.add(
                UserMemoryFact(
                    user_id=user_id,
                    fact_text="Lives in a humid climate",
                    embedding=[0.02] * MEMORY_EMBEDDING_DIM,
                )
            )
            session.commit()

            user = session.get(User, user_id)
            session.delete(user)
            session.commit()

            remaining = session.query(UserMemoryFact).filter_by(user_id=user_id).all()
            assert remaining == []

    def test_source_session_set_null_on_session_delete(self, pg_engine, user_id):
        with Session(pg_engine) as session:
            chat_session = ChatSession(id=str(uuid.uuid4()), user_id=user_id)
            session.add(chat_session)
            session.commit()

            fact = UserMemoryFact(
                user_id=user_id,
                fact_text="Uses well water",
                embedding=[0.03] * MEMORY_EMBEDDING_DIM,
                source_session_id=chat_session.id,
            )
            session.add(fact)
            session.commit()

            session.delete(chat_session)
            session.commit()

            session.refresh(fact)
            assert fact.source_session_id is None
