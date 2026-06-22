"""Unit tests for backend.schemas Pydantic models."""

import pytest
from pydantic import ValidationError

from backend.schemas import (
    BackendRequest,
    BackendResponse,
    ChatSessionInfo,
    IntroductionPlanSchema,
    IntroductionWeek,
    RoutineSchema,
    RoutineStepSchema,
    ToolResult,
    UserProfile,
)


class TestBackendRequest:
    def test_valid_request(self):
        req = BackendRequest(username="alice", message="What moisturiser should I use?")
        assert req.username == "alice"
        assert req.message == "What moisturiser should I use?"

    def test_empty_username_raises(self):
        with pytest.raises(ValidationError, match="username"):
            BackendRequest(username="", message="hello")

    def test_whitespace_only_username_raises(self):
        with pytest.raises(ValidationError, match="username"):
            BackendRequest(username="   ", message="hello")

    def test_empty_message_raises(self):
        with pytest.raises(ValidationError, match="message"):
            BackendRequest(username="alice", message="")

    def test_whitespace_only_message_raises(self):
        with pytest.raises(ValidationError, match="message"):
            BackendRequest(username="alice", message="   ")

    def test_message_at_max_length_allowed(self, monkeypatch):
        from backend import schemas as s
        monkeypatch.setattr(s.settings, "max_message_chars", 10)
        req = BackendRequest(username="alice", message="1234567890")
        assert len(req.message) == 10

    def test_message_exceeds_max_length_raises(self, monkeypatch):
        from backend import schemas as s
        monkeypatch.setattr(s.settings, "max_message_chars", 5)
        with pytest.raises(ValidationError, match="must not exceed"):
            BackendRequest(username="alice", message="123456")

    def test_non_string_username_raises(self):
        with pytest.raises(ValidationError):
            BackendRequest(username=123, message="hello")


class TestUserProfile:
    def test_defaults(self):
        profile = UserProfile(username="bob")
        assert profile.skin_type is None
        assert profile.skin_concerns == []
        assert profile.has_shaving_routine is None
        assert profile.medical_flags == []
        assert profile.onboarding_complete is False

    def test_full_profile(self):
        profile = UserProfile(
            username="carol",
            skin_type="oily",
            skin_concerns=["acne", "dryness"],
            has_shaving_routine=True,
            medical_flags=["rosacea"],
            onboarding_complete=True,
        )
        assert profile.skin_type == "oily"
        assert "acne" in profile.skin_concerns
        assert profile.medical_flags == ["rosacea"]
        assert profile.onboarding_complete is True


class TestRoutineSchemas:
    def test_routine_step_schema(self):
        step = RoutineStepSchema(position=1, ingredient="retinol")
        assert step.position == 1
        assert step.product_name is None

    def test_routine_schema_empty_steps(self):
        routine = RoutineSchema(name="Morning")
        assert routine.steps == []

    def test_routine_schema_with_steps(self):
        steps = [
            RoutineStepSchema(position=1, ingredient="cleanser"),
            RoutineStepSchema(position=2, ingredient="spf", product_name="Altruist SPF50"),
        ]
        routine = RoutineSchema(name="Morning Routine", steps=steps)
        assert len(routine.steps) == 2
        assert routine.steps[1].product_name == "Altruist SPF50"


class TestIntroductionPlanSchema:
    def test_valid_plan(self):
        week = IntroductionWeek(week=1, active="retinol", frequency="2x/week", notes="Start slow")
        plan = IntroductionPlanSchema(actives=["retinol"], weeks=[week], status="active")
        assert plan.status == "active"
        assert plan.actives == ["retinol"]

    def test_introduction_week_fields(self):
        w = IntroductionWeek(week=3, active="niacinamide", frequency="3x/week", notes="Stable skin")
        assert w.week == 3
        assert w.frequency == "3x/week"


class TestBackendResponse:
    def test_defaults(self):
        resp = BackendResponse(message="Hello!")
        assert resp.citations == []
        assert resp.tool_results == []
        assert resp.error is False
        assert resp.error_message is None

    def test_error_response(self):
        resp = BackendResponse(message="", error=True, error_message="Rate limit exceeded")
        assert resp.error is True
        assert "Rate limit" in resp.error_message


class TestToolResult:
    def test_tool_result(self):
        tr = ToolResult(tool_name="kb_search", summary="Found 2 docs about retinol.")
        assert tr.tool_name == "kb_search"
        assert "retinol" in tr.summary
