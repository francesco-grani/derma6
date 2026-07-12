"""Unit test for `stream_resume_response()`'s rate-limit gate (security-remediation
Task 55, Req 19.6) — mirrors `stream_agent_response()`'s existing `_rate_limiter.check()`
gate, which `tests/test_graph_memory_retrieval.py` documents is already covered
indirectly; this file adds the resume-path-specific case.

`backend/agent/graph.py` is coverage-omitted (LangGraph streaming requires a live LLM
+ graph runtime, per pyproject.toml) — this test exercises just the rate-limit gate by
patching `_rate_limiter`, without needing a live graph/LLM.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.graph import stream_resume_response


async def _consume(agen):
    return [chunk async for chunk in agen]


class TestStreamResumeResponseRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limited_user_gets_error_without_touching_the_graph(self):
        with (
            patch("backend.agent.graph._rate_limiter") as mock_limiter,
            patch("backend.agent.graph._store") as mock_store,
            patch("backend.agent.graph.build_graph") as mock_build_graph,
        ):
            mock_limiter.check.return_value = False

            chunks = await _consume(
                stream_resume_response("uid-alice", "session-1", "run-1", "confirm", "")
            )

        assert any("Rate limit exceeded" in c for c in chunks)
        assert any("[DONE]" in c for c in chunks)
        mock_store.get_profile.assert_not_called()
        mock_build_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_user_proceeds_past_the_gate(self):
        class _FakeCompiledGraph:
            async def astream(self, *args, **kwargs):
                return
                yield  # pragma: no cover — makes this an async generator

            async def aget_state(self, *args, **kwargs):
                return MagicMock(tasks=[])

        with (
            patch("backend.agent.graph._rate_limiter") as mock_limiter,
            patch("backend.agent.graph._store") as mock_store,
            patch("backend.agent.graph._make_tools", return_value=[]),
            patch("backend.agent.graph.build_graph", return_value=_FakeCompiledGraph()) as mock_build_graph,
            patch("backend.agent.graph.build_system_prompt", return_value=""),
            patch("backend.agent.graph.get_history") as mock_get_history,
        ):
            mock_limiter.check.return_value = True
            mock_store.get_all_routines.return_value = []
            mock_get_history.return_value = MagicMock(messages=[])

            chunks = await _consume(
                stream_resume_response("uid-alice", "session-1", "run-1", "confirm", "")
            )

        assert not any("Rate limit exceeded" in c for c in chunks)
        mock_build_graph.assert_called_once()
