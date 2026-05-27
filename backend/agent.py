"""BackendService: central integration layer for the Derma6 RAG chatbot.

Wires together rate limiting, profile management, system-prompt construction,
chat history, and the LangChain/LangGraph agent with all five domain tools.
"""

import logging

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.db.chat_history import get_history
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.logging_config import set_log_username
from backend.rate_limiter import RateLimiter
from backend.schemas import BackendRequest, BackendResponse, UserProfile
from backend.tools.conflict_checker import conflict_checker
from backend.tools.introduction_scheduler import introduction_scheduler
from backend.tools.kb_search import kb_search
from backend.tools.routine_sequencer import routine_sequencer
from backend.tools.save_routine import save_routine
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

_GROUNDING_RULE = (
    "GROUNDING: Prefer to answer from information retrieved by kb_search. "
    "If the retrieved context does not fully cover the question, you may supplement "
    "with your general skincare knowledge — but clearly distinguish retrieved facts "
    "from general guidance when both appear in the same answer."
)

_CONCISENESS_RULE = (
    "STYLE: Answer the specific question asked. Be direct and concise. "
    "Do not add unsolicited skincare tips or general education beyond what directly "
    "addresses the question."
)

def _tool_instructions(username: str) -> str:
    """Return tool instructions. Username is pre-bound — tools need no username argument."""
    return (
        "TOOLS AVAILABLE — call these whenever the task requires them:\n"
        "- kb_search: Search the skincare knowledge base. ALWAYS call this first for any "
        "factual skincare question — ingredients, routines, concepts, actives, skin science. "
        "Input: the user's question or a concise search phrase.\n"
        "- conflict_checker: Check if two ingredients conflict. "
        "Input: \"ingredient_a, ingredient_b\"\n"
        "- routine_sequencer: Order ingredients into the correct routine sequence. "
        "Input: comma-separated ingredient names\n"
        "- save_routine_tool: Save a routine to the user's profile. "
        "NEVER call automatically — always ask first: 'Would you like me to save this routine to your profile?' "
        "and only call if the user confirms. "
        "name: if updating an existing routine use its EXACT existing name to replace it; "
        "otherwise use a descriptive name, e.g. 'Morning Routine', 'Evening Routine', 'Basic Routine'. "
        "steps: comma-separated steps in application order.\n"
        "- skin_type_advisor_tool: Classify the user's skin type and save it to their profile. "
        "MUST be called as soon as the user describes their skin. "
        "Input: free-text description of the user's skin, "
        "e.g. \"skin feels tight after washing and gets flaky by afternoon\"\n"
        "- update_skin_concerns_tool: Save the user's skin concerns. "
        "MUST be called as soon as the user states their concerns. "
        "Input: comma-separated concerns, e.g. \"acne, dark spots\"\n"
        "- update_shaving_routine_tool: Save whether the user shaves. "
        "MUST be called as soon as the user answers the shaving question. "
        "Input: 'yes' or 'no'\n"
        "- add_medical_flag_tool: Save a diagnosed skin condition. Call ONLY when the user "
        "explicitly states they have the condition ('I have eczema'). If they mention a condition "
        "without confirming they have it, ask first: 'Do you have this condition yourself, or are "
        "you looking for general information about it?' Input: condition name\n"
        "- spf_recommender: Recommend an SPF product. Input: the user's query as-is\n"
        "- introduction_scheduler_tool: Build a phased introduction plan and save it to the "
        "profile. Input: comma-separated active ingredients, e.g. \"retinol, niacinamide\""
    )


