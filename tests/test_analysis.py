"""Tests for backend.api.analysis (capstone-round Bundle 1, Task 4, Req 1.2-1.6).

`backend/api/*` is a thin FastAPI route wrapper (already in
`[tool.coverage.run] omit`, "covered by integration tests" per the project's
existing precedent — see pyproject.toml) so these are integration-style tests
that call `analyze_skin()` directly with a mocked `AsyncOpenAI` client, rather
than unit tests targeting coverage. They exercise:

  - the schema-constrained primary path (`structured_completion()`'s
    `response_format` branch) end-to-end through `analyze_skin()`
  - the prompt-only fallback path (triggered by a rejected `response_format`)
  - the new nullable `Alternative.probability` field (Req 1.6), asserting a
    populated probability still round-trips as a string (Req 1.5) alongside a
    null one in the same response
  - the terminal-failure path (`StructuredOutputError`) surfacing as the same
    controlled HTTP 502 `analyze_skin()` already returned before this change
"""

import io
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from openai import BadRequestError
from PIL import Image

from backend.api.analysis import analyze_skin
from backend.schemas import SkinAnalysisResult


# --- test fixtures / helpers -------------------------------------------------


def _make_test_image_bytes() -> bytes:
    """A tiny valid JPEG, so `_prepare_for_vision()`'s real PIL round-trip runs."""
    img = Image.new("RGB", (20, 20), color=(200, 150, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class _FakeUploadFile:
    """Stands in for FastAPI's `UploadFile` — only `.content_type` and
    `async .read()` are used by `analyze_skin()`.
    """

    def __init__(self, content: bytes, content_type: str = "image/jpeg"):
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _mock_db() -> MagicMock:
    """A bare `Session` double — `analyze_skin()` no longer looks up a `User`
    row by username (Task 21: the deferred `User.username` lookup from Task 4
    is dropped now that `get_current_user` already returns the `user_id`),
    so this only needs to support `db.add()` / `db.commit()`.
    """
    return MagicMock()


def _mock_openai_client(*create_side_effects) -> MagicMock:
    """MagicMock standing in for AsyncOpenAI, matching test_llm_structured.py's
    `_mock_client()` helper — `.chat.completions.create()` returns the given
    side effects in order across successive calls.
    """
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=list(create_side_effects))
    return client


def _completion(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


def _bad_request_error() -> BadRequestError:
    httpx_response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )
    return BadRequestError(
        "response_format not supported for this model", response=httpx_response, body=None
    )


_VALID_RESULT_JSON = (
    '{"condition":"Acne","confidence":0.82,'
    '"alternatives":['
    '{"condition":"Eczema","probability":"12.3%"},'
    '{"condition":"Psoriasis","probability":null}'
    '],'
    '"reasoning":"Visible comedones and inflammatory papules.",'
    '"disclaimer":"This is an AI screening tool for educational purposes only. '
    'It does not constitute a medical diagnosis. Please consult a qualified dermatologist."}'
)


async def _run_analyze_skin(
    monkeypatch,
    client: MagicMock,
    db: MagicMock | None = None,
    user_id: str = "test-user-id",
):
    monkeypatch.setattr("backend.api.analysis.AsyncOpenAI", lambda **kwargs: client)
    file = _FakeUploadFile(_make_test_image_bytes())
    db = db if db is not None else _mock_db()
    return await analyze_skin(file=file, user_id=user_id, db=db)


# --- tests --------------------------------------------------------------------


class TestAnalyzeSkinSchemaConstrainedPath:
    @pytest.mark.asyncio
    async def test_primary_path_success_returns_parsed_result(self, monkeypatch):
        client = _mock_openai_client(_completion(_VALID_RESULT_JSON))

        result = await _run_analyze_skin(monkeypatch, client)

        assert isinstance(result, SkinAnalysisResult)
        assert result.condition == "Acne"
        assert result.confidence == 0.82
        # Only the primary (schema-constrained) call was made — no fallback round-trip.
        assert client.chat.completions.create.await_count == 1
        primary_kwargs = client.chat.completions.create.await_args_list[0].kwargs
        assert primary_kwargs["response_format"]["type"] == "json_schema"
        assert primary_kwargs["response_format"]["json_schema"]["strict"] is True

    @pytest.mark.asyncio
    async def test_populated_and_null_probability_coexist(self, monkeypatch):
        """Req 1.5/1.6: a present probability still reads as a string, a missing
        one is explicitly null rather than silently dropped from the response.
        """
        client = _mock_openai_client(_completion(_VALID_RESULT_JSON))

        result = await _run_analyze_skin(monkeypatch, client)

        assert result.alternatives[0].condition == "Eczema"
        assert result.alternatives[0].probability == "12.3%"
        assert result.alternatives[1].condition == "Psoriasis"
        assert result.alternatives[1].probability is None

    @pytest.mark.asyncio
    async def test_persists_analysis_record_for_existing_user(self, monkeypatch):
        client = _mock_openai_client(_completion(_VALID_RESULT_JSON))
        db = _mock_db()

        await _run_analyze_skin(monkeypatch, client, db=db, user_id="uuid-42")

        db.add.assert_called_once()
        db.commit.assert_called_once()
        saved_record = db.add.call_args[0][0]
        assert saved_record.user_id == "uuid-42"
        assert saved_record.condition == "Acne"


class TestAnalyzeSkinFallbackPath:
    @pytest.mark.asyncio
    async def test_bad_request_error_triggers_fallback_and_succeeds(self, monkeypatch):
        client = _mock_openai_client(_bad_request_error(), _completion(_VALID_RESULT_JSON))

        result = await _run_analyze_skin(monkeypatch, client)

        assert result.condition == "Acne"
        assert client.chat.completions.create.await_count == 2
        # Fallback call must not pass response_format at all.
        fallback_kwargs = client.chat.completions.create.await_args_list[1].kwargs
        assert "response_format" not in fallback_kwargs
        # Fallback system prompt must carry the explicit JSON-shape instruction.
        fallback_system_message = fallback_kwargs["messages"][0]["content"]
        assert "Return ONLY valid JSON" in fallback_system_message

    @pytest.mark.asyncio
    async def test_schema_validation_failure_on_200_triggers_fallback(self, monkeypatch):
        client = _mock_openai_client(
            _completion("not valid json at all"),
            _completion(_VALID_RESULT_JSON),
        )

        result = await _run_analyze_skin(monkeypatch, client)

        assert result.condition == "Acne"
        assert client.chat.completions.create.await_count == 2


class TestAnalyzeSkinTerminalFailure:
    @pytest.mark.asyncio
    async def test_unparseable_fallback_raises_controlled_502(self, monkeypatch):
        client = _mock_openai_client(_bad_request_error(), _completion("still not valid json"))

        with pytest.raises(HTTPException) as exc_info:
            await _run_analyze_skin(monkeypatch, client)

        assert exc_info.value.status_code == 502
        assert exc_info.value.detail == "Could not parse analysis result."

    @pytest.mark.asyncio
    async def test_network_error_on_primary_call_raises_controlled_502(self, monkeypatch):
        client = _mock_openai_client(RuntimeError("connection reset"))

        with pytest.raises(HTTPException) as exc_info:
            await _run_analyze_skin(monkeypatch, client)

        assert exc_info.value.status_code == 502
        assert exc_info.value.detail == "Vision model unavailable. Please try again."
