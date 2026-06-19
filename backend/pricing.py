"""Token pricing for OpenRouter models.

Prices are in USD per single token (i.e. per-million rates divided by 1_000_000).
Update these when OpenRouter pricing changes.

Source: https://openrouter.ai/models
"""

# (prompt_usd_per_token, completion_usd_per_token)
_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini":              (0.150 / 1_000_000, 0.600 / 1_000_000),
    "openai/gpt-4o":                   (2.50  / 1_000_000, 10.00 / 1_000_000),
    "openai/gpt-4.1":                  (2.00  / 1_000_000, 8.00  / 1_000_000),
    "openai/gpt-4.1-mini":             (0.40  / 1_000_000, 1.60  / 1_000_000),
    "openai/o4-mini":                  (1.10  / 1_000_000, 4.40  / 1_000_000),
    "anthropic/claude-sonnet-4-6":     (3.00  / 1_000_000, 15.00 / 1_000_000),
    "anthropic/claude-opus-4-8":       (15.00 / 1_000_000, 75.00 / 1_000_000),
    "anthropic/claude-haiku-4-5":      (0.80  / 1_000_000, 4.00  / 1_000_000),
    "google/gemini-2.0-flash":         (0.075 / 1_000_000, 0.30  / 1_000_000),
    "google/gemini-2.5-flash-preview": (0.15  / 1_000_000, 0.60  / 1_000_000),
    "google/gemini-2.5-pro-preview":   (1.25  / 1_000_000, 10.00 / 1_000_000),
    "qwen/qwen3-235b-a22b":            (0.13  / 1_000_000, 0.60  / 1_000_000),
    "meta-llama/llama-4-maverick":     (0.18  / 1_000_000, 0.60  / 1_000_000),
}

# Fallback: rough average for unknown models
_DEFAULT = (1.00 / 1_000_000, 3.00 / 1_000_000)


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return the estimated USD cost for one LLM call."""
    prompt_rate, completion_rate = _PRICES.get(model, _DEFAULT)
    return prompt_tokens * prompt_rate + completion_tokens * completion_rate
