# Cross-Session Memory

**TL;DR** — after every chat turn, a fire-and-forget background task asks an LLM to extract freeform facts worth remembering ("travels for work often", "prefers fragrance-free products"), drops anything that overlaps a field the structured profile already tracks, embeds and dedups what's left against the user's existing facts, and stores the rest in Postgres (`pgvector`). On later turns, the incoming message is embedded and the nearest facts for that user are pulled into the system prompt. Every step is fail-open — a failure here never blocks or fails the chat response.

---

## Why a separate system from the profile

Derma6 already has a structured profile (`skin_type`, `skin_concerns`, `beard_style`, `location`, `medical_flags`) captured deliberately through onboarding and HITL confirmation tools. Cross-session memory exists for everything *outside* that — lifestyle details, preferences, and context a user mentions in passing that would help a future conversation but doesn't fit a defined field. It is not a second, looser way to capture the same profile data; see [Denylisting against the profile](#denylisting-against-the-profile) below for how that boundary is enforced.

---

## Pipeline

```
chat turn completes
      │
      ▼ (fire-and-forget, does not block the response)
extract_and_store_facts(user_id, session_id, user_message, ai_message)
      │
      ▼
structured_completion() ──► MemoryExtractionResult { facts: list[str] }
      │  system prompt embeds a denylist: do NOT extract skin type, concerns,
      │  facial hair, location, or medical conditions — profile already owns those
      ▼
filter_denylisted_facts() ──► drops any fact whose words are ≥50% profile-owned
      │  (defense-in-depth: catches what slips past the prompt-level instruction)
      ▼
for each surviving fact:
      embed → find_nearest(user_id, embedding) → cosine similarity ≥ threshold?
                                                      │
                                     yes ─── skip (near-duplicate)
                                      no ─── add_fact() — persist
```

Retrieval, on a later turn:

```
incoming user message
      │
      ▼
embed_query(message) ──► search_facts(user_id, embedding, top_k=5)
      │  filtered by user_id first — cosine distance computed over one
      │  user's facts, never the whole table
      ▼
top-K facts rendered into the system prompt under
"ADDITIONAL CONTEXT FROM PAST CONVERSATIONS", each sanitised
```

Both extraction and retrieval are wrapped in broad `try/except` blocks that log and continue — a failure degrades to "no facts extracted" or "no facts retrieved," never a blocked or failed chat turn.

---

## Denylisting against the profile

Two independent layers keep memory facts from duplicating structured profile data:

1. **Prompt-level instruction** — the extraction system prompt explicitly lists the categories to *not* extract (skin type, concerns, facial hair/beard style, location, diagnosed medical conditions) because "these are already captured elsewhere in the user's profile."
2. **Word-overlap filter** (`filter_denylisted_facts()`, pure function, unit-tested without any live dependency) — a fixed set of profile-owned terms (`oily`, `combination`, `beard`, `rosacea`, `location`, ...) is checked against each candidate fact's words. If **50% or more** of a fact's significant words are in that set, it's dropped before it's ever embedded or stored. This is defense-in-depth: the LLM won't always perfectly follow the prompt instruction, so a stray extraction that slips through is caught here instead of being persisted.

---

## Deduplication

Before a surviving fact is stored, it's embedded and compared against the user's existing facts via `MemoryStore.find_nearest()` — the single nearest neighbor by cosine distance, filtered to that user only. If `1 - distance ≥ MEMORY_SIMILARITY_THRESHOLD` (default **0.92**), the candidate is treated as a near-duplicate and silently skipped rather than stored again. There's no batch/offline reconciliation — dedup only ever runs against what's already there at write time.

---

## Storage: `user_memory_facts`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `user_id` | TEXT | FK → `users`, `ON DELETE CASCADE` |
| `fact_text` | TEXT | |
| `embedding` | `vector(4096)` | Width matches `qwen/qwen3-embedding-8b`, confirmed empirically |
| `source_session_id` | TEXT, nullable | FK → `chat_sessions`, `ON DELETE SET NULL` — a fact outlives the session it came from |
| `created_at` | TIMESTAMP | |

### The pgvector dimension caveat

`pgvector`'s HNSW and ivfflat index types both cap out at **2000 dimensions**. `qwen/qwen3-embedding-8b` produces **4096-dimensional** vectors — confirmed empirically against the live OpenRouter API, not assumed — so `CREATE INDEX ... USING hnsw` on this column fails outright at this width. There is deliberately **no ANN index** on `embedding`.

This is not a practical problem at current scale: every query filters by `user_id` first (`WHERE user_id = ...` before the cosine-distance `ORDER BY`), so the scan is over one user's handful of facts, not the whole table. It becomes worth revisiting only if per-user fact counts grow large enough for that per-user scan to matter — at which point a `halfvec`-typed index (supports higher dimensionality at reduced precision) is the documented next step, not re-architecting the storage.

**If `EMBEDDING_MODEL` ever changes:** the vector width is a migration-time constant (`MEMORY_EMBEDDING_DIM` in `backend/db/models.py`), not derived from config at runtime. Changing the embedding model requires a new Alembic migration to alter the column width, plus a full re-embed/backfill of existing facts — not just an env var change.

---

## Configuration reference

| Environment variable | Default | Effect |
|---|---|---|
| `MEMORY_EXTRACTION_MODEL` | _(unset)_ | Model used for fact extraction; falls back to `LLM_MODEL` (the same model driving live chat) when unset |
| `MEMORY_SIMILARITY_THRESHOLD` | `0.92` | Cosine similarity at or above which a candidate fact is treated as a duplicate and skipped |
| `MEMORY_RETRIEVAL_TOP_K` | `5` | Number of nearest facts pulled into the system prompt per turn |

---

## Isolation and safety properties

- **Per-user isolation** — every `MemoryStore` query filters by `user_id` first; there is no code path that retrieves or deduplicates across users.
- **Fail-open by design** — extraction and retrieval failures are caught, logged, and swallowed. A broken embeddings call or a down LLM degrades memory to "off" for that turn, never to a blocked chat response.
- **Sanitised at render time** — each fact is passed through the same `_sanitise()` prompt-injection defense as other dynamic content before being interpolated into the system prompt (see [Security — Prompt-injection containment](Security.md#prompt-injection-containment-for-profile-data) for the pattern this follows).