def _make_tools(username: str) -> list:
    """Return username-bound versions of tools that need to write to the user's profile.

    The LLM sees simple single-argument tools — no pipe-separated format, no username
    to construct. The username is injected automatically via closure.
    """
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def skin_type_advisor_tool(description: str) -> str:
        """Classify the user's skin type from their description and save it to their profile."""
        return skin_type_advisor.invoke(f"description: {description} | username: {username}")

    @lc_tool
    def save_routine_tool(name: str, steps: str) -> str:
        """Save a named skincare routine to the user's profile. Call this after routine_sequencer.
        name: descriptive name, e.g. 'Morning Routine', 'Evening Routine', 'Basic Routine'.
        steps: comma-separated steps in application order."""
        from backend.schemas import RoutineSchema, RoutineStepSchema
        step_list = [s.strip() for s in steps.split(",") if s.strip()]
        if not step_list:
            return "Error: no steps provided."
        routine_name = name.strip() or "My Routine"
        step_schemas = [
            RoutineStepSchema(position=i + 1, ingredient=step, product_name=None)
            for i, step in enumerate(step_list)
        ]
        routine = RoutineSchema(name=routine_name, steps=step_schemas)
        try:
            ProfileStore().save_routine(username, routine)
            logger.info("Routine '%s' saved for %s: %d steps", routine_name, username, len(step_list))
            return (
                f"✅ '{routine_name}' saved ({len(step_list)} steps). "
                "You can view it in the Routine Viewer tab."
            )
        except Exception as exc:
            logger.error("save_routine_tool failed: %s", exc)
            return "Sorry, I could not save the routine. Please try again."

    @lc_tool
    def introduction_scheduler_tool(actives: str) -> str:
        """Create a phased introduction schedule for new actives and save it to the profile.
        Input: comma-separated active ingredient names."""
        return introduction_scheduler.invoke(f"actives: {actives} | username: {username}")

    @lc_tool
    def update_skin_concerns_tool(concerns: str) -> str:
        """Save the user's skin concerns to their profile.
        Input: comma-separated concerns, e.g. 'acne, dark spots, dryness'"""
        concern_list = [c.strip() for c in concerns.split(",") if c.strip()]
        if not concern_list:
            return "Error: at least one concern is required."
        try:
            ProfileStore().update_skin_concerns(username, concern_list)
            logger.info("Skin concerns saved for %s: %s", username, concern_list)
            return f"Skin concerns saved: {', '.join(concern_list)}."
        except Exception as exc:
            logger.error("update_skin_concerns_tool failed: %s", exc)
            return "Sorry, I could not save your skin concerns. Please try again."

    @lc_tool
    def update_shaving_routine_tool(has_shaving: str) -> str:
        """Save whether the user has a shaving routine to their profile.
        Input: 'yes' or 'no'"""
        value = has_shaving.strip().lower()
        if value not in ("yes", "no", "true", "false", "1", "0"):
            return "Error: input must be 'yes' or 'no'."
        bool_value = value in ("yes", "true", "1")
        try:
            ProfileStore().update_has_shaving_routine(username, bool_value)
            logger.info("Shaving routine saved for %s: %s", username, bool_value)
            return f"Shaving routine preference saved: {'yes' if bool_value else 'no'}."
        except Exception as exc:
            logger.error("update_shaving_routine_tool failed: %s", exc)
            return "Sorry, I could not save your shaving preference. Please try again."

    @lc_tool
    def add_medical_flag_tool(condition: str) -> str:
        """Save a diagnosed skin condition to the user's profile.
        ONLY call this when the user explicitly confirms they personally have the condition
        (e.g. 'I have eczema', 'I suffer from rosacea'). Do NOT call if they are asking
        for information about a condition without stating they have it.
        Input: condition name, e.g. 'eczema', 'rosacea', 'psoriasis'."""
        condition = condition.strip()
        if not condition:
            return "Error: condition name must not be empty."
        try:
            ProfileStore().add_medical_flag(username, condition)
            logger.info("Medical flag added for %s: %s", username, condition)
            return (
                f"Medical flag '{condition}' saved. A dermatologist disclaimer will appear "
                "on responses that include specific recommendations."
            )
        except Exception as exc:
            logger.error("add_medical_flag_tool failed: %s", exc)
            return "Sorry, I could not save the medical flag. Please try again."

    return [
        kb_search,
        conflict_checker,
        routine_sequencer,
        save_routine_tool,
        skin_type_advisor_tool,
        update_skin_concerns_tool,
        update_shaving_routine_tool,
        add_medical_flag_tool,
        spf_recommender,
        introduction_scheduler_tool,
    ]


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


_MAX_MESSAGE_LENGTH = 500

_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all instructions",
    "you are now",
    "disregard",
    "new persona",
    "act as",
    "jailbreak",
    "dan",
]


