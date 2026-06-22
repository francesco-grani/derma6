"""Unit tests for backend.pricing."""

import pytest

from backend.pricing import calculate_cost, _PRICES, _DEFAULT


class TestCalculateCost:
    def test_known_model_gpt4o_mini(self):
        cost = calculate_cost("openai/gpt-4o-mini", 1_000, 500)
        prompt_rate, completion_rate = _PRICES["openai/gpt-4o-mini"]
        expected = 1_000 * prompt_rate + 500 * completion_rate
        assert abs(cost - expected) < 1e-12

    def test_known_model_claude_sonnet(self):
        cost = calculate_cost("anthropic/claude-sonnet-4-6", 2_000, 800)
        p, c = _PRICES["anthropic/claude-sonnet-4-6"]
        assert abs(cost - (2_000 * p + 800 * c)) < 1e-12

    def test_unknown_model_uses_default(self):
        cost = calculate_cost("unknown/model-xyz", 1_000, 1_000)
        p, c = _DEFAULT
        assert abs(cost - (1_000 * p + 1_000 * c)) < 1e-12

    def test_zero_tokens_returns_zero(self):
        assert calculate_cost("openai/gpt-4o-mini", 0, 0) == 0.0

    def test_cost_is_positive(self):
        for model in _PRICES:
            assert calculate_cost(model, 100, 100) > 0

    def test_completion_tokens_cost_more_than_prompt(self):
        """For all models, completion rate >= prompt rate."""
        for model, (p_rate, c_rate) in _PRICES.items():
            assert c_rate >= p_rate, f"{model}: completion rate should be >= prompt rate"

    def test_all_known_models_present(self):
        expected_models = [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-6",
            "google/gemini-2.0-flash",
        ]
        for m in expected_models:
            assert m in _PRICES

    def test_large_token_count(self):
        cost = calculate_cost("openai/gpt-4o-mini", 1_000_000, 500_000)
        assert cost > 0
        assert cost < 10.0  # sanity: gpt-4o-mini is cheap
