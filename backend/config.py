"""Configuration management for Derma6.

Uses pydantic-settings for environment variable management with validation.
Fails fast at import time if required variables are missing.
"""

from pydantic import Field, ValidationError, field_validator
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
    sqlite_db_path: str = Field(
        default="./data/skincare.db",
        alias="SQLITE_DB_PATH",
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

    # Input validation
    max_message_chars: int = Field(default=2000, alias="MAX_MESSAGE_CHARS")

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
    def sqlite_url(self) -> str:
        """SQLAlchemy-compatible connection string derived from sqlite_db_path."""
        return f"sqlite:///{self.sqlite_db_path}"


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