def _check_message(message: str) -> BackendResponse | None:
    """Return a blocking BackendResponse if the message fails a pre-LLM guard, else None.

    Guards applied (in order):
    1. Length cap — rejects messages over _MAX_MESSAGE_LENGTH characters.
    2. Injection pattern block — rejects messages matching known injection phrases.
    """
    if len(message) > _MAX_MESSAGE_LENGTH:
        return BackendResponse(
            message=f"Your message is too long. Please keep it under {_MAX_MESSAGE_LENGTH} characters.",
            error=False,
        )
    lowered = message.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in lowered:
            return BackendResponse(
                message="I can only help with skincare questions.",
                error=False,
            )
    return None


def build_system_prompt(profile: UserProfile) -> str:
    """Build a system prompt string tailored to the user's profile."""
    username = _sanitise(profile.username) if profile.username else "unknown"
    sections: list[str] = [_PERSONA]

    # --- Username (always present so tools know who to update) ---
    sections.append(f"CURRENT USER: username='{username}'")

    # --- Profile summary ---
    if not profile.onboarding_complete:
        sections.append(
            "ONBOARDING: This user has not completed their skin profile. "
            "Collect the following, one question at a time, in this order:\n"
            "1. Skin description → call skin_type_advisor_tool immediately with their answer.\n"
            "2. Skin concerns (e.g. acne, dryness, dark spots) → call update_skin_concerns_tool.\n"
            "3. Shaving (yes/no) → ask exactly 'Do you actively shave your beard or body?' → call update_shaving_routine_tool.\n"
            "4. Medical skin conditions: ask 'Do you have any diagnosed skin conditions such as "
            "eczema, rosacea, or psoriasis?' → if yes, call add_medical_flag_tool once per "
            "condition mentioned; if no, skip the tool and proceed.\n"
            "CRITICAL: call the corresponding tool immediately after each answer before asking "
            "the next question. Do not proceed until the tool confirms the save."
        )
    else:
        safe_skin_type = _sanitise(profile.skin_type) if profile.skin_type else profile.skin_type
        safe_concerns = [_sanitise(c) for c in profile.skin_concerns]
        try:
            existing_routines = [r.name for r in ProfileStore().get_all_routines(profile.username)]
        except Exception:
            existing_routines = []
        routines_str = ", ".join(f"'{_sanitise(n)}'" for n in existing_routines) if existing_routines else "none"
        sections.append(
            f"USER PROFILE: skin_type={safe_skin_type}, "
            f"concerns={safe_concerns}, "
            f"shaving={profile.has_shaving_routine}, "
            f"saved_routines=[{routines_str}]"
        )

    # --- Medical flag rule (only when flags are present) ---
    if profile.medical_flags:
        safe_flags = [_sanitise(f) for f in profile.medical_flags]
        flags_str = ", ".join(safe_flags)
        sections.append(
            f"MEDICAL FLAG: This user has: {flags_str}.\n"
            "DISCLAIMER RULE — read carefully:\n"
            "APPEND the disclaimer below ONLY when you are: recommending a specific product, "
            "suggesting the user add or remove an ingredient from their routine, or advising "
            "them to start/stop using something.\n"
            "DO NOT append it when: explaining what an ingredient is, answering factual skincare "
            "questions, discussing ingredient conflicts in the abstract, or having a general "
            "conversation. When in doubt, omit it.\n"
            f'Disclaimer text (copy verbatim when applicable): '
            f'"⚠️ I\'m an AI assistant, not a dermatologist. Given your {flags_str}, '
            f'please consult a qualified dermatologist before making changes to your routine."'
        )

    # --- Grounding, conciseness, and citation rules ---
    sections.append(_GROUNDING_RULE)
    sections.append(_CONCISENESS_RULE)
    sections.append(_CITATION_RULE)

    # --- Tool instructions (with username baked in) ---
    sections.append(_tool_instructions(username))

    return "\n\n".join(sections)



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


def _extract_tool_results_from_messages(messages: list) -> list:
    """Extract ToolResult objects from agent result messages.

    Builds a tool_call_id → tool_name map from AIMessages, then creates
    a ToolResult per ToolMessage.
    """
    from backend.schemas import ToolResult

    call_id_to_name: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if isinstance(tc, dict) and "id" in tc and "name" in tc:
                    call_id_to_name[tc["id"]] = tc["name"]

    results: list = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_name = call_id_to_name.get(msg.tool_call_id, "unknown_tool")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            results.append(ToolResult(tool_name=tool_name, summary=content))
    return results


