"""Tests for SQLAlchemy ORM models.

Uses an in-memory SQLite database to avoid test database side effects.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.models import Base, IntroductionPlan, Routine, RoutineStep, User


@pytest.fixture
def in_memory_engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(in_memory_engine):
    """Create a database session for a test."""
    connection = in_memory_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


class TestModels:
    """Test suite for ORM models."""

    def test_all_tables_exist(self, in_memory_engine):
        """Test that all four tables exist in the database."""
        inspector = __import__("sqlalchemy").inspect(in_memory_engine)
        table_names = inspector.get_table_names()

        assert "users" in table_names
        assert "routines" in table_names
        assert "routine_steps" in table_names
        assert "introduction_plans" in table_names

    def test_user_creation_with_only_username(self, db_session):
        """Test that a User can be created with only username (nullable fields absent)."""
        user = User(username="john_doe")
        db_session.add(user)
        db_session.commit()

        retrieved_user = db_session.query(User).filter_by(username="john_doe").first()
        assert retrieved_user is not None
        assert retrieved_user.username == "john_doe"
        assert retrieved_user.skin_type is None
        assert retrieved_user.skin_concerns is None
        assert retrieved_user.has_shaving_routine is None
        assert retrieved_user.medical_flags is None

    def test_user_onboarding_complete_defaults_to_false(self, db_session):
        """Test that onboarding_complete defaults to False."""
        user = User(username="jane_doe")
        db_session.add(user)
        db_session.commit()

        retrieved_user = db_session.query(User).filter_by(username="jane_doe").first()
        assert retrieved_user.onboarding_complete is False

    def test_routine_linked_to_user_via_fk(self, db_session):
        """Test that Routine can be linked to User via foreign key."""
        user = User(username="test_user")
        db_session.add(user)
        db_session.commit()

        routine = Routine(user_id=user.id, name="Morning")
        db_session.add(routine)
        db_session.commit()

        retrieved_routine = db_session.query(Routine).filter_by(name="Morning").first()
        assert retrieved_routine is not None
        assert retrieved_routine.user_id == user.id
        assert retrieved_routine.user.username == "test_user"

    def test_routine_step_linked_to_routine_via_fk(self, db_session):
        """Test that RoutineStep can be linked to Routine via foreign key."""
        user = User(username="test_user")
        db_session.add(user)
        db_session.commit()

        routine = Routine(user_id=user.id, name="Morning")
        db_session.add(routine)
        db_session.commit()

        step = RoutineStep(
            routine_id=routine.id,
            position=1,
            ingredient="Cleanser",
            product_name="CeraVe Foaming Cleanser",
        )
        db_session.add(step)
        db_session.commit()

        retrieved_step = db_session.query(RoutineStep).filter_by(position=1).first()
        assert retrieved_step is not None
        assert retrieved_step.routine_id == routine.id
        assert retrieved_step.ingredient == "Cleanser"
        assert retrieved_step.product_name == "CeraVe Foaming Cleanser"
        assert retrieved_step.routine.name == "Morning"

    def test_introduction_plan_linked_to_user_via_fk(self, db_session):
        """Test that IntroductionPlan can be linked to User via foreign key."""
        user = User(username="test_user")
        db_session.add(user)
        db_session.commit()

        plan = IntroductionPlan(
            user_id=user.id,
            plan_json='[{"week": 1, "actives": ["niacinamide"]}]',
            actives_list='["niacinamide", "retinol"]',
            status="active",
        )
        db_session.add(plan)
        db_session.commit()

        retrieved_plan = db_session.query(IntroductionPlan).filter_by(status="active").first()
        assert retrieved_plan is not None
        assert retrieved_plan.user_id == user.id
        assert retrieved_plan.user.username == "test_user"
        assert "niacinamide" in retrieved_plan.plan_json

    def test_nullable_fields_accept_none(self, db_session):
        """Test that all nullable fields accept None without error."""
        user = User(
            username="nullable_test",
            skin_type=None,
            skin_concerns=None,
            has_shaving_routine=None,
            medical_flags=None,
        )
        db_session.add(user)
        db_session.commit()

        retrieved_user = db_session.query(User).filter_by(username="nullable_test").first()
        assert retrieved_user.skin_type is None
        assert retrieved_user.skin_concerns is None
        assert retrieved_user.has_shaving_routine is None
        assert retrieved_user.medical_flags is None

    def test_routine_step_nullable_product_name(self, db_session):
        """Test that RoutineStep.product_name can be None."""
        user = User(username="test_user")
        db_session.add(user)
        db_session.commit()

        routine = Routine(user_id=user.id, name="Morning")
        db_session.add(routine)
        db_session.commit()

        step = RoutineStep(
            routine_id=routine.id,
            position=1,
            ingredient="Moisturizer",
            product_name=None,
        )
        db_session.add(step)
        db_session.commit()

        retrieved_step = db_session.query(RoutineStep).filter_by(position=1).first()
        assert retrieved_step.product_name is None

    def test_user_created_at_is_datetime(self, db_session):
        """Test that created_at is a datetime."""
        user = User(username="datetime_test")
        db_session.add(user)
        db_session.commit()

        retrieved_user = db_session.query(User).filter_by(username="datetime_test").first()
        assert isinstance(retrieved_user.created_at, datetime)

    def test_user_updated_at_is_datetime(self, db_session):
        """Test that updated_at is a datetime."""
        user = User(username="datetime_test")
        db_session.add(user)
        db_session.commit()

        retrieved_user = db_session.query(User).filter_by(username="datetime_test").first()
        assert isinstance(retrieved_user.updated_at, datetime)
