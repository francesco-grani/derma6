"""Tests for the query_decompose node."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.rag.pipeline.nodes.decompose import query_decompose


def _state(query: str) -> dict:
    return {"original_query": query, "node_latencies": {}}


@pytest.mark.asyncio
async def test_simple_query_returns_single_element():
    mock_resp = MagicMock()
    mock_resp.content = '["What is niacinamide?"]'
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("What is niacinamide?"))

    assert result["sub_queries"] == ["What is niacinamide?"]
    assert result["decompose_error"] is False
    assert "query_decompose" in result["node_latencies"]


@pytest.mark.asyncio
async def test_complex_query_returns_multiple():
    mock_resp = MagicMock()
    mock_resp.content = '["Is retinol safe?", "Does niacinamide conflict with retinol?"]'
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("Is retinol safe with niacinamide for dry skin?"))

    assert len(result["sub_queries"]) == 2
    assert result["decompose_error"] is False


@pytest.mark.asyncio
async def test_invalid_json_falls_back():
    mock_resp = MagicMock()
    mock_resp.content = "Here are the sub-queries: retinol, niacinamide"
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("retinol and niacinamide"))

    assert result["sub_queries"] == ["retinol and niacinamide"]
    assert result["decompose_error"] is True


@pytest.mark.asyncio
async def test_timeout_falls_back():
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()

        async def _slow(*args, **kwargs):
            await asyncio.sleep(100)

        mock_llm.ainvoke = _slow
        mock_llm_fn.return_value = mock_llm

        with patch("backend.rag.pipeline.nodes.decompose.settings") as mock_settings:
            mock_settings.decompose_timeout_seconds = 0.001
            mock_settings.rag_debug_mode = False
            result = await query_decompose(_state("test query"))

    assert result["sub_queries"] == ["test query"]
    assert result["decompose_error"] is True


@pytest.mark.asyncio
async def test_llm_exception_falls_back():
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("some skincare question"))

    assert result["sub_queries"] == ["some skincare question"]
    assert result["decompose_error"] is True


# ── _get_llm ──────────────────────────────────────────────────────────────────


def test_get_llm_is_a_singleton():
    import backend.rag.pipeline.nodes.decompose as decompose_module

    decompose_module._llm = None
    first = decompose_module._get_llm()
    second = decompose_module._get_llm()

    assert first is second
    decompose_module._llm = None


# ── Response content shape / edge cases ──────────────────────────────────────


@pytest.mark.asyncio
async def test_content_as_list_of_typed_blocks_is_joined():
    mock_resp = MagicMock()
    mock_resp.content = [{"type": "text", "text": '["What is niacinamide?"]'}]
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("What is niacinamide?"))

    assert result["sub_queries"] == ["What is niacinamide?"]
    assert result["decompose_error"] is False


@pytest.mark.asyncio
async def test_empty_content_falls_back():
    mock_resp = MagicMock()
    mock_resp.content = "   "
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("test query"))

    assert result["sub_queries"] == ["test query"]
    assert result["decompose_error"] is True


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_stripped():
    mock_resp = MagicMock()
    mock_resp.content = '```json\n["retinol basics"]\n```'
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("retinol basics"))

    assert result["sub_queries"] == ["retinol basics"]
    assert result["decompose_error"] is False


@pytest.mark.asyncio
async def test_non_list_json_falls_back():
    mock_resp = MagicMock()
    mock_resp.content = '{"not": "a list"}'
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("test query"))

    assert result["sub_queries"] == ["test query"]
    assert result["decompose_error"] is True


@pytest.mark.asyncio
async def test_empty_list_json_falls_back():
    mock_resp = MagicMock()
    mock_resp.content = "[]"
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        result = await query_decompose(_state("test query"))

    assert result["sub_queries"] == ["test query"]
    assert result["decompose_error"] is True


@pytest.mark.asyncio
async def test_debug_mode_logs_without_error():
    mock_resp = MagicMock()
    mock_resp.content = '["a", "b"]'
    with patch("backend.rag.pipeline.nodes.decompose._get_llm") as mock_llm_fn:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)
        mock_llm_fn.return_value = mock_llm

        with patch("backend.rag.pipeline.nodes.decompose.settings") as ms:
            ms.decompose_timeout_seconds = 10
            ms.rag_debug_mode = True
            result = await query_decompose(_state("a and b"))

    assert result["sub_queries"] == ["a", "b"]
    assert result["decompose_error"] is False