def _extract_rag_context_from_messages(messages: list) -> list[dict]:
    """Extract RAG retrieval metadata from kb_search ToolMessages.

    Parses the __RAG_CONTEXT_JSON__ footer appended by kb_search and returns
    a deduplicated list of {source, score, snippet} dicts ordered by score.
    """
    import json

    seen: set[str] = set()
    items: list[dict] = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        marker = "__RAG_CONTEXT_JSON__: "
        idx = content.find(marker)
        if idx == -1:
            continue
        try:
            raw = json.loads(content[idx + len(marker):].strip())
            for entry in raw:
                key = entry.get("source", "")
                if key and key not in seen:
                    seen.add(key)
                    items.append(entry)
        except (json.JSONDecodeError, AttributeError):
            pass

    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    return items


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
        set_log_username(username)
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

        # --- Message guard (length cap + injection patterns) ---
        guard_response = _check_message(request.message)
        if guard_response is not None:
            logger.info("Message guard blocked request for %s", username)
            return guard_response

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
                temperature=0.3,
            )
            tools = _make_tools(username)
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
            result = agent.invoke(
                {"messages": input_messages},
                config={"metadata": {"username": username}},
            )

            # --- Extract answer ---
            answer = _get_answer_from_result(result)

            # --- Collect and deduplicate citations ---
            citations = _extract_citations(result)

            # --- Collect tool results ---
            messages = result.get("messages", [])
            tool_results = _extract_tool_results_from_messages(messages)

            # --- Persist to chat history ---
            chat_history.add_user_message(request.message)
            chat_history.add_ai_message(answer)

            logger.info(
                "Response generated for %s: citations=%d tool_results=%d",
                username,
                len(citations),
                len(tool_results),
            )

            return BackendResponse(
                message=answer,
                citations=citations,
                tool_results=tool_results,
                error=False,
            )

        except Exception as e:
            logger.error("BackendService.run error for %s: %s", username, e)
            return BackendResponse(
                message="",
                error=True,
                error_message=str(e),
            )

    def build_stream(self, request: BackendRequest, result: dict):
        """Generator that yields text chunks for streaming display.

        Populates `result` with citations, error state, and full message
        once the generator is exhausted. Caller should use st.write_stream().
        """
        username = request.username
        set_log_username(username)
        logger.info("BackendService.build_stream: username=%s", username)

        # --- Rate limit check ---
        if not self._rate_limiter.check(username):
            result.update({"error": False, "citations": [], "tool_results": []})
            yield "You are sending messages too quickly. Please wait a moment."
            return

        try:
            store = ProfileStore()
            store.get_or_create_user(username)
            profile = store.get_profile(username)
            system_prompt = build_system_prompt(profile)
            chat_history = get_history(username)

            llm = ChatOpenAI(
                model=settings.llm_model,
                openai_api_key=settings.openrouter_api_key,
                openai_api_base=settings.openrouter_base_url,
                temperature=0.3,
            )
            tools = _make_tools(username)
            agent = create_agent(model=llm, tools=tools, system_prompt=system_prompt)

            input_messages = list(chat_history.messages) + [
                HumanMessage(content=request.message)
            ]

            accumulated_text: list[str] = []
            accumulated_messages: list = []

            for chunk, _ in agent.stream(
                {"messages": input_messages},
                stream_mode="messages",
                config={"metadata": {"username": username}},
            ):
                accumulated_messages.append(chunk)
                if isinstance(chunk, AIMessageChunk):
                    content = chunk.content
                    if isinstance(content, str) and content:
                        accumulated_text.append(content)
                        yield content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    accumulated_text.append(text)
                                    yield text

            answer = "".join(accumulated_text)

            citations = _extract_citations_from_messages(accumulated_messages)
            rag_context = _extract_rag_context_from_messages(accumulated_messages)

            chat_history.add_user_message(request.message)
            chat_history.add_ai_message(answer)

            logger.info(
                "build_stream complete for %s: citations=%d rag_docs=%d",
                username, len(citations), len(rag_context),
            )

            result.update({
                "message": answer,
                "citations": citations,
                "rag_context": rag_context,
                "tool_results": [],
                "error": False,
            })

        except Exception as e:
            logger.error("BackendService.build_stream error for %s: %s", username, e)
            result.update({
                "error": True,
                "error_message": str(e),
                "citations": [],
                "tool_results": [],
            })
            yield f"\n\n⚠️ An error occurred: {e}"
