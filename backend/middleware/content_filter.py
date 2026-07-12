"""Content filtering for incoming chat messages and outgoing LLM responses.

Input guardrails (FastAPI dependencies `check_chat_content`, `check_resume_content`):
  - Jailbreak / prompt-injection patterns
  - PII detected in the user's message (email, phone, credit card, SSN)

Output guardrails (utility `scrub_pii_output`):
  - PII replacement in the assembled answer before it is stored in chat history.
  - The streamed text has already reached the client, so scrubbing applies only
    to what is persisted; this prevents PII from surfacing in history retrieval.

Usage:
  Input  → Depends(check_chat_content) on the /api/chat route
         → Depends(check_resume_content) on the /api/chat/resume route
           (security-remediation Req 19.5 — the resume path's freeform `note`
           field is a second user-controlled input channel into the agent and
           must be filtered the same way `message` is)
  Output → scrub_pii_output(answer) in graph.py before chat_history.add_ai_message()
"""

import logging
import re

from fastapi import HTTPException

from backend.schemas import ChatRequest, ResumeRequest
from backend.security_patterns import JAILBREAK_PATTERN as _JAILBREAK

logger = logging.getLogger(__name__)

# ── PII patterns (input) ──────────────────────────────────────────────────────
# Ordered from most to least specific to avoid shadowing.

_PII_INPUT: list[tuple[str, re.Pattern[str]]] = [
    (
        "credit card number",
        re.compile(
            r"\b(?:4[0-9]{12}(?:[0-9]{3})?|"       # Visa
            r"[25][1-7][0-9]{14}|"                   # Mastercard
            r"3[47][0-9]{13}|"                       # Amex
            r"3(?:0[0-5]|[68][0-9])[0-9]{11}|"      # Diners
            r"6(?:011|5[0-9]{2})[0-9]{12})\b"        # Discover
        ),
    ),
    (
        "SSN",
        re.compile(
            r"\b(?!000|666|9\d\d)\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b"
        ),
    ),
    (
        "email address",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "phone number",
        re.compile(
            r"\b(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b"
        ),
    ),
]

# ── PII patterns (output scrubbing) ──────────────────────────────────────────

_PII_OUTPUT_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[email]"),
    (
        re.compile(r"\b(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b"),
        "[phone]",
    ),
    (
        re.compile(
            r"\b(?!000|666|9\d\d)\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}\b"
        ),
        "[ssn]",
    ),
]


# ── FastAPI dependency ────────────────────────────────────────────────────────

def _check_content(message: str) -> None:
    """Raise HTTP 400 if `message` contains jailbreak attempts or PII.

    Shared by check_chat_content (message) and check_resume_content (note) —
    both are free-text, user-controlled strings that reach the same agent/LLM
    boundary, so they get the same guardrail (security-remediation Req 19.5).
    """
    if _JAILBREAK.search(message):
        logger.warning("content_filter: jailbreak attempt blocked")
        raise HTTPException(
            status_code=400,
            detail="Message blocked: potential prompt injection detected.",
        )

    for pii_type, pattern in _PII_INPUT:
        if pattern.search(message):
            logger.info("content_filter: PII (%s) detected in input", pii_type)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Please don't share personal information like a {pii_type} here. "
                    "Just describe your skincare question and I'll help!"
                ),
            )


async def check_chat_content(req: ChatRequest) -> None:
    """Raise HTTP 400 if the message contains jailbreak attempts or PII."""
    _check_content(req.message)


async def check_resume_content(req: ResumeRequest) -> None:
    """Raise HTTP 400 if a HITL resume's freeform `note` contains jailbreak
    attempts or PII (security-remediation Req 19.5). `note` defaults to ""
    (schemas.ResumeRequest), which never matches either pattern set, so
    interrupt kinds that don't use a note are unaffected."""
    _check_content(req.note)


# ── Output PII scrubber ───────────────────────────────────────────────────────

def scrub_pii_output(text: str) -> str:
    """Replace PII patterns in LLM output before storing in chat history."""
    for pattern, replacement in _PII_OUTPUT_SUBS:
        if pattern.search(text):
            logger.warning("content_filter: PII found in LLM output — scrubbing before storage")
            text = pattern.sub(replacement, text)
    return text
