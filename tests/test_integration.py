"""Integration tests — T18 (core flows) and T20 (Medical Flag + domain enforcement).

T18 tests use real SQLite (via tmp_path) and mock only the LLM/agent layer.
T20 tests verify the medical-flag disclaimer and domain-restriction system prompt.

T18-1  Full onboarding flow: new user → all profile fields set → onboarding_complete True
T18-2  Conflict Checker in agent loop: mocked LLM result w/ ToolMessage → tool_results populated
T18-3  RAG citation: mocked ToolMessage w/ Sources line → citations populated
T18-4  Rate limit enforcement: 11th call blocked, LLM never invoked for it
T18-5  Missing env var at startup: subprocess without OPENROUTER_API_KEY raises

T20-1  Medical flag disclaimer appended to answer when profile has flags
T20-2  Domain restriction present in system prompt; off-topic answer passed through unchanged
"""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import backend.agent as agent_module
from backend.agent import BackendService, build_system_prompt
from backend.db.profile_store import ProfileStore
from backend.schemas import BackendRequest, BackendResponse, UserProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(**kwargs) -> UserProfile:
    defaults = dict(
        username="intuser",
        skin_type="oily",
        skin_concerns=[],
        has_shaving_routine=False,
        medical_flags=[],
        onboarding_complete=True,
    )
    defaults.update(kwargs)
    return UserProfile(**defaults)


def _agent_result(answer: str = "OK", tool_messages: list | None = None) -> dict:
    messages: list = []
    if tool_messages:
        messages.extend(tool_messages)
    messages.append(AIMessage(content=answer))
    return {"messages": messages}


def _run_service(
    profile: UserProfile,
    agent_result: dict | None = None,
    rate_limit_allowed: bool = True,
    message: str = "hello",
) -> BackendResponse:
    if agent_result is None:
        agent_result = _agent_result()

    with (
        patch("backend.agent.RateLimiter") as MockRL,
        patch("backend.agent.ProfileStore") as MockPS,
        patch("backend.agent.get_history") as mock_gh,
        patch("backend.agent.ChatOpenAI"),
        patch("backend.agent.create_agent") as mock_ca,
    ):
        MockRL.return_value.check.return_value = rate_limit_allowed
        MockPS.return_value.get_or_create_user.return_value = None
        MockPS.return_value.get_profile.return_value = profile
        mock_gh.return_value.messages = []
        mock_gh.return_value.add_user_message = MagicMock()
        mock_gh.return_value.add_ai_message = MagicMock()
        mock_ca.return_value.invoke.return_value = agent_result

        svc = BackendService()
        return svc.run(BackendRequest(username=profile.username, message=message))


# ---------------------------------------------------------------------------
# T18-1 · Full onboarding flow — real SQLite
# ---------------------------------------------------------------------------

class TestT18Onboarding:
    """T18-1: new user → all required fields set → onboarding_complete True in SQLite."""

    def test_onboarding_complete_after_all_fields_set(self, tmp_path):
        db_url = f"sqlite:///{tmp_path}/test.db"
        store = ProfileStore(db_url=db_url)

        store.get_or_create_user("newbie")
        profile = store.get_profile("newbie")
        assert profile.onboarding_complete is False

        store.update_skin_type("newbie", "combination")
        store.update_skin_concerns("newbie", ["acne", "oiliness"])
        store.update_has_shaving_routine("newbie", True)

        profile = store.get_profile("newbie")
        assert profile.onboarding_complete is True
        assert profile.skin_type == "combination"
        assert "acne" in profile.skin_concerns
        assert profile.has_shaving_routine is True

    def test_onboarding_not_complete_with_missing_fields(self, tmp_path):
        db_url = f"sqlite:///{tmp_path}/test.db"
        store = ProfileStore(db_url=db_url)
        store.get_or_create_user("partial")

        store.update_skin_type("partial", "oily")
        # skin_concerns and has_shaving_routine not set
        profile = store.get_profile("partial")
        assert profile.onboarding_complete is False

    def test_medical_flag_saved_alongside_onboarding(self, tmp_path):
        db_url = f"sqlite:///{tmp_path}/test.db"
        store = ProfileStore(db_url=db_url)
        store.get_or_create_user("flagged")

        store.update_skin_type("flagged", "dry")
        store.update_skin_concerns("flagged", ["sensitivity"])
        store.update_has_shaving_routine("flagged", False)
        store.add_medical_flag("flagged", "eczema")

        profile = store.get_profile("flagged")
        assert profile.onboarding_complete is True
        assert "eczema" in profile.medical_flags


