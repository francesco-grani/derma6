"""Configuration management for Derma6.

Uses pydantic-settings for environment variable management with validation.
Fails fast at import time if required variables are missing.
"""

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
    )

    # LLM
    openrouter_api_key: str = Field(
        ...,
        alias="OPENROUTER_API_KEY",
        description="OpenRouter API key (required)",
    )
    llm_model: str = Field(
        default="openai/gpt-4o-mini",
        alias="LLM_MODEL",
    )
    vision_model: str = Field(
        default="openai/gpt-4o",
        alias="VISION_MODEL",
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )

    # Embeddings — served via OpenRouter API, not loaded locally
    embedding_model: str = Field(
        default="qwen/qwen3-embedding-8b",
        alias="EMBEDDING_MODEL",
    )

    # Storage
    database_url: str = Field(
        ...,
        alias="DATABASE_URL",
        description="Postgres connection string (raw, as provided by Supabase) or a sqlite:/// URL for tests",
    )
    chroma_persist_dir: str = Field(
        default="./data/chroma",
        alias="CHROMA_PERSIST_DIR",
    )
    conflict_table_path: str = Field(
        default="./knowledge_base/conflict_table.json",
        alias="CONFLICT_TABLE_PATH",
    )

    # Retrieval
    retrieval_top_k: int = Field(default=4, alias="RETRIEVAL_TOP_K")
    retrieval_min_score: float = Field(default=0.3, alias="RETRIEVAL_MIN_SCORE")

    # Rate limiting
    rate_limit_requests: int = Field(default=10, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")

    # Auth
    secret_key: str = Field(
        default="change-me-in-production-use-a-long-random-string",
        alias="SECRET_KEY",
    )
    access_token_expire_minutes: int = Field(
        default=60 * 24,  # 24 hours
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )

    # Supabase Auth (Bundle 2 — JWT verification against the Supabase project)
    supabase_url: str = Field(
        ...,
        alias="SUPABASE_URL",
        description="Supabase project URL (e.g. https://<project-ref>.supabase.co)",
    )
    supabase_jwks_url: str = Field(
        default="",
        alias="SUPABASE_JWKS_URL",
        description=(
            "Supabase JWKS endpoint used to verify JWT signatures. "
            "Derived from supabase_url (f'{supabase_url}/auth/v1/.well-known/jwks.json') "
            "when not explicitly set."
        ),
    )
    supabase_jwt_secret: str = Field(
        default="",
        alias="SUPABASE_JWT_SECRET",
        description="Shared-secret HS256 fallback for JWT verification, used only if the "
        "project is not configured for JWKS-based (RS256/ES256) verification.",
    )

    @field_validator("supabase_jwks_url", mode="after")
    @classmethod
    def _derive_jwks_url(cls, v: str, info: ValidationInfo) -> str:
        """Derive the JWKS URL from supabase_url when not explicitly configured."""
        if v:
            return v
        supabase_url = info.data.get("supabase_url", "")
        return f"{supabase_url}/auth/v1/.well-known/jwks.json"

    # Cross-session memory (Bundle 3 — extraction/retrieval of freeform facts)
    memory_extraction_model: str | None = Field(
        default=None,
        alias="MEMORY_EXTRACTION_MODEL",
        description="Model used for memory-fact extraction. Falls back to llm_model "
        "when unset (see effective_memory_extraction_model).",
    )
    memory_similarity_threshold: float = Field(
        default=0.92, alias="MEMORY_SIMILARITY_THRESHOLD"
    )
    memory_retrieval_top_k: int = Field(default=5, alias="MEMORY_RETRIEVAL_TOP_K")

    @property
    def effective_memory_extraction_model(self) -> str:
        """The model actually used for memory-fact extraction: an explicit
        override if configured, otherwise the same model driving the live chat
        agent (llm_model)."""
        return self.memory_extraction_model or self.llm_model

    # Input validation
    max_message_chars: int = Field(default=2000, alias="MAX_MESSAGE_CHARS")

    # Agentic RAG pipeline
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        alias="RERANKER_MODEL",
    )
    rerank_top_k: int = Field(default=5, alias="RERANK_TOP_K")
    # Cross-encoder relevance floor (ms-marco MiniLM logit scale, ~-11..+11).
    # Candidates whose raw reranker score falls below this are dropped before
    # grading, pruning egregiously off-topic chunks (e.g. a Ceramides passage
    # retrieved for a sunscreen query). The single best candidate is always kept
    # so retrieval never returns empty. Set very low to effectively disable.
    rerank_min_score: float = Field(default=-6.0, alias="RERANK_MIN_SCORE")
    # A reranked doc need only clear this fraction of "relevant" CRAG grades to
    # answer from the local KB. Kept low because the grader is lenient and the
    # generate node additionally drops the individually non-relevant chunks —
    # one solidly relevant chunk is enough to prefer the KB over a fallback.
    crag_relevance_threshold: float = Field(default=0.25, alias="CRAG_RELEVANCE_THRESHOLD")
    # Genuine KB gaps fall back to a live web search (Tavily if TAVILY_API_KEY is
    # set, else DuckDuckGo) rather than answering from the model alone; degrades
    # to "llm-only" automatically if the search yields nothing / errors.
    crag_fallback_strategy: str = Field(default="web-search", alias="CRAG_FALLBACK_STRATEGY")
    decompose_timeout_seconds: int = Field(default=10, alias="DECOMPOSE_TIMEOUT_SECONDS")
    hyde_timeout_seconds: int = Field(default=10, alias="HYDE_TIMEOUT_SECONDS")
    crag_grade_timeout_seconds: int = Field(default=10, alias="CRAG_GRADE_TIMEOUT_SECONDS")
    rerank_timeout_seconds: int = Field(default=15, alias="RERANK_TIMEOUT_SECONDS")
    rrf_k: int = Field(default=60, alias="RRF_K")
    # Added to a candidate's cross-encoder score per canonical active it shares
    # with the query, applied just before top-k selection so the actives signal
    # survives reranking. On the ms-marco MiniLM logit scale (~-11..+11); set to
    # 0.0 to disable actives-aware boosting.
    actives_rerank_boost: float = Field(default=1.5, alias="ACTIVES_RERANK_BOOST")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    rag_debug_mode: bool = Field(default=False, alias="RAG_DEBUG_MODE")

    # Product finder
    product_cache_db_path: str = Field(
        default="./data/product_cache.db",
        alias="PRODUCT_CACHE_DB_PATH",
    )
    product_cache_ttl_seconds: int = Field(default=600, alias="PRODUCT_CACHE_TTL_SECONDS")
    product_lookup_timeout_seconds: int = Field(
        default=8, alias="PRODUCT_LOOKUP_TIMEOUT_SECONDS"
    )
    product_max_listings_per_source: int = Field(
        default=8, alias="PRODUCT_MAX_LISTINGS_PER_SOURCE"
    )
    product_thumbnail_fetch_timeout_seconds: float = Field(
        default=4.0, alias="PRODUCT_THUMBNAIL_FETCH_TIMEOUT_SECONDS"
    )

    # Product source discovery
    source_discovery_db_path: str = Field(
        default="./data/source_discovery.db",
        alias="SOURCE_DISCOVERY_DB_PATH",
    )
    source_discovery_ttl_seconds: int = Field(
        default=604800, alias="SOURCE_DISCOVERY_TTL_SECONDS"  # 7 days
    )
    source_discovery_timeout_seconds: int = Field(
        default=20, alias="SOURCE_DISCOVERY_TIMEOUT_SECONDS"
    )
    source_discovery_model: str | None = Field(
        default=None,
        alias="SOURCE_DISCOVERY_MODEL",
        description="Model used for source-discovery LLM calls. Falls back to llm_model "
        "when unset (see effective_source_discovery_model).",
    )

    @property
    def effective_source_discovery_model(self) -> str:
        """The model actually used for source-discovery LLM calls: an explicit
        override if configured, otherwise the same model driving the live chat
        agent (llm_model)."""
        return self.source_discovery_model or self.llm_model

    # Relevance classification
    relevance_classification_timeout_seconds: float = Field(
        default=6.0, alias="RELEVANCE_CLASSIFICATION_TIMEOUT_SECONDS"
    )
    relevance_classification_model: str | None = Field(
        default=None,
        alias="RELEVANCE_CLASSIFICATION_MODEL",
        description="Model used for relevance-classification LLM calls. Falls back to "
        "llm_model when unset (see effective_relevance_classification_model).",
    )

    @property
    def effective_relevance_classification_model(self) -> str:
        """The model actually used for relevance-classification LLM calls: an
        explicit override if configured, otherwise the same model driving the
        live chat agent (llm_model)."""
        return self.relevance_classification_model or self.llm_model

    # CORS
    allowed_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        alias="ALLOWED_ORIGINS",
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v  # type: ignore[return-value]

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="./logs/app.log", alias="LOG_FILE")

    # Error monitoring (optional)
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    sentry_traces_sample_rate: float = Field(default=0.1, alias="SENTRY_TRACES_SAMPLE_RATE")

    # LangSmith tracing (optional — enabled when LANGSMITH_API_KEY is set)
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_tracing: str = Field(default="false", alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(
        default="derma6", alias="LANGSMITH_PROJECT"
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com", alias="LANGSMITH_ENDPOINT"
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        """SQLAlchemy dialect-qualified URL derived from database_url.

        Supabase provides a raw postgresql:// string; SQLAlchemy needs the
        driver qualified explicitly (psycopg v3). sqlite:// URLs (tests) pass
        through unchanged.
        """
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        return self.database_url


try:
    settings = Settings()
except ValidationError as e:
    lines = "\n".join(
        f"  • {'.'.join(str(l) for l in err['loc'])}: {err['msg']}"
        for err in e.errors()
    )
    raise RuntimeError(
        f"Missing or invalid environment variables:\n{lines}\n\n"
        "Copy .env.example to .env and fill in OPENROUTER_API_KEY."
    ) from e
