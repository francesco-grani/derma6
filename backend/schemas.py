"""Pydantic v2 application-layer schemas for request/response validation.

All schemas are in Pydantic v2 format and use proper field validators
for custom validation logic.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.config import settings
from backend.security_patterns import JAILBREAK_PATTERN

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


# Kept in sync by hand with backend.agent.graph's skin_type_advisor_tool
# Literal (the original spec's Bundle 1 agent-tool layer) — security-
# remediation Req 23.3 extends the same enum to this request-validation
# layer so a value can never reach storage without going through the tool.
_SKIN_TYPES = Literal["oily", "dry", "combination", "sensitive", "dehydrated", "acneic"]


def _reject_jailbreak_phrases(v: str) -> str:
    """Shared field_validator body (Req 23.3): free-text profile fields that
    flow into the agent's system prompt (`location`, `skin_concerns`) are
    checked against the same jailbreak-pattern regex the chat/resume input
    guardrails use, rather than a second invented pattern set."""
    if JAILBREAK_PATTERN.search(v):
        raise ValueError("This value looks like it contains an instruction override attempt.")
    return v


class ProfilePatch(BaseModel):
    skin_type: Optional[_SKIN_TYPES] = None
    beard_style: Optional[str] = None
    location: Optional[str] = None
    skin_concerns: Optional[list[str]] = None

    @field_validator("location")
    @classmethod
    def location_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            _reject_jailbreak_phrases(v)
        return v

    @field_validator("skin_concerns")
    @classmethod
    def skin_concerns_valid(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            for item in v:
                _reject_jailbreak_phrases(item)
        return v


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


# ── Source Discovery ─────────────────────────────────────────────────────────


class DiscoveredSourcesLLM(BaseModel):
    """Raw structured-output shape requested from the discovery LLM call
    (Req 2, 3) — passed as `schema_model` to `structured_completion()`
    (backend/llm/structured.py), reusing that module's existing
    schema-enforcement/fallback machinery rather than a new LLM-calling
    pattern (Requirements Review Note point 2).

    Deliberately over-fetches candidates relative to the cap of 10
    (`_MAX_DOMAINS_PER_CATEGORY` in product_source_discovery.py, Req 2.2/3.4):
    syntactic validation and web-search verification (see
    product_source_discovery.py) will reject some fraction of raw LLM
    candidates, so asking for up to 15 leaves enough headroom to still net a
    healthy set of validated domains in the common case. The system prompt
    also asks the model to order each list by prominence/reliability, since
    only the first `_MAX_DOMAINS_PER_CATEGORY` survivors are kept.
    """

    location_recognized: bool
    # Confidence/validity signal (Req 1.4, 7): False means the model could
    # not confidently place `location` as a real, specific place it can
    # name retailers/marketplaces for — treated identically to a discovery
    # failure (Req 7.1), never as "fall back to some other location."
    retailer_domains: list[str] = Field(default_factory=list, max_length=15)
    vinted_locale_domain: str | None = None
    secondhand_marketplace_domains: list[str] = Field(default_factory=list, max_length=15)


class DiscoveredSources(BaseModel):
    """Validated, verified, count-capped discovery result (Req 2.2, 2.4,
    3.4) — what `get_or_discover_sources()` returns and what
    `SourceDiscoveryStore` persists (as `.model_dump_json()`, mirroring
    `ProductCacheStore`'s existing `ProductFindResponse` persistence
    pattern). Never contains an unvalidated/unverified candidate."""

    retailer_domains: tuple[str, ...] = ()
    vinted_domain: str | None = None  # e.g. "vinted.it" — full domain, Req 3.1/3.2
    secondhand_domains: tuple[str, ...] = ()  # non-Vinted marketplace domains, Req 3.3/3.4


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


# ── Product Finder ───────────────────────────────────────────────────────────


class ProductListing(BaseModel):
    """A single retail (new) or secondhand (used) product listing surfaced by
    `GET /api/products/find` (Req 9.7)."""

    type: Literal["new", "used"]
    title: str
    # Nullable: best-effort price extraction from a retail search snippet
    # (Req 11.5) doesn't always yield a clean price; the listing is still
    # included rather than discarded (Req 11.6).
    price: float | None = None
    currency: str | None = None
    source: str
    thumbnail_url: str | None = None
    listing_url: str


class ProductFindResponse(BaseModel):
    """Response shape for `GET /api/products/find` (Req 9.4, 9.7, 9.9)."""

    listings: list[ProductListing]
    # False only on retail-source failure/timeout, not on a legitimate
    # zero-result search (Req 9.9, 14.5).
    retail_ok: bool
    # False only if every attempted secondhand sub-source (Vinted, and
    # Kleinanzeigen when attempted) failed/timed out — True if either
    # succeeds (Req 9.9, 10.8), not False merely on a legitimate zero-result
    # search.
    secondhand_ok: bool


# ── Relevance Filtering ──────────────────────────────────────────────────────

_MAX_RELEVANCE_CANDIDATES = 12
# Headroom above settings.product_max_listings_per_source's default (8) — the
# category's diversified/capped candidate set is what's actually classified
# (Req 1.1), so this bound is a defensive cap on the LLM's response shape, not
# a value that needs to track the settings default exactly. Chosen as a plain
# Field(max_length=...) bound rather than a schema-level maxItems constraint
# specifically because of the lesson recorded in backend/llm/structured.py's
# _tighten(): to_strict_json_schema() strips maxItems/minItems from array
# fields before they reach the provider (several OpenRouter-routed providers
# reject that keyword outright), so this bound only ever does anything at
# Pydantic construction time in Python — which is exactly what's needed here,
# since the classification response is a small list of ints, not a
# provider-facing shape whose size the provider itself needs to enforce.


class ListingRelevanceLLM(BaseModel):
    """Structured output shape for one batched relevance-classification call
    over a category's candidate listings (Req 1.1, 1.2), passed as
    `schema_model` to `structured_completion()` — the same infrastructure
    `product_source_discovery.py` already uses (Req 1.1's explicit mandate).

    Candidates are supplied to the LLM as a numbered list in the user
    message (index, title, snippet, url); the model returns only the
    indices it judges genuine, rather than echoing every candidate back —
    this keeps the response small and its size naturally bounded by the
    category's already-capped candidate count, avoiding the maxItems pitfall
    documented above.
    """

    genuine_indices: list[int] = Field(default_factory=list, max_length=_MAX_RELEVANCE_CANDIDATES)


# ── Product Finder Streaming ─────────────────────────────────────────────────


class ProductFindStageEvent(BaseModel):
    """One SSE 'stage' frame (Req 7) — reuses this codebase's existing
    `data: {json}\\n\\n` + `type`-discriminator convention
    (`backend/agent/graph.py`'s `stream_agent_response`/`_sse`,
    Requirements Review Note point 2), as a Pydantic model rather than a
    plain dict (Requirements Review Note point 4)."""

    type: Literal["stage"] = "stage"
    stage: str  # stable machine identifier: "discovery" | "domain_check" |
    # "relevance_filter" | "thumbnail_enrichment" | "price_enrichment"
    message: str  # human-readable phrase for direct display (Req 7.5),
    # e.g. "Checking dm.de..." — untrusted (may embed an LLM/search-derived
    # domain name), rendered only as text (Non-Functional Consideration 3)


class ProductFindResultEvent(BaseModel):
    """The SSE stream's terminal frame (Req 6.4, 8.1) — carries the exact
    same ProductFindResponse payload the non-streaming endpoint returns,
    unchanged in shape/semantics."""

    type: Literal["result"] = "result"
    result: ProductFindResponse


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
