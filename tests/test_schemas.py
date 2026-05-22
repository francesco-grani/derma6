"""Tests for Pydantic v2 application-layer schemas.

Tests cover:
- BackendRequest validation (username, message)
- BackendResponse defaults
- UserProfile defaults
- ToolResult construction
"""

import pytest
from pydantic import ValidationError

from backend.schemas import (
    BackendRequest,
    BackendResponse,
    IntroductionPlanSchema,
    IntroductionWeek,
    RoutineSchema,
    RoutineStepSchema,
    ToolResult,
    UserProfile,
)


class TestBackendRequest:
    """Tests for BackendRequest schema validation."""

    def test_backend_request_valid(self):
        """Test that a valid BackendRequest constructs without error."""
        req = BackendRequest(username="john_doe", message="Hello, how are you?")
        assert req.username == "john_doe"
        assert req.message == "Hello, how are you?"

    def test_backend_request_empty_username(self):
        """Test that an empty username raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username="", message="Hello")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "username" in str(errors[0]["loc"])
        assert "non-empty, non-whitespace string" in errors[0]["msg"]

    def test_backend_request_whitespace_username(self):
        """Test that a whitespace-only username raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username="   ", message="Hello")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "username" in str(errors[0]["loc"])
        assert "non-empty, non-whitespace string" in errors[0]["msg"]

    def test_backend_request_empty_message(self):
        """Test that an empty message raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username="john_doe", message="")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "message" in str(errors[0]["loc"])

    def test_backend_request_whitespace_only_message(self):
        """Test that a whitespace-only message raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username="john_doe", message="   ")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "message" in str(errors[0]["loc"])

    def test_backend_request_message_not_string(self):
        """Test that a non-string message raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username="john_doe", message=123)

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "message" in str(errors[0]["loc"])

    def test_backend_request_username_not_string(self):
        """Test that a non-string username raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username=123, message="Hello")

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "username" in str(errors[0]["loc"])

    def test_backend_request_message_too_long(self):
        """Test that a message exceeding max_message_chars raises ValidationError."""
        from backend.config import settings

        oversized = "a" * (settings.max_message_chars + 1)
        with pytest.raises(ValidationError) as exc_info:
            BackendRequest(username="john_doe", message=oversized)

        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert "message" in str(errors[0]["loc"])
        assert str(settings.max_message_chars) in errors[0]["msg"]

    def test_backend_request_message_at_max_length(self):
        """Test that a message of exactly max_message_chars is valid."""
        from backend.config import settings

        exact = "a" * settings.max_message_chars
        req = BackendRequest(username="john_doe", message=exact)
        assert len(req.message) == settings.max_message_chars


class TestBackendResponse:
    """Tests for BackendResponse schema."""

    def test_backend_response_defaults(self):
        """Test that BackendResponse has correct default values."""
        resp = BackendResponse(message="Test message")
        assert resp.message == "Test message"
        assert resp.citations == []
        assert resp.tool_results == []
        assert resp.error is False
        assert resp.error_message is None

    def test_backend_response_with_citations(self):
        """Test BackendResponse with citations."""
        resp = BackendResponse(
            message="Test", citations=["source1.pdf", "source2.pdf"]
        )
        assert resp.citations == ["source1.pdf", "source2.pdf"]

    def test_backend_response_with_tool_results(self):
        """Test BackendResponse with tool results."""
        tool_result = ToolResult(tool_name="check_conflict", summary="No conflicts")
        resp = BackendResponse(message="Test", tool_results=[tool_result])
        assert len(resp.tool_results) == 1
        assert resp.tool_results[0].tool_name == "check_conflict"
        assert resp.tool_results[0].summary == "No conflicts"

    def test_backend_response_with_error(self):
        """Test BackendResponse with error information."""
        resp = BackendResponse(
            message="Error occurred",
            error=True,
            error_message="Invalid input provided",
        )
        assert resp.error is True
        assert resp.error_message == "Invalid input provided"


class TestUserProfile:
    """Tests for UserProfile schema."""

    def test_user_profile_defaults(self):
        """Test that UserProfile has correct default values."""
        profile = UserProfile(username="test_user")
        assert profile.username == "test_user"
        assert profile.skin_type is None
        assert profile.skin_concerns == []
        assert profile.has_shaving_routine is None
        assert profile.medical_flags == []
        assert profile.onboarding_complete is False

    def test_user_profile_with_all_fields(self):
        """Test UserProfile with all fields populated."""
        profile = UserProfile(
            username="test_user",
            skin_type="oily",
            skin_concerns=["acne", "sensitivity"],
            has_shaving_routine=True,
            medical_flags=["eczema"],
            onboarding_complete=True,
        )
        assert profile.username == "test_user"
        assert profile.skin_type == "oily"
        assert profile.skin_concerns == ["acne", "sensitivity"]
        assert profile.has_shaving_routine is True
        assert profile.medical_flags == ["eczema"]
        assert profile.onboarding_complete is True


