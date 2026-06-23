"""Content filtering for incoming chat messages and outgoing LLM responses.

Input guardrails (FastAPI dependency `check_chat_content`):
  - Jailbreak / prompt-injection patterns
  - PII detected in the user's message (email, phone, credit card, SSN)

Output guardrails (utility `scrub_pii_output`):
  - PII replacement in the assembled answer before it is stored in chat history.
  - The streamed text has already reached the client, so scrubbing applies only
    to what is persisted; this prevents PII from surfacing in history retrieval.

Usage:
  Input  → Depends(check_chat_content) on the /api/chat route
  Output → scrub_pii_output(answer) in graph.py before chat_history.add_ai_message()
"""

import logging
import re

from fastapi import HTTPException

from backend.schemas import ChatRequest

logger = logging.getLogger(__name__)

# ── Jailbreak / prompt-injection detection ────────────────────────────────────

_JAILBREAK = re.compile(
    r"ignore\s+(previous|all|above|prior|your|these)\s+(instructions?|prompts?|rules?|constraints?)"
    r"|you\s+are\s+now\s+(a\b|an\b|the\b|my\b|no\s+longer)"
    r"|(forget|disregard|override|bypass|violate)\s+(your|all|the|previous|any)\s+"
    r"(instructions?|rules?|training|constraints?|guidelines?|programming)"
    r"|act\s+as\s+if\s+you\s+(are|were)"
    r"|\bdan\s+mode\b|\bdo\s+anything\s+now\b|\bjailbreak\b"
    r"|<\s*/?system\s*>"
    r"|system\s*:\s*\S"
    r"|(new|different|another)\s+(persona|personality|identity)"
    r"|(switch|change|adopt)\s+(your\s+)?(persona|personality|role)"
    r"|you\s+have\s+no\s+(restrictions?|limits?|guidelines?|rules?|constraints?|filters?)"
    r"|(disable|remove|turn\s+off|bypass)\s+(your\s+)?(safety|filters?|restrictions?|guardrails?|moderation)"
    r"|\bprompt\s+injection\b",
    re.IGNORECASE,
)

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

async def check_chat_content(req: ChatRequest) -> None:
    """Raise HTTP 400 if the message contains jailbreak attempts or PII."""
    message = req.message

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


# ── Output PII scrubber ───────────────────────────────────────────────────────

def scrub_pii_output(text: str) -> str:
    """Replace PII patterns in LLM output before storing in chat history."""
    for pattern, replacement in _PII_OUTPUT_SUBS:
        if pattern.search(text):
            logger.warning("content_filter: PII found in LLM output — scrubbing before storage")
            text = pattern.sub(replacement, text)
    return text
