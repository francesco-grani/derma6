"""BackendService: central integration layer for the Skincare Routine Builder RAG chatbot.

Wires together rate limiting, profile management, system-prompt construction,
chat history, and the LangChain/LangGraph agent with all five domain tools.
"""

import logging

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.db.chat_history import get_history
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.rate_limiter import RateLimiter
from backend.schemas import BackendRequest, BackendResponse, UserProfile
from backend.tools.conflict_checker import conflict_checker
from backend.tools.introduction_scheduler import introduction_scheduler
from backend.tools.routine_sequencer import routine_sequencer
from backend.tools.skin_type_advisor import skin_type_advisor
from backend.tools.spf_recommender import spf_recommender

logger = logging.getLogger(__name__)

_PERSONA = (
    "You are a friendly, knowledgeable skincare assistant for male beginners. "
    "You specialise exclusively in skincare routines, ingredient science, and skin health. "
    "You do not answer questions outside this domain — if asked, politely redirect to skincare topics."
)

_CITATION_RULE = (
    "CITATIONS: When you use information retrieved by tools, always mention the source "
    "document name at the end of your response."
)

_TOOL_INSTRUCTIONS = (
    "TOOLS AVAILABLE:\n"
    "- conflict_checker: Check if two ingredients conflict. Input: \"ingredient_a, ingredient_b\"\n"
    "- routine_sequencer: Order ingredients into correct routine steps. Input: comma-separated ingredients\n"
    "- skin_type_advisor: Classify skin type from description. "
    "Input: \"description: <text> | username: <username>\"\n"
    "- spf_recommender: Recommend SPF products. Input: user query string\n"
    "- introduction_scheduler: Create phased introduction schedule. "
    "Input: \"actives: a, b, c | username: <username>\""
)


def _sanitise(text: str) -> str:
    """Sanitise user-controlled text before embedding it in the system prompt.

    Prevents prompt-injection attacks that exploit newlines or section delimiters.

    Steps applied (in order):
    1. Truncate at the first newline (\\n or \\r) — anything after a newline is
       attacker-injected prompt content and is discarded entirely.
    2. Truncate at the first occurrence of the ``---`` section-delimiter sequence
       — anything after it is discarded.
    3. Strip leading/trailing whitespace from the surviving fragment.

    Args:
        text: Raw user-controlled string (e.g. skin_type, concern, medical flag).

    Returns:
        Sanitised string safe to embed in the system prompt.
    """
    # Truncate at first CR or LF
    for nl in ("\r\n", "\r", "\n"):
        idx = text.find(nl)
        if idx != -1:
            text = text[:idx]

    # Truncate at first section delimiter
    idx = text.find("---")
    if idx != -1:
        text = text[:idx]

    return text.strip()


def build_system_prompt(profile: UserProfile) -> str:
    """Build a system prompt string tailored to the user's profile.

    Args:
        profile: The user's current UserProfile.

    Returns:
        A multi-section system prompt string.
    """
    sections: list[str] = [_PERSONA]

    # --- Profile summary ---
    if not profile.onboarding_complete:
        sections.append(
            "ONBOARDING: This user has not completed their skin profile. "
            "Your priority is to ask questions to determine their skin type, main concerns, "
            "and whether they shave. Collect: skin_type, skin_concerns (list), "
            "has_shaving_routine (yes/no)."
        )
    else:
        safe_skin_type = _sanitise(profile.skin_type) if profile.skin_type else profile.skin_type
        safe_concerns = [_sanitise(c) for c in profile.skin_concerns]
        sections.append(
            f"USER PROFILE: skin_type={safe_skin_type}, "
            f"concerns={safe_concerns}, "
            f"shaving={profile.has_shaving_routine}"
        )

    # --- Medical flag rule (only when flags are present) ---
    if profile.medical_flags:
        safe_flags = [_sanitise(f) for f in profile.medical_flags]
        flags_str = ", ".join(safe_flags)
        sections.append(
            f"MEDICAL FLAG: This user has flagged: {flags_str}. "
            "Always append this disclaimer to your responses: "
            f'"⚠️ I\'m an AI assistant, not a dermatologist. '
            f"Given your skin condition ({flags_str}), please consult a qualified "
            f'dermatologist before introducing new actives."'
        )

    # --- Citation rule ---
    sections.append(_CITATION_RULE)

    # --- Tool instructions ---
    sections.append(_TOOL_INSTRUCTIONS)

    return "\n\n".join(sections)


def _build_medical_disclaimer(medical_flags: list[str]) -> str:
    """Return the medical disclaimer string for appending to answers."""
    flags_str = ", ".join(medical_flags)
    return (
        f"\n\n⚠️ I'm an AI assistant, not a dermatologist. "
        f"Given your skin condition ({flags_str}), please consult a qualified "
        "dermatologist before introducing new actives."
    )


def _extract_citations_from_messages(messages: list) -> list[str]:
    """Scan ToolMessage outputs for source names and return a deduplicated list.

    Looks for strings containing "Sources:" (e.g. from spf_recommender output) or
    "source_name:" key patterns in tool message content.

    Args:
        messages: The list of LangChain messages from the agent result.

    Returns:
        Deduplicated list of citation strings, preserving first-seen order.
    """
    seen: set[str] = set()
    citations: list[str] = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue

        content = msg.content
        if not isinstance(content, str):
            continue

        # Parse "Sources: Name1, Name2" lines
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("Sources:"):
                raw = stripped[len("Sources:"):].strip()
                for source in raw.split(","):
                    source = source.strip()
                    if source and source not in seen:
                        seen.add(source)
                        citations.append(source)

        # Parse "source_name: <value>" patterns
        for line in content.splitlines():
            if "source_name:" in line:
                parts = line.split("source_name:", 1)
                if len(parts) == 2:
                    source = parts[1].strip().strip('"').strip("'").strip(",")
                    if source and source not in seen:
                        seen.add(source)
                        citations.append(source)

    return citations


