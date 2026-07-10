"""Unit tests for backend.llm.structured.

`to_strict_json_schema()` is pure schema-conversion logic (Req 18.1) — no
network calls, no LLM client. Covers: nested objects, arrays, Literal enums,
and Optional/X | None fields explicitly represented (rather than omitted)
per Req 1.6.

`structured_completion()`'s fallback-selection logic is business logic
Req 18.1 wants tested, so it is covered here via a mocked `AsyncOpenAI`
client rather than a blanket coverage omit (per the design's stated
preference) — covering: primary-path success, fallback triggered by
`openai.BadRequestError`, fallback triggered by schema-validation failure on
a 200, and terminal failure raising `StructuredOutputError` (Req 1.1-1.4).
"""

import json
from typing import Literal, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import BadRequestError
from pydantic import BaseModel

from backend.llm.structured import (
    StructuredOutputError,
    structured_completion,
    to_strict_json_schema,
)


class _Flat(BaseModel):
    """A model with only scalar fields, one required and one optional."""

    required_field: str
    optional_field: str | None = None


class _Address(BaseModel):
    city: str
    zip_code: str | None = None


class _WithNestedList(BaseModel):
    """A model whose field is a list of a nested BaseModel (rendered via $defs/$ref)."""

    name: str
    addresses: list[_Address]


class _WithOptionalNested(BaseModel):
    """A model with an Optional[NestedModel] field — exercises anyOf + $ref together."""

    name: str
    primary_address: Optional[_Address] = None


class _WithLiteral(BaseModel):
    skin_type: Literal["oily", "dry", "combination"]


class TestFlatModel:
    def test_additional_properties_false_on_root(self):
        schema = to_strict_json_schema(_Flat)
        assert schema["additionalProperties"] is False

    def test_required_includes_optional_field(self):
        schema = to_strict_json_schema(_Flat)
        # Req 1.6: optional fields must still be listed in "required" —
        # OpenAI strict mode requires every property key present in "required",
        # optionality is expressed through the field's type union instead.
        assert set(schema["required"]) == {"required_field", "optional_field"}

    def test_optional_field_represented_as_anyof_with_null(self):
        schema = to_strict_json_schema(_Flat)
        optional_schema = schema["properties"]["optional_field"]
        assert "anyOf" in optional_schema
        types_in_anyof = {branch.get("type") for branch in optional_schema["anyOf"]}
        assert types_in_anyof == {"string", "null"}

    def test_required_field_not_nullable(self):
        schema = to_strict_json_schema(_Flat)
        assert schema["properties"]["required_field"]["type"] == "string"

    def test_returns_a_plain_dict(self):
        schema = to_strict_json_schema(_Flat)
        assert isinstance(schema, dict)

    def test_is_deterministic(self):
        assert to_strict_json_schema(_Flat) == to_strict_json_schema(_Flat)


class TestNestedObjectsAndArrays:
    def test_defs_entry_gets_additional_properties_false(self):
        schema = to_strict_json_schema(_WithNestedList)
        address_def = schema["$defs"]["_Address"]
        assert address_def["additionalProperties"] is False

    def test_defs_entry_required_includes_optional_field(self):
        schema = to_strict_json_schema(_WithNestedList)
        address_def = schema["$defs"]["_Address"]
        assert set(address_def["required"]) == {"city", "zip_code"}

    def test_array_field_references_defs_via_ref(self):
        schema = to_strict_json_schema(_WithNestedList)
        addresses_schema = schema["properties"]["addresses"]
        assert addresses_schema["type"] == "array"
        assert "$ref" in addresses_schema["items"]

    def test_root_still_tightened_alongside_nested_defs(self):
        schema = to_strict_json_schema(_WithNestedList)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {"name", "addresses"}

    def test_optional_nested_object_combines_anyof_and_ref(self):
        schema = to_strict_json_schema(_WithOptionalNested)
        primary_address_schema = schema["properties"]["primary_address"]
        assert "anyOf" in primary_address_schema
        branch_keys = [set(branch.keys()) for branch in primary_address_schema["anyOf"]]
        assert any("$ref" in keys for keys in branch_keys)
        assert any(branch.get("type") == "null" for branch in primary_address_schema["anyOf"])

    def test_nested_def_reached_through_optional_still_tightened(self):
        schema = to_strict_json_schema(_WithOptionalNested)
        address_def = schema["$defs"]["_Address"]
        assert address_def["additionalProperties"] is False
        assert set(address_def["required"]) == {"city", "zip_code"}

    def test_optional_nested_field_listed_in_required(self):
        schema = to_strict_json_schema(_WithOptionalNested)
        assert "primary_address" in schema["required"]


class TestLiteralEnum:
    def test_literal_field_keeps_enum_representation(self):
        schema = to_strict_json_schema(_WithLiteral)
        skin_type_schema = schema["properties"]["skin_type"]
        assert skin_type_schema["enum"] == ["oily", "dry", "combination"]

    def test_literal_field_not_treated_as_object(self):
        schema = to_strict_json_schema(_WithLiteral)
        skin_type_schema = schema["properties"]["skin_type"]
        assert "additionalProperties" not in skin_type_schema

    def test_required_still_includes_literal_field(self):
        schema = to_strict_json_schema(_WithLiteral)
        assert "skin_type" in schema["required"]


# --- structured_completion() -------------------------------------------------


class _Result(BaseModel):
    """A minimal schema_model target used to exercise structured_completion()."""

    answer: str
    confidence: float


