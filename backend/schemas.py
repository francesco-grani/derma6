"""Pydantic v2 application-layer schemas for request/response validation.

All schemas are in Pydantic v2 format and use proper field validators
for custom validation logic.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from backend.config import settings

# ── Auth ──────────────────────────────────────────────────────────────────────


class CompleteSignupRequest(BaseModel):
    """Provisions the local user row after Supabase has created the auth identity
    (Req 4.4). `supabase_user_id` is the provider-issued UUID that becomes the
    local `users.id` primary key; `email` and `username` were submitted by the
    user during signup and are never derived automatically (Req 4.6)."""

    supabase_user_id: str
    email: str
    username: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 2:
            raise ValueError("Username must be at least 2 characters.")
        if len(v) > 50:
            raise ValueError("Username must be 50 characters or fewer.")
        return v


# ── Chat ─────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatHistoryMessage(BaseModel):
    role: str
    content: str


# ── HITL ─────────────────────────────────────────────────────────────────────


class ResumeRequest(BaseModel):
    session_id: str
    run_id: str
    choice: str  # "confirm" | "rename" | "cancel"
    note: str = ""


# ── Profile / Routines ────────────────────────────────────────────────────────


class ProfilePatch(BaseModel):
    skin_type: Optional[str] = None
    beard_style: Optional[str] = None
    location: Optional[str] = None
    skin_concerns: Optional[list[str]] = None


class RenameRequest(BaseModel):
    new_name: str


# ── Skin Analysis ─────────────────────────────────────────────────────────────


class Alternative(BaseModel):
    condition: str
    # Optional (Req 1.6): not every alternative condition the vision model
    # considers has a computed percentage. Explicitly nullable rather than
    # silently omitted so the strict schema represents optionality (see
    # backend.llm.structured.to_strict_json_schema). Additive/backward-
    # compatible widening (Req 1.5): existing consumers reading
    # alt.probability as a string still work when it's present.
    probability: str | None = None


class SkinAnalysisResult(BaseModel):
    condition: str
    confidence: float
    alternatives: list[Alternative]
    reasoning: str
    disclaimer: str


class SkinAnalysisRecord(BaseModel):
    id: int
    condition: str
    confidence: float
    alternatives: list[Alternative]
    reasoning: str
    disclaimer: str
    image_b64: Optional[str]
    thumbnail_b64: Optional[str]
    created_at: datetime


class SaveConditionRequest(BaseModel):
    condition: str


# ── Cross-session memory (Bundle 3) ─────────────────────────────────────────────


class MemoryFactSchema(BaseModel):
    """A single durably-stored freeform fact extracted from a past conversation."""

    id: int
    fact_text: str
    # Nullable: the FK is ON DELETE SET NULL (backend/db/models.py::UserMemoryFact) —
    # a fact outlives the session it was extracted from if that session is deleted.
    source_session_id: str | None = None
    created_at: datetime


class MemoryExtractionResult(BaseModel):
    """LLM output shape for `structured_completion()`-driven fact extraction
    (backend/agent/memory_extraction.py). Empty `facts` is valid and expected
    (Req 9.4) — most turns contain nothing memory-worthy."""

    facts: list[str] = []


# ── Admin ─────────────────────────────────────────────────────────────────────


class UserSummary(BaseModel):
    id: str
    username: str
    skin_type: Optional[str]
    skin_concerns: Optional[str]
    has_shaving_routine: Optional[bool]
    medical_flags: Optional[str]
    onboarding_complete: bool
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float

    model_config = {"from_attributes": True}


# ── Core user/session models ──────────────────────────────────────────────────


class UserProfile(BaseModel):
    """User profile information from onboarding."""

    user_id: str  # the Supabase UUID / local users.id primary key
    username: str
    skin_type: str | None = None
    skin_concerns: list[str] = []
    has_shaving_routine: bool | None = None
    beard_style: str | None = None  # "shave" | "trim" | "grow"
    location: str | None = None
    medical_flags: list[str] = []
    onboarding_complete: bool = False
    is_admin: bool = False  # sourced from users.is_admin only, never from the JWT (Req 8.2)


class RoutineStepInput(BaseModel):
    """Typed tool-argument shape for a single routine step (Req 2.1, 2.2).

    Used as the element type of save_routine_tool's `steps: list[RoutineStepInput]`
    parameter (backend/agent/graph.py) — replaces the prior comma-separated
    `steps: str` + JSON-encoded `suggestions: str` tool arguments. A step missing
    `ingredient` is rejected by LangGraph's ToolNode (Pydantic validation) before
    the tool closure body runs (Req 2.4).
    """

    ingredient: str
    suggested_product: str | None = None
    budget_product: str | None = None


class RoutineStepSchema(BaseModel):
    """A single step in a routine (ingredient application)."""

    position: int
    ingredient: str
    product_name: str | None = None
    budget_product: str | None = None


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
        """Validate that message is a non-empty string within the allowed length.

        Args:
            v: The message to validate

        Returns:
            The validated message

        Raises:
            ValueError: If message is empty, not a string, or exceeds max length
        """
        if not isinstance(v, str) or len(v.strip()) == 0:
            raise ValueError("message must be a non-empty string")
        if len(v) > settings.max_message_chars:
            raise ValueError(
                f"message must not exceed {settings.max_message_chars} characters "
                f"(got {len(v)})"
            )
        return v


class ChatSessionInfo(BaseModel):
    """Summary of a chat session for the session list."""

    session_id: str
    title: str | None = None
    created_at: str
    updated_at: str


class BackendResponse(BaseModel):
    """API response schema for the RAG chatbot backend."""

    message: str
    citations: list[str] = []
    tool_results: list[ToolResult] = []
    error: bool = False
    error_message: str | None = None