def _extract_citations_from_intermediate_steps(intermediate_steps: list) -> list[str]:
    """Scan AgentExecutor-style intermediate_steps for source names.

    Each step is typically (AgentAction, tool_output_str). Used as a fallback
    when the agent result uses the old-style intermediate_steps format.

    Args:
        intermediate_steps: List of (AgentAction, str) tuples.

    Returns:
        Deduplicated list of citation strings.
    """
    seen: set[str] = set()
    citations: list[str] = []

    for step in intermediate_steps:
        if not isinstance(step, (list, tuple)) or len(step) < 2:
            continue

        tool_output = step[1]
        if not isinstance(tool_output, str):
            continue

        # Parse "Sources: Name1, Name2" lines
        for line in tool_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Sources:"):
                raw = stripped[len("Sources:"):].strip()
                for source in raw.split(","):
                    source = source.strip()
                    if source and source not in seen:
                        seen.add(source)
                        citations.append(source)

        # Parse "source_name: <value>" patterns
        for line in tool_output.splitlines():
            if "source_name:" in line:
                parts = line.split("source_name:", 1)
                if len(parts) == 2:
                    source = parts[1].strip().strip('"').strip("'").strip(",")
                    if source and source not in seen:
                        seen.add(source)
                        citations.append(source)

    return citations


def _extract_citations(result: dict) -> list[str]:
    """Extract deduplicated citations from an agent result dict.

    Supports both the new LangGraph messages-based format and the legacy
    intermediate_steps format, trying messages first.

    Args:
        result: The dict returned by agent.invoke().

    Returns:
        Deduplicated list of citation strings.
    """
    # New LangGraph API: result has "messages" list
    if "messages" in result:
        return _extract_citations_from_messages(result["messages"])

    # Legacy AgentExecutor format: result has "intermediate_steps"
    return _extract_citations_from_intermediate_steps(
        result.get("intermediate_steps", [])
    )


def _get_answer_from_result(result: dict) -> str:
    """Extract the assistant's final answer from an agent result dict.

    Supports both the new LangGraph messages-based format (last AIMessage)
    and the legacy AgentExecutor format (result["output"]).

    Args:
        result: The dict returned by agent.invoke().

    Returns:
        The assistant's answer string.
    """
    # New LangGraph API: last AIMessage in messages list
    if "messages" in result:
        messages = result["messages"]
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, list):
                    # Content blocks format
                    text_parts = [
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    ]
                    return "".join(text_parts)
                return str(content)
        return ""

    # Legacy format
    return result.get("output", "")


class BackendService:
    """Central service that orchestrates one turn of the skincare chatbot.

    Responsibilities (in order):
    1. Rate limit check
    2. Profile load (get or create)
    3. System prompt build
    4. Chat history load
    5. Agent construction and invocation
    6. Citation extraction and deduplication
    7. Medical disclaimer append
    8. Chat history persistence
    9. BackendResponse construction

    All exceptions from steps 2-9 are caught and surfaced as an error response.
    """

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter()

    def run(self, request: BackendRequest) -> BackendResponse:
        """Execute one chatbot turn and return a BackendResponse.

        Args:
            request: The incoming BackendRequest (username + message).

        Returns:
            A BackendResponse with the assistant's answer, citations, and error state.
        """
        username = request.username
        logger.info("BackendService.run: username=%s", username)

        # --- Rate limit check ---
        allowed = self._rate_limiter.check(username)
        if not allowed:
            logger.info("Rate limit check: blocked for %s", username)
            return BackendResponse(
                message="You are sending messages too quickly. Please wait a moment.",
                error=False,
            )
        logger.info("Rate limit check: passed for %s", username)

        try:
            # --- Load profile ---
            store = ProfileStore()
            store.get_or_create_user(username)
            profile = store.get_profile(username)
            logger.info(
                "Profile loaded for %s: onboarding_complete=%s",
                username,
                profile.onboarding_complete,
            )

            # --- Build system prompt ---
            system_prompt = build_system_prompt(profile)

            # --- Load chat history ---
            chat_history = get_history(username)

            # --- Build agent ---
            llm = ChatOpenAI(
                model=settings.llm_model,
                openai_api_key=settings.openrouter_api_key,
                openai_api_base=settings.openrouter_base_url,
            )
            tools = [
                conflict_checker,
                routine_sequencer,
                skin_type_advisor,
                spf_recommender,
                introduction_scheduler,
            ]
            agent = create_agent(
                model=llm,
                tools=tools,
                system_prompt=system_prompt,
            )

            # --- Invoke agent ---
            logger.info("Agent invoked for %s", username)
            input_messages = list(chat_history.messages) + [
                HumanMessage(content=request.message)
            ]
            result = agent.invoke({"messages": input_messages})

            # --- Extract answer ---
            answer = _get_answer_from_result(result)

            # --- Collect and deduplicate citations ---
            citations = _extract_citations(result)

            # --- Append medical disclaimer ---
            if profile.medical_flags:
                answer = answer + _build_medical_disclaimer(profile.medical_flags)

            # --- Persist to chat history ---
            chat_history.add_user_message(request.message)
            chat_history.add_ai_message(answer)

            logger.info(
                "Response generated for %s: citations=%d",
                username,
                len(citations),
            )

            return BackendResponse(
                message=answer,
                citations=citations,
                tool_results=[],
                error=False,
            )

        except Exception as e:
            logger.error("BackendService.run error for %s: %s", username, e)
            return BackendResponse(
                message="",
                error=True,
                error_message=str(e),
            )
