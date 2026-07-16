"""Unit tests for backend.config.Settings — Supabase config fields (Bundle 2).

_env_file=None is passed explicitly everywhere so these tests never pick up a
developer's real local .env file; only the constructor kwargs below matter.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.config import Settings

_REQUIRED = {
    "OPENROUTER_API_KEY": "test-key",
    "DATABASE_URL": "sqlite:///test.db",
}


def _make_settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **_REQUIRED, **overrides)  # type: ignore[call-arg, arg-type]


class TestSupabaseJwksUrlDerivedDefault:
    def test_derives_jwks_url_from_supabase_url_when_unset(self) -> None:
        settings = _make_settings(SUPABASE_URL="https://myproj.supabase.co")

        assert (
            settings.supabase_jwks_url
            == "https://myproj.supabase.co/auth/v1/.well-known/jwks.json"
        )

    def test_respects_an_explicitly_configured_jwks_url(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            SUPABASE_JWKS_URL="https://custom.example.com/jwks.json",
        )

        assert settings.supabase_jwks_url == "https://custom.example.com/jwks.json"


class TestSupabaseJwtSecretFallback:
    def test_defaults_to_empty_string_when_unset(self) -> None:
        settings = _make_settings(SUPABASE_URL="https://myproj.supabase.co")

        assert settings.supabase_jwt_secret == ""

    def test_uses_explicit_value_when_set(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            SUPABASE_JWT_SECRET="shared-secret-value",
        )

        assert settings.supabase_jwt_secret == "shared-secret-value"


class TestSupabaseUrlRequired:
    def test_missing_supabase_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # conftest.py sets a process-wide SUPABASE_URL default for the rest of the
        # suite; remove it here so this test genuinely exercises the "unset" case.
        monkeypatch.delenv("SUPABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None, **_REQUIRED)  # type: ignore[call-arg, arg-type]


class TestMemorySettingsDefaults:
    def test_defaults_load_correctly(self) -> None:
        settings = _make_settings(SUPABASE_URL="https://myproj.supabase.co")

        assert settings.memory_extraction_model is None
        assert settings.memory_similarity_threshold == 0.92
        assert settings.memory_retrieval_top_k == 5

    def test_explicit_values_are_respected(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            MEMORY_EXTRACTION_MODEL="anthropic/claude-haiku-4.5",
            MEMORY_SIMILARITY_THRESHOLD="0.85",
            MEMORY_RETRIEVAL_TOP_K="3",
        )

        assert settings.memory_extraction_model == "anthropic/claude-haiku-4.5"
        assert settings.memory_similarity_threshold == 0.85
        assert settings.memory_retrieval_top_k == 3


class TestProductFinderSettingsDefaults:
    def test_defaults_load_correctly(self) -> None:
        settings = _make_settings(SUPABASE_URL="https://myproj.supabase.co")

        assert settings.product_cache_db_path == "./data/product_cache.db"
        assert settings.product_cache_ttl_seconds == 600
        assert settings.product_lookup_timeout_seconds == 8
        assert settings.product_max_listings_per_source == 8


class TestSourceDiscoverySettingsDefaults:
    def test_defaults_load_correctly(self) -> None:
        settings = _make_settings(SUPABASE_URL="https://myproj.supabase.co")

        assert settings.source_discovery_db_path == "./data/source_discovery.db"
        assert settings.source_discovery_ttl_seconds == 604800
        assert settings.source_discovery_timeout_seconds == 20
        assert settings.source_discovery_model is None

    def test_explicit_values_are_respected(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            SOURCE_DISCOVERY_DB_PATH="./custom/source_discovery.db",
            SOURCE_DISCOVERY_TTL_SECONDS="1209600",
            SOURCE_DISCOVERY_TIMEOUT_SECONDS="30",
            SOURCE_DISCOVERY_MODEL="anthropic/claude-haiku-4.5",
        )

        assert settings.source_discovery_db_path == "./custom/source_discovery.db"
        assert settings.source_discovery_ttl_seconds == 1209600
        assert settings.source_discovery_timeout_seconds == 30
        assert settings.source_discovery_model == "anthropic/claude-haiku-4.5"


class TestEffectiveSourceDiscoveryModel:
    def test_falls_back_to_llm_model_when_unset(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            LLM_MODEL="anthropic/claude-haiku-4.5",
        )

        assert settings.source_discovery_model is None
        assert settings.effective_source_discovery_model == "anthropic/claude-haiku-4.5"

    def test_uses_explicit_override_when_set(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            LLM_MODEL="anthropic/claude-haiku-4.5",
            SOURCE_DISCOVERY_MODEL="openai/gpt-4o-mini",
        )

        assert settings.effective_source_discovery_model == "openai/gpt-4o-mini"


class TestEffectiveMemoryExtractionModel:
    def test_falls_back_to_llm_model_when_unset(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            LLM_MODEL="anthropic/claude-haiku-4.5",
        )

        assert settings.memory_extraction_model is None
        assert settings.effective_memory_extraction_model == "anthropic/claude-haiku-4.5"

    def test_uses_explicit_override_when_set(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            LLM_MODEL="anthropic/claude-haiku-4.5",
            MEMORY_EXTRACTION_MODEL="openai/gpt-4o-mini",
        )

        assert settings.effective_memory_extraction_model == "openai/gpt-4o-mini"


class TestRelevanceClassificationSettingsDefaults:
    def test_defaults_load_correctly(self) -> None:
        settings = _make_settings(SUPABASE_URL="https://myproj.supabase.co")

        assert settings.relevance_classification_timeout_seconds == 6.0
        assert settings.relevance_classification_model is None

    def test_explicit_values_are_respected(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            RELEVANCE_CLASSIFICATION_TIMEOUT_SECONDS="10.5",
            RELEVANCE_CLASSIFICATION_MODEL="anthropic/claude-haiku-4.5",
        )

        assert settings.relevance_classification_timeout_seconds == 10.5
        assert settings.relevance_classification_model == "anthropic/claude-haiku-4.5"


class TestEffectiveRelevanceClassificationModel:
    def test_falls_back_to_llm_model_when_unset(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            LLM_MODEL="anthropic/claude-haiku-4.5",
        )

        assert settings.relevance_classification_model is None
        assert settings.effective_relevance_classification_model == "anthropic/claude-haiku-4.5"

    def test_uses_explicit_override_when_set(self) -> None:
        settings = _make_settings(
            SUPABASE_URL="https://myproj.supabase.co",
            LLM_MODEL="anthropic/claude-haiku-4.5",
            RELEVANCE_CLASSIFICATION_MODEL="openai/gpt-4o-mini",
        )

        assert settings.effective_relevance_classification_model == "openai/gpt-4o-mini"


class TestPoolerModeDetection:
    """Prepared statements must be off against Supavisor's transaction pooler
    (port 6543) and on everywhere else — see Settings.db_uses_transaction_pooler.
    """

    _POOLER = "aws-0-eu-west-1.pooler.supabase.com"

    def _with_db_url(self, url: str) -> Settings:
        # Not _make_settings(): it always supplies DATABASE_URL itself.
        return Settings(  # type: ignore[call-arg]
            _env_file=None,
            OPENROUTER_API_KEY="test-key",
            DATABASE_URL=url,
        )

    def test_detects_transaction_pooler_on_6543(self) -> None:
        settings = self._with_db_url(f"postgresql://u:p@{self._POOLER}:6543/postgres")

        assert settings.db_uses_transaction_pooler is True
        assert settings.db_prepare_threshold is None

    def test_treats_session_pooler_on_5432_as_prepared_statement_capable(self) -> None:
        settings = self._with_db_url(f"postgresql://u:p@{self._POOLER}:5432/postgres")

        assert settings.db_uses_transaction_pooler is False
        assert settings.db_prepare_threshold == 0

    def test_survives_a_password_containing_the_pooler_port(self) -> None:
        """Guards against a naive `"6543" in url` check: the port is structural,
        not a string that may legitimately appear elsewhere in the URL."""
        settings = self._with_db_url(f"postgresql://u:pw6543@{self._POOLER}:5432/postgres")

        assert settings.db_uses_transaction_pooler is False

    def test_sqlite_is_not_a_transaction_pooler(self) -> None:
        settings = self._with_db_url("sqlite:////tmp/x.db")

        assert settings.db_uses_transaction_pooler is False