# ---------------------------------------------------------------------------
# T18-2 · Conflict Checker in agent loop
# ---------------------------------------------------------------------------

class TestT18ConflictChecker:
    """T18-2: mocked agent loop w/ conflict_checker ToolMessage → tool_results populated."""

    def test_conflict_checker_tool_result_in_response(self):
        tool_call_id = "call_conflict"
        verdict_text = (
            "Verdict: use-at-different-times\n"
            "Reason: They work at different pH levels.\n"
            "Unknown ingredients: []"
        )
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "conflict_checker",
                        "args": {"ingredients": "retinol, vitamin c"},
                        "id": tool_call_id,
                    }
                ],
            ),
            ToolMessage(content=verdict_text, tool_call_id=tool_call_id),
            AIMessage(content="Use retinol at night and vitamin C in the morning."),
        ]
        result = _run_service(
            _make_profile(),
            agent_result={"messages": messages},
            message="Can I use retinol with vitamin C?",
        )

        assert len(result.tool_results) == 1
        tr = result.tool_results[0]
        assert tr.tool_name == "conflict_checker"
        assert "use-at-different-times" in tr.summary

    def test_multiple_tool_calls_produce_multiple_tool_results(self):
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "conflict_checker", "args": {}, "id": "c1"},
                    {"name": "kb_search", "args": {}, "id": "c2"},
                ],
            ),
            ToolMessage(content="Verdict: safe", tool_call_id="c1"),
            ToolMessage(content="Sources: Retinol Profile", tool_call_id="c2"),
            AIMessage(content="All good."),
        ]
        result = _run_service(_make_profile(), agent_result={"messages": messages})
        assert len(result.tool_results) == 2
        names = {tr.tool_name for tr in result.tool_results}
        assert names == {"conflict_checker", "kb_search"}


# ---------------------------------------------------------------------------
# T18-3 · RAG citation
# ---------------------------------------------------------------------------

class TestT18RagCitation:
    """T18-3: mocked ToolMessage with Sources line → citations present in BackendResponse."""

    def test_citation_extracted_from_tool_message(self):
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "kb_search", "args": {}, "id": "kb1"}],
            ),
            ToolMessage(
                content="Retinol is a vitamin A derivative.\n\nSources: Retinol Profile",
                tool_call_id="kb1",
            ),
            AIMessage(content="Retinol helps with skin renewal."),
        ]
        result = _run_service(_make_profile(), agent_result={"messages": messages})
        assert "Retinol Profile" in result.citations

    def test_citation_deduplicated_across_tool_messages(self):
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "kb_search", "args": {}, "id": "kb1"},
                    {"name": "kb_search", "args": {}, "id": "kb2"},
                ],
            ),
            ToolMessage(content="Sources: Retinol Profile", tool_call_id="kb1"),
            ToolMessage(content="Sources: Retinol Profile", tool_call_id="kb2"),
            AIMessage(content="Done."),
        ]
        result = _run_service(_make_profile(), agent_result={"messages": messages})
        assert result.citations.count("Retinol Profile") == 1

    def test_no_citations_when_no_tool_messages(self):
        result = _run_service(_make_profile(), agent_result=_agent_result("Hello!"))
        assert result.citations == []


# ---------------------------------------------------------------------------
# T18-4 · Rate limit enforcement
# ---------------------------------------------------------------------------

