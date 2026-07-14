# Verification spike finding (capstone-round Task 1, scripts/verify_structured_output.py,
# recorded 2026-07-09 against the live OpenRouter API, 3 consecutive runs): schema-shape
# conformance CONFIRMED for settings.vision_model (google/gemini-2.5-flash) —
# response_format={"type": "json_schema", "strict": True} is honored, not silently
# ignored/degraded to plain text. Re-run scripts/verify_structured_output.py and update
# this comment if settings.vision_model is ever changed.
"""Schema-enforced structured output helpers (capstone-round Bundle 1, Req 1-3).

This module is the single place `response_format`-based schema enforcement is
implemented, reused by skin analysis (`backend/api/analysis.py`), memory-fact
extraction (`backend/agent/memory_extraction.py`), and readiness-report
synthesis (`backend/agent/report_pipeline.py`).
"""

import json
import logging
from typing import Any, TypeVar

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_DEFAULT_FALLBACK_SUFFIX = "Return ONLY valid JSON matching the schema above."


class StructuredOutputError(Exception):
    """Raised when neither the schema-constrained primary path nor the
    prompt-only fallback path yields a response parseable into the requested
    ``schema_model`` (Req 1.4). Callers convert this into a controlled,
    user-visible error (e.g. HTTP 502) rather than letting an unparseable
    LLM response surface as an unhandled exception (Req 17.1).
    """


def to_strict_json_schema(model: type[BaseModel]) -> dict:
    """Convert a Pydantic v2 model into an OpenAI strict-mode-compatible JSON schema.

    Starts from ``model.model_json_schema()`` and tightens every object schema
    found anywhere in the tree (the top-level schema, every entry under
    ``$defs``, and every nested object reachable through ``properties``,
    ``items``, ``anyOf``/``oneOf`` branches, etc.) so that:

    - every object gets ``"additionalProperties": False``
    - every property key is listed in ``"required"``, even properties that are
      optional on the Pydantic model — OpenAI's strict mode requires all keys
      to be present in ``required``; optionality is expressed via the field's
      type union instead (see below), not via omission from ``required``
    - ``Optional[X]`` / ``X | None`` fields are represented explicitly as
      ``{"anyOf": [<X schema>, {"type": "null"}]}`` rather than being silently
      dropped from the schema (Req 1.6) — this is already Pydantic v2's
      default rendering for such fields, so no extra transformation is needed
      beyond keeping the key listed in ``required``

    This is a pure function: no I/O, no network calls, fully unit-testable
    (Req 18.1).

    Args:
        model: A Pydantic v2 ``BaseModel`` subclass.

    Returns:
        A JSON-schema ``dict`` suitable for
        ``response_format={"type": "json_schema", "json_schema": {"schema": ..., "strict": True}}``.
    """
    schema = model.model_json_schema()
    _tighten(schema)
    return schema


def _tighten(node: Any) -> None:
    """Recursively mutate `node` in place, tightening every object schema found.

    Walks dicts and lists generically so it reaches every nested schema
    regardless of where it's referenced from (`properties`, `items`,
    `anyOf`/`oneOf` branches, and `$defs` entries alike) without needing
    separate handling for each of those JSON Schema constructs.
    """
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        if node.get("type") == "array":
            # `maxItems`/`minItems` (from a Pydantic `Field(max_length=...)`
            # on a list) is rejected outright by several OpenRouter-routed
            # providers' structured-output schema validation (observed live:
            # Anthropic, Amazon Bedrock, and Azure all rejected
            # `DiscoveredSourcesLLM`'s schema with "property 'maxItems' is
            # not supported", which silently degraded discovery to its
            # fallback path every single call). Stripping it here keeps the
            # Pydantic-level `max_length` validation intact for Python-side
            # construction (`DiscoveredSourcesLLM(...)` still raises
            # `ValidationError` past 6 items) — only the JSON schema sent to
            # the provider drops the constraint.
            node.pop("maxItems", None)
            node.pop("minItems", None)
        for value in node.values():
            _tighten(value)
    elif isinstance(node, list):
        for item in node:
            _tighten(item)


