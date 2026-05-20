"""Pydantic v2 application-layer schemas for request/response validation.

All schemas are in Pydantic v2 format and use proper field validators
for custom validation logic.
"""

from pydantic import BaseModel, field_validator


class UserProfile(BaseModel):
    """User profile information from onboarding."""

    username: str
    skin_type: str | None = None
    skin_concerns: list[str] = []
    has_shaving_routine: bool | None = None
    medical_flags: list[str] = []
    onboarding_complete: bool = False


class RoutineStepSchema(BaseModel):
    """A single step in a routine (ingredient application)."""

    position: int
    ingredient: str
    product_name: str | None = None


class RoutineSchema(BaseModel):
    """A complete routine (morning, evening, etc.)."""

    name: str
    steps: list[RoutineStepSchema] = []


class IntroductionWeek(BaseModel):
    """Weekly introduction schedule for an active ingredient."""

    week: int
    active: str
    frequency: str  # e.g. "2x per week"
    notes: str


class IntroductionPlanSchema(BaseModel):
    """Introduction plan for gradually introducing active ingredients."""

    actives: list[str]
    weeks: list[IntroductionWeek]
    status: str  # "active" | "completed" | "paused"


class ToolResult(BaseModel):
    """Result from a tool invocation."""

    tool_name: str
    summary: str


class BackendRequest(BaseModel):
    """API request schema for the RAG chatbot backend."""

    username: str
    message: str

    @field_validator("username", mode="before")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Validate that username is non-empty and non-whitespace-only.

        Args:
            v: The username to validate

        Returns:
            The validated username

        Raises:
            ValueError: If username is empty or whitespace-only
        """
        if not isinstance(v, str) or not v.strip():
            raise ValueError("username must be a non-empty, non-whitespace string")
        return v

    @field_validator("message", mode="before")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Validate that message is a non-empty string.

        Args:
            v: The message to validate

        Returns:
            The validated message

        Raises:
            ValueError: If message is empty or not a string
        """
        if not isinstance(v, str) or len(v.strip()) == 0:
            raise ValueError("message must be a non-empty string")
        return v


class BackendResponse(BaseModel):
    """API response schema for the RAG chatbot backend."""

    message: str
    citations: list[str] = []
    tool_results: list[ToolResult] = []
    error: bool = False
    error_message: str | None = None
