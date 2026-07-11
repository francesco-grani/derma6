"""Cross-session memory: extraction, denylist filtering, and dedup logic
(capstone-round Bundle 3, Req 9-12).

Split deliberately into pure functions (this module's `filter_denylisted_facts`,
`is_near_duplicate`) and the LLM/DB-calling orchestration (`extract_and_store_facts`,
Task 35) so the business logic is unit-testable without live dependencies (Req 18.1).
"""

import asyncio
import logging
import re

from openai import AsyncOpenAI

from backend.config import settings
from backend.db.deps import get_memory_store
from backend.llm.structured import structured_completion
from backend.rag.embeddings import OpenRouterEmbeddings
from backend.schemas import MemoryExtractionResult

logger = logging.getLogger(__name__)

# Synonyms for the profile fields already tracked on `User`/`ProfileStore`
# (skin type, concerns, facial hair, location, medical flags) — a fact that is
# mostly made of these words duplicates ground the app already captures via its
# dedicated onboarding tools, rather than being genuinely new freeform context.
# Defense-in-depth alongside the prompt-level denylist embedded in the
# extraction system prompt (see extract_and_store_facts, Task 35) — a stray
# extraction that slips past the prompt instruction is caught here instead of
# being persisted.
_PROFILE_OWNED_TERMS: frozenset[str] = frozenset({
    # Skin type (ProfileStore.update_skin_type)
    "skin", "type", "oily", "dry", "dryness", "combination", "sensitive",
    "dehydrated", "acneic", "acne",
    # Skin concerns (ProfileStore.update_skin_concerns)
    "concern", "concerns", "wrinkles", "aging", "ageing", "hyperpigmentation",
    "dark", "spots", "redness", "pores", "blackheads", "blemishes",
    # Facial hair / beard style (ProfileStore.update_beard_style)
    "beard", "shave", "shaves", "shaving", "shaven", "trim", "trims", "trimmed",
    "facial", "hair",
    # Location (ProfileStore.update_location)
    "location", "country", "region", "live", "lives", "living", "based",
    # Medical flags (ProfileStore.add_medical_flag)
    "medical", "diagnosed", "condition", "eczema", "rosacea", "psoriasis",
    "dermatitis", "allergy", "allergic",
})

# Fraction of a candidate fact's significant words that must overlap
# `_PROFILE_OWNED_TERMS` before the fact is dropped as profile-owned territory.
_DENYLIST_OVERLAP_THRESHOLD = 0.5

_WORD_RE = re.compile(r"[A-Za-z']+")


def filter_denylisted_facts(candidate_facts: list[str]) -> list[str]:
    """Drop candidate facts that mostly restate a profile field the app already
    tracks via its dedicated onboarding tools (Req 9.2, 10.2). A fact is dropped
    when the fraction of its words found in `_PROFILE_OWNED_TERMS` is at least
    `_DENYLIST_OVERLAP_THRESHOLD`; empty/word-less facts are dropped outright.

    Pure function: no I/O, no network calls (Req 18.1).
    """
    kept: list[str] = []
    for fact in candidate_facts:
        words = [w.lower() for w in _WORD_RE.findall(fact)]
        if not words:
            continue
        overlap_ratio = sum(1 for w in words if w in _PROFILE_OWNED_TERMS) / len(words)
        if overlap_ratio >= _DENYLIST_OVERLAP_THRESHOLD:
            logger.debug("filter_denylisted_facts dropped %r (overlap=%.2f)", fact, overlap_ratio)
            continue
        kept.append(fact)
    return kept


def is_near_duplicate(cosine_distance: float, similarity_threshold: float) -> bool:
    """A candidate fact is a near-duplicate of an existing one iff their cosine
    similarity (`1 - cosine_distance`) is at or above `similarity_threshold`
    (typically `settings.memory_similarity_threshold`, Req 10.3).

    Pure function: no I/O, no network calls (Req 18.1).
    """
    similarity = 1 - cosine_distance
    return similarity >= similarity_threshold


# ── Orchestration (LLM + DB calling — not pure, see pragma below) ──────────────

_client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url=settings.openrouter_base_url,
)

_embeddings = OpenRouterEmbeddings()

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract freeform, memory-worthy facts a user shared about themselves during "
    "a skincare-assistant conversation, so they can be recalled in future sessions.\n\n"
    "DO NOT extract facts about: skin type (oily/dry/combination/sensitive/dehydrated/"
    "acneic), skin concerns (acne, dryness, dark spots, etc.), facial hair / beard style, "
    "location (country/region), or diagnosed medical skin conditions (eczema, rosacea, "
    "psoriasis, etc.) — these are already captured elsewhere in the user's profile and "
    "must NOT be duplicated here.\n\n"
    "Only extract genuinely new, freeform context that would help a future conversation — "
    "e.g. lifestyle details, preferences, constraints, or history not covered by the "
    "profile fields above. If the conversation contains nothing memory-worthy, return an "
    "empty facts list. Most turns contain nothing worth remembering — do not force an "
    "extraction just to produce output."
)


async def extract_and_store_facts(
    user_id: str, session_id: str, user_message: str, ai_message: str
) -> None:  # pragma: no cover — LLM/DB-calling orchestration; pure helpers above are unit-tested directly
    """Extract memory-worthy facts from one chat turn and persist the novel ones.

    Runs as a fire-and-forget background task after a chat turn completes
    (backend/agent/graph.py, Task 37) — must never block or fail the
    user-visible response (Req 12.1-12.3): every exception here is caught,
    logged, and swallowed rather than propagated.

    Pipeline: resolve the effective extraction model (Req 9.1) → schema-
    constrained extraction via `structured_completion()` with the denylist
    embedded in the system prompt (Req 9.5) → `filter_denylisted_facts()`
    defense-in-depth (Req 9.2, 10.2) → for each surviving fact, embed it and
    skip storing it if it's a near-duplicate of an existing fact for this user
    (Req 10.3), otherwise persist it (Req 9.3, 10.1).
    """
    try:
        model = settings.effective_memory_extraction_model
        result, _used_fallback = await structured_completion(
            _client,
            model=model,
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            user_content=f"User: {user_message}\n\nAssistant: {ai_message}",
            schema_model=MemoryExtractionResult,
        )

        candidate_facts = filter_denylisted_facts(result.facts)
        if not candidate_facts:
            return  # Req 9.4: nothing memory-worthy — nothing stored, no error.

        store = get_memory_store()
        for fact_text in candidate_facts:
            embedding = (
                await asyncio.to_thread(_embeddings.embed_documents, [fact_text])
            )[0]

            nearest = store.find_nearest(user_id, embedding)
            if nearest is not None:
                _existing_fact, distance = nearest
                if is_near_duplicate(distance, settings.memory_similarity_threshold):
                    logger.debug(
                        "extract_and_store_facts: skipping near-duplicate fact for %s: %r",
                        user_id, fact_text,
                    )
                    continue

            store.add_fact(user_id, session_id, fact_text, embedding)
    except Exception as exc:
        logger.error("extract_and_store_facts failed for %s: %s", user_id, exc)