async def structured_completion(
    client: AsyncOpenAI,
    *,
    model: str,
    system_prompt: str,
    user_content: list | str,
    schema_model: type[T],
    max_tokens: int = 1024,
    temperature: float = 0.1,
    fallback_prompt_suffix: str = _DEFAULT_FALLBACK_SUFFIX,
) -> tuple[T, bool]:
    """Request a schema-conforming completion, with a documented fallback (Req 1.3).

    Shared by skin analysis (`backend/api/analysis.py`), memory-fact extraction
    (`backend/agent/memory_extraction.py`), and readiness-report synthesis
    (`backend/agent/report_pipeline.py`) so the fallback behaviour (Req 17.2) is
    implemented once and inherited everywhere, rather than reinvented per call site.

    1. Try the primary path: `response_format={"type": "json_schema", ...}` built
       from `to_strict_json_schema(schema_model)`, parsed via
       `schema_model.model_validate_json(...)`.
    2. If the provider rejects `response_format` outright (`openai.BadRequestError`)
       or the primary response's content fails schema validation, fall back to a
       prompt-only request: `system_prompt` + `fallback_prompt_suffix` describing the
       shape in text, no `response_format`, parsed via `json.loads` +
       `schema_model(**parsed)` — the same approach `analyze_skin()` already used,
       generalised here.
    3. If the fallback response is also unparseable, raise `StructuredOutputError`
       (Req 1.4) rather than letting the exception propagate unhandled (Req 17.1).

    Any other exception raised by the primary network call (timeouts, connection
    errors, non-`BadRequestError` API errors) is intentionally left to propagate —
    callers already wrap their own network calls in a `try/except` that converts
    such failures into a controlled error (e.g. analysis.py's existing 502 handling).

    Returns:
        A `(parsed_model, used_fallback)` tuple — `used_fallback` is `True` iff the
        prompt-only fallback path was used to produce the result.
    """
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_model.__name__,
                    "schema": to_strict_json_schema(schema_model),
                    "strict": True,
                },
            },
        )
    except BadRequestError as exc:
        logger.warning(
            "structured_completion: model=%s rejected response_format (%s); "
            "falling back to prompt-only JSON generation",
            model,
            exc,
        )
        return await _fallback_completion(
            client,
            model=model,
            system_prompt=system_prompt,
            user_content=user_content,
            schema_model=schema_model,
            max_tokens=max_tokens,
            temperature=temperature,
            fallback_prompt_suffix=fallback_prompt_suffix,
        )

    raw = (response.choices[0].message.content or "").strip()
    try:
        parsed = schema_model.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "structured_completion: model=%s's schema-constrained response failed "
            "validation (%s); falling back to prompt-only JSON generation",
            model,
            exc,
        )
        return await _fallback_completion(
            client,
            model=model,
            system_prompt=system_prompt,
            user_content=user_content,
            schema_model=schema_model,
            max_tokens=max_tokens,
            temperature=temperature,
            fallback_prompt_suffix=fallback_prompt_suffix,
        )

    return parsed, False


async def _fallback_completion(
    client: AsyncOpenAI,
    *,
    model: str,
    system_prompt: str,
    user_content: list | str,
    schema_model: type[T],
    max_tokens: int,
    temperature: float,
    fallback_prompt_suffix: str,
) -> tuple[T, bool]:
    """Prompt-only JSON fallback path (Req 1.3), used when `response_format`
    is unsupported/rejected or the primary response fails schema validation.

    Raises `StructuredOutputError` (Req 1.4) if the fallback response is also
    unparseable, rather than letting `json.JSONDecodeError`/`ValidationError`/
    `TypeError` propagate as an unhandled exception (Req 17.1).
    """
    fallback_system_prompt = f"{system_prompt}\n\n{fallback_prompt_suffix}"
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": fallback_system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed_json = json.loads(raw)
        result = schema_model(**parsed_json)
    except Exception as exc:
        logger.error(
            "structured_completion: fallback prompt-only JSON path also failed "
            "for model=%s, schema=%s: %s",
            model,
            schema_model.__name__,
            exc,
        )
        raise StructuredOutputError(
            f"Could not obtain a {schema_model.__name__}-conforming response from "
            f"model={model!r} via either the schema-constrained or fallback path."
        ) from exc

    return result, True