class TestRoutineStepSchema:
    """Tests for RoutineStepSchema."""

    def test_routine_step_valid(self):
        """Test that a valid RoutineStepSchema constructs."""
        step = RoutineStepSchema(
            position=1, ingredient="Cleanser", product_name="CeraVe Foaming Cleanser"
        )
        assert step.position == 1
        assert step.ingredient == "Cleanser"
        assert step.product_name == "CeraVe Foaming Cleanser"

    def test_routine_step_without_product_name(self):
        """Test that RoutineStepSchema works without product_name."""
        step = RoutineStepSchema(position=2, ingredient="Moisturizer")
        assert step.position == 2
        assert step.ingredient == "Moisturizer"
        assert step.product_name is None


class TestRoutineSchema:
    """Tests for RoutineSchema."""

    def test_routine_schema_empty_steps(self):
        """Test that RoutineSchema can be created with empty steps."""
        routine = RoutineSchema(name="Morning")
        assert routine.name == "Morning"
        assert routine.steps == []

    def test_routine_schema_with_steps(self):
        """Test RoutineSchema with steps."""
        step1 = RoutineStepSchema(position=1, ingredient="Cleanser")
        step2 = RoutineStepSchema(position=2, ingredient="Moisturizer")
        routine = RoutineSchema(name="Evening", steps=[step1, step2])
        assert routine.name == "Evening"
        assert len(routine.steps) == 2
        assert routine.steps[0].ingredient == "Cleanser"
        assert routine.steps[1].ingredient == "Moisturizer"


class TestIntroductionWeek:
    """Tests for IntroductionWeek schema."""

    def test_introduction_week_valid(self):
        """Test that a valid IntroductionWeek constructs."""
        week = IntroductionWeek(
            week=1,
            active="niacinamide",
            frequency="2x per week",
            notes="Start low concentration",
        )
        assert week.week == 1
        assert week.active == "niacinamide"
        assert week.frequency == "2x per week"
        assert week.notes == "Start low concentration"


class TestIntroductionPlanSchema:
    """Tests for IntroductionPlanSchema."""

    def test_introduction_plan_valid(self):
        """Test that a valid IntroductionPlanSchema constructs."""
        week1 = IntroductionWeek(
            week=1, active="niacinamide", frequency="2x per week", notes="Introduction"
        )
        week2 = IntroductionWeek(
            week=2, active="niacinamide", frequency="3x per week", notes="Increase"
        )
        plan = IntroductionPlanSchema(
            actives=["niacinamide", "retinol"],
            weeks=[week1, week2],
            status="active",
        )
        assert plan.actives == ["niacinamide", "retinol"]
        assert len(plan.weeks) == 2
        assert plan.status == "active"


class TestToolResult:
    """Tests for ToolResult schema."""

    def test_tool_result_valid(self):
        """Test that a valid ToolResult constructs."""
        result = ToolResult(
            tool_name="check_conflict", summary="No conflicts found"
        )
        assert result.tool_name == "check_conflict"
        assert result.summary == "No conflicts found"


class TestSchemaJsonSerialization:
    """Tests for JSON serialization of schemas."""

    def test_backend_request_model_dump(self):
        """Test that BackendRequest can be serialized to dict."""
        req = BackendRequest(username="test", message="hello")
        data = req.model_dump()
        assert data["username"] == "test"
        assert data["message"] == "hello"

    def test_backend_response_model_dump(self):
        """Test that BackendResponse can be serialized to dict."""
        tool_result = ToolResult(tool_name="test", summary="ok")
        resp = BackendResponse(
            message="Success",
            citations=["doc.pdf"],
            tool_results=[tool_result],
        )
        data = resp.model_dump()
        assert data["message"] == "Success"
        assert data["citations"] == ["doc.pdf"]
        assert len(data["tool_results"]) == 1
        assert data["error"] is False

    def test_backend_request_model_validate_json(self):
        """Test that BackendRequest can be created from JSON."""
        json_data = '{"username": "test_user", "message": "hello world"}'
        req = BackendRequest.model_validate_json(json_data)
        assert req.username == "test_user"
        assert req.message == "hello world"