class TestT18RateLimit:
    """T18-4: 11th call from same user is rate-limited; LLM never invoked for it."""

    def test_eleventh_call_is_rate_limited(self):
        profile = _make_profile()

        with (
            patch("backend.agent.ProfileStore") as MockPS,
            patch("backend.agent.get_history") as mock_gh,
            patch("backend.agent.ChatOpenAI"),
            patch("backend.agent.create_agent") as mock_ca,
        ):
            MockPS.return_value.get_or_create_user.return_value = None
            MockPS.return_value.get_profile.return_value = profile
            mock_gh.return_value.messages = []
            mock_gh.return_value.add_user_message = MagicMock()
            mock_gh.return_value.add_ai_message = MagicMock()
            mock_ca.return_value.invoke.return_value = _agent_result("OK")

            svc = BackendService()  # one instance — real RateLimiter

            for i in range(10):
                r = svc.run(BackendRequest(username="rl_user", message="hello"))
                assert "too quickly" not in r.message, f"call {i+1} was unexpectedly blocked"

            # 11th call must be blocked
            blocked = svc.run(BackendRequest(username="rl_user", message="hello"))
            assert "too quickly" in blocked.message
            assert blocked.error is False
            # LLM invoked exactly 10 times (not 11)
            assert mock_ca.return_value.invoke.call_count == 10


# ---------------------------------------------------------------------------
# T18-5 · Missing env var at startup
# ---------------------------------------------------------------------------

class TestT18MissingEnvVar:
    """T18-5: importing backend.config without OPENROUTER_API_KEY raises RuntimeError."""

    def test_missing_openrouter_api_key_raises_at_import(self, tmp_path):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENROUTER_API_KEY", "DOTENV_PATH")
        }
        # Run from tmp_path so there is no local .env file
        result = subprocess.run(
            [sys.executable, "-c", "import backend.config"],
            env=env,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        error_output = result.stderr + result.stdout
        assert "OPENROUTER_API_KEY" in error_output or "RuntimeError" in error_output


# ---------------------------------------------------------------------------
# T20-1 · Medical flag disclaimer appended to answer
# ---------------------------------------------------------------------------

class TestT20MedicalFlagDisclaimer:
    """T20-1: response includes disclaimer text whenever user has medical flags."""

    def test_disclaimer_appended_when_medical_flags_set(self):
        profile = _make_profile(medical_flags=["eczema"])
        result = _run_service(profile, agent_result=_agent_result("Apply niacinamide."))
        assert "⚠️" in result.message
        assert "dermatologist" in result.message
        assert "eczema" in result.message

    def test_no_disclaimer_when_no_medical_flags(self):
        profile = _make_profile(medical_flags=[])
        result = _run_service(profile, agent_result=_agent_result("Apply niacinamide."))
        assert "⚠️" not in result.message
        assert "dermatologist" not in result.message

    def test_response_still_delivered_alongside_disclaimer(self):
        """No hard block: full answer is present together with the disclaimer."""
        profile = _make_profile(medical_flags=["rosacea"])
        answer_text = "Use a gentle cleanser and ceramide moisturiser."
        result = _run_service(profile, agent_result=_agent_result(answer_text))
        assert answer_text in result.message
        assert "⚠️" in result.message


# ---------------------------------------------------------------------------
# T20-2 · Domain restriction in system prompt; off-topic answer passed through
# ---------------------------------------------------------------------------

class TestT20DomainRestriction:
    """T20-2: system prompt restricts domain; off-topic answer is passed through unchanged."""

    def test_system_prompt_contains_domain_restriction(self):
        profile = _make_profile()
        prompt = build_system_prompt(profile)
        assert "skincare" in prompt.lower()
        assert "politely redirect" in prompt.lower() or "do not answer" in prompt.lower()

    def test_off_topic_redirect_response_passed_through(self):
        """With a mocked LLM that returns a redirect, BackendService preserves it."""
        redirect_msg = (
            "I only help with skincare topics. "
            "Please ask me about your skincare routine!"
        )
        profile = _make_profile()
        result = _run_service(
            profile,
            agent_result=_agent_result(redirect_msg),
            message="What's the capital of France?",
        )
        assert redirect_msg in result.message
        assert result.error is False
