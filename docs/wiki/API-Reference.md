# API Reference

**TL;DR** — Base URL `http://localhost:8000`, interactive docs at `/docs`. Every route requires `Authorization: Bearer <supabase-jwt>` except `/health`, `/docs`, `/openapi.json`, and `/redoc`. There's no `/auth/login` or `/auth/register` any more — Supabase issues and refreshes sessions directly from the frontend; the backend only verifies the JWT and provisions a local user row on first authenticated request. All per-user routes are ownership-checked server-side (404, not 403, on a foreign-owned resource — see [Security](Security.md)).

---

## Auth

### `POST /api/auth/complete-signup`

Provisions the local `users` row from a **verified** Supabase JWT — not from the request body, which carries nothing. Idempotent; safe to call on every login. Runs on the user's first authenticated request after email verification (Supabase's "Confirm email" setting means `signUp()` itself never returns a session to call this from).

**Identity source:** JWT claims — `sub` (user id), `email`, `user_metadata.username`.

**Response `201`:**
```json
{ "user_id": "<supabase-uuid>", "username": "alice" }
```

**Response `409`** if the email is already registered to a different local row.

---

## Chat

### `POST /api/chat`

Stream one agent turn as SSE (`text/event-stream`). Runs the content filter (jailbreak + PII regex) before invoking the agent, and 404s if `session_id` doesn't belong to the caller.

**Body:**
```json
{ "message": "What moisturiser should I use?", "session_id": "<uuid>" }
```

**SSE `data` shapes** (see [Architecture — SSE event types](Architecture.md#sse-event-types) for the full reference):

| `type` | Meaning |
|---|---|
| `text` | One LLM output token |
| `clear_text` | Agent is re-running after a tool call; reset the message bubble |
| `interrupt` | A HITL tool paused the graph — `{run_id, kind, title, options, preview}` |
| `metadata` | End of turn — `{citations, rag_context, tool_results, rag_routing, rag_fallback_triggered}` |
| `session_title` | First message in a session — sidebar title update |
| `error` | Exception or rate limit hit |
| _(terminal)_ | `data: [DONE]` |

---

### `POST /api/chat/resume`

Resume a graph suspended by a HITL tool's `interrupt()`. Requires **both** `run_id` and `session_id` to belong to the caller — a valid `run_id` with a foreign `session_id` is rejected too, since a resumed answer is appended to whichever session it names.

**Body:**
```json
{ "session_id": "<uuid>", "run_id": "<uuid>", "choice": "confirm", "note": "" }
```

`choice` is tool-defined (`"confirm" | "rename" | "cancel"` for most cards). Streams the same SSE shapes as `/api/chat`.

---

### `GET /api/me/chat/history?session_id=<uuid>`

Persisted history for a session (ownership-checked).

**Response `200`:**
```json
[
  { "role": "user", "content": "..." },
  { "role": "assistant", "content": "..." }
]
```

---

## Sessions

### `GET /api/me/sessions`

List the caller's chat sessions.

### `POST /api/me/sessions`

Create a new (empty, untitled) session. **Response `201`** with the created `ChatSessionInfo`. The frontend always creates a session up front, before the first chat message references it.

### `DELETE /api/me/sessions/{session_id}`

Delete a session and its history. `404` if not owned by the caller.

---

## Profile

### `GET /api/me/profile`

Full `UserProfile` — skin type, concerns, medical flags, beard style, location, onboarding status.

### `PATCH /api/me/profile`

Atomic partial update — applied in a single transaction, no partial writes on validation failure.

**Body** (any subset):
```json
{ "skin_type": "combination", "beard_style": "trim", "location": "...", "skin_concerns": ["acne", "redness"] }
```

`skin_type` is enum-constrained (`oily | dry | combination | sensitive | dehydrated | acneic`); `location`/free-text fields are checked against the shared jailbreak-pattern regex. **`422`** on an invalid `beard_style` or jailbreak-pattern match.

---

## Routines

### `GET /api/me/routines`

List all saved routines (`RoutineSchema[]`).

### `DELETE /api/me/routines/{name}`

Delete a routine by name.

### `PATCH /api/me/routines/{name}`

Rename a routine.

**Body:** `{ "new_name": "Weekend AM" }`

**Response `409`** on a case-insensitive name collision with another existing routine (enforced both app-side and by a DB unique constraint).

---

## Skin Analysis

### `POST /api/me/analyze-skin`

Upload a photo for one-shot vision analysis (not agentic — no LangGraph tool calls). Behind a dedicated per-user rate limit and a 10 MB size cap (rejected pre-read where possible).

**Body:** `multipart/form-data` — field `file` (`image/jpeg`, `image/png`, or `image/webp`).

**Response `200`** (`SkinAnalysisResult`):
```json
{
  "condition": "Mild acne",
  "confidence": 0.72,
  "alternatives": [{ "condition": "Folliculitis", "probability": "18.0%" }],
  "reasoning": "...",
  "disclaimer": "This is an AI screening tool for educational purposes only. ..."
}
```

Persists a `skin_analyses` row (full image + 256px thumbnail) as a side effect. `413` if oversized, `415` if not an allowed type, `502` if the vision model call or its structured-output parsing fails.

### `GET /api/me/skin-analyses`

List the caller's saved analyses, oldest first (each including both images as base64).

### `DELETE /api/me/skin-analyses/{analysis_id}`

Delete one saved analysis. `404` if not owned by the caller.

### `POST /api/me/medical-flags`

Save a medical flag directly from the analysis page (distinct from the `add_medical_flag_tool` HITL path in chat — this one is a direct write, no confirmation card).

**Body:** `{ "condition": "Rosacea" }`

---

## Export

### `GET /api/me/export?format=html|pdf`

Generate a skincare-plan export (profile + routines + latest session). Returns `text/html` or `application/pdf` (rendered via WeasyPrint/xhtml2pdf) as a file download, named from the caller's display username.

---

## Admin

All routes below require `role`-equivalent `is_admin = true` on the caller's `users` row (`403` otherwise).

### `GET /api/admin/users`

List all users with aggregated token usage and cost (`UserSummary[]`).

### `GET /api/admin/eval/golden`

Return the deepeval golden dataset (`eval/golden_dataset.json`) as-is.

### `GET /api/admin/eval/status`

Current eval run status (`idle | running`), progress, and results if completed.

### `POST /api/admin/eval/run`

Kick off the deepeval suite as a background task. **`202`** on accept, **`409`** if a run is already in progress (status flip happens synchronously before the background task is scheduled, so two near-simultaneous requests can't both start a run).

### `POST /api/admin/eval/export/html`

Render the current eval results as a downloadable HTML report.

---

## Health

### `GET /health`

Always `{ "status": "ok" }`. No auth required — the only route besides `/docs`/`/openapi.json`/`/redoc` that isn't.