def _mock_client(*create_side_effects) -> MagicMock:
    """Build a MagicMock standing in for AsyncOpenAI, whose
    `.chat.completions.create()` is an AsyncMock with the given side effects
    (queued in order across successive calls — first call gets the first
    entry, second call the second, etc.).
    """
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=list(create_side_effects))
    return client


def _completion(content: str) -> MagicMock:
    """Build a fake ChatCompletion-shaped response exposing only the
    `.choices[0].message.content` path structured_completion() reads.
    """
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


def _bad_request_error() -> BadRequestError:
    """Build a real openai.BadRequestError, matching what the AsyncOpenAI
    client actually raises on a 4xx response.
    """
    httpx_response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    return BadRequestError(
        "response_format not supported for this model", response=httpx_response, body=None
    )


class TestStructuredCompletionPrimaryPath:
    @pytest.mark.asyncio
    async def test_primary_path_success_returns_parsed_model_and_used_fallback_false(self):
        client = _mock_client(_completion('{"answer": "oily", "confidence": 0.9}'))

        result, used_fallback = await structured_completion(
            client,
            model="anthropic/claude-haiku-4.5",
            system_prompt="system",
            user_content="user",
            schema_model=_Result,
        )

        assert result == _Result(answer="oily", confidence=0.9)
        assert used_fallback is False
        # Only the primary call was made — no fallback round-trip.
        assert client.chat.completions.create.await_count == 1
        primary_kwargs = client.chat.completions.create.await_args_list[0].kwargs
        assert primary_kwargs["response_format"]["type"] == "json_schema"
        assert primary_kwargs["response_format"]["json_schema"]["strict"] is True


class TestStructuredCompletionFallbackOnBadRequest:
    @pytest.mark.asyncio
    async def test_bad_request_error_triggers_fallback_and_succeeds(self):
        client = _mock_client(
            _bad_request_error(),
            _completion('{"answer": "dry", "confidence": 0.5}'),
        )

        result, used_fallback = await structured_completion(
            client,
            model="anthropic/claude-haiku-4.5",
            system_prompt="system",
            user_content="user",
            schema_model=_Result,
        )

        assert result == _Result(answer="dry", confidence=0.5)
        assert used_fallback is True
        assert client.chat.completions.create.await_count == 2
        # Fallback call must not pass response_format at all.
        fallback_kwargs = client.chat.completions.create.await_args_list[1].kwargs
        assert "response_format" not in fallback_kwargs

    @pytest.mark.asyncio
    async def test_fallback_system_prompt_includes_suffix(self):
        client = _mock_client(
            _bad_request_error(),
            _completion('{"answer": "dry", "confidence": 0.5}'),
        )

        await structured_completion(
            client,
            model="anthropic/claude-haiku-4.5",
            system_prompt="Analyse the input.",
            user_content="user",
            schema_model=_Result,
            fallback_prompt_suffix="Return ONLY JSON: {answer, confidence}.",
        )

        fallback_kwargs = client.chat.completions.create.await_args_list[1].kwargs
        fallback_system_message = fallback_kwargs["messages"][0]["content"]
        assert "Analyse the input." in fallback_system_message
        assert "Return ONLY JSON: {answer, confidence}." in fallback_system_message


class TestStructuredCompletionFallbackOnValidationFailure:
    @pytest.mark.asyncio
    async def test_schema_validation_failure_on_200_triggers_fallback(self):
        client = _mock_client(
            _completion("not valid json at all"),
            _completion('{"answer": "combination", "confidence": 0.7}'),
        )

        result, used_fallback = await structured_completion(
            client,
            model="anthropic/claude-haiku-4.5",
            system_prompt="system",
            user_content="user",
            schema_model=_Result,
        )

        assert result == _Result(answer="combination", confidence=0.7)
        assert used_fallback is True
        assert client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_primary_response_missing_required_field_triggers_fallback(self):
        # Valid JSON, but missing the required "confidence" field — fails
        # schema_model.model_validate_json() even though the call itself was a 200.
        client = _mock_client(
            _completion('{"answer": "oily"}'),
            _completion('{"answer": "oily", "confidence": 0.8}'),
        )

        result, used_fallback = await structured_completion(
            client,
            model="anthropic/claude-haiku-4.5",
            system_prompt="system",
            user_content="user",
            schema_model=_Result,
        )

        assert result == _Result(answer="oily", confidence=0.8)
        assert used_fallback is True


class TestStructuredCompletionTerminalFailure:
    @pytest.mark.asyncio
    async def test_unparseable_fallback_raises_structured_output_error(self):
        client = _mock_client(
            _bad_request_error(),
            _completion("still not valid json"),
        )

        with pytest.raises(StructuredOutputError):
            await structured_completion(
                client,
                model="anthropic/claude-haiku-4.5",
                system_prompt="system",
                user_content="user",
                schema_model=_Result,
            )

    @pytest.mark.asyncio
    async def test_fallback_missing_required_field_raises_structured_output_error(self):
        client = _mock_client(
            _bad_request_error(),
            _completion('{"answer": "oily"}'),  # missing "confidence"
        )

        with pytest.raises(StructuredOutputError):
            await structured_completion(
                client,
                model="anthropic/claude-haiku-4.5",
                system_prompt="system",
                user_content="user",
                schema_model=_Result,
            )

    @pytest.mark.asyncio
    async def test_structured_output_error_chains_original_exception(self):
        client = _mock_client(
            _bad_request_error(),
            _completion("{not json"),
        )

        with pytest.raises(StructuredOutputError) as exc_info:
            await structured_completion(
                client,
                model="anthropic/claude-haiku-4.5",
                system_prompt="system",
                user_content="user",
                schema_model=_Result,
            )

        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
