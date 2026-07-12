"""Shared regex patterns for detecting prompt-injection / jailbreak phrases.

Single source of truth for both `backend.middleware.content_filter` (chat/
resume message filtering) and `backend.schemas` (profile free-text field
validation, security-remediation Req 23.3) — kept in its own module rather
than in either consumer to avoid a schemas.py <-> content_filter.py import
cycle (content_filter.py already imports request schemas from schemas.py).
"""

import re

JAILBREAK_PATTERN = re.compile(
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
