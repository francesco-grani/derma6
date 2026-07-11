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
