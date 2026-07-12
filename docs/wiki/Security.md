# Security

**TL;DR** — Derma6 went through a full [deepsec](https://www.npmjs.com/package/deepsec) AI-driven vulnerability scan covering auth, data isolation, prompt-injection surfaces, and CI/CD — 37 findings, all remediated and re-verified via deepsec's revalidation pass down to 0 remaining true positives. The highest-impact fix was an IDOR that let one authenticated user read or hijack another user's chat session; the rest cluster around signup/identity integrity, prompt-injection containment for profile data, and supply-chain hardening. This page is the technical deep-dive; the README has the condensed version.

---

## Session & run ownership (IDOR)

**The finding:** `session_id` and `run_id` are client-supplied on every chat, history, and HITL-resume request. Before remediation, they were trusted at face value — any authenticated user who guessed or observed another user's `session_id`/`run_id` could read that user's conversation, or resume their in-flight HITL interrupt and have the result appended to their history.

**The fix:**
- `_require_session_owner()` (`backend/api/chat.py`) resolves `session_id` against `SessionStore.get_session_owner()` before any read or write in `/api/chat` and `/api/me/chat/history`.
- `/api/chat/resume` (`backend/api/hitl.py`) checks **both** `run_id` ownership (via `get_run_owner()`, which reads the `user_id` stamped into the LangGraph checkpoint's config metadata at graph-invocation time — not a client-supplied value) and `session_id` ownership separately. Both checks are necessary: a caller with a legitimately-owned `run_id` could otherwise still name a foreign `session_id` and have the resumed answer appended to someone else's chat history.
- Every ownership failure returns **404, not 403** — deliberately, so a caller can't use the response code to distinguish "doesn't exist" from "belongs to someone else" and enumerate valid ids.

---

## Client-side cache isolation

**The finding:** React Query caches server responses client-side, keyed by query, not by user. On a fast account switch (or any sign-out that didn't route through the app's own logout button — e.g. Supabase detecting an invalid refresh token in another tab), a previous user's cached profile/routines/session data could still render briefly for the next signed-in identity.

**The fix:** `logout()` synchronously clears the React Query cache, resets session state, and clears the session-storage keys used for active-session tracking, *before* calling `supabase.auth.signOut()`. Supabase's own `onAuthStateChange` listener performs the identical clear as a backstop, catching sign-outs that don't go through the app's `logout()` at all.

---

## Signup provisioning integrity

**The finding:** the old locally-issued auth stack let signup trust client-supplied identity fields. Migrating to Supabase Auth removed the vector, but the provisioning endpoint (creating the local `users` row on first login) needed to not reintroduce it.

**The fix:** `POST /api/auth/complete-signup` trusts nothing from the request body — it derives `user_id` (`sub`), `email`, and `username` (`user_metadata.username`) entirely from the already-JWT-verified `request.state`. It's also not a public route: Supabase's "Confirm email" setting means `signUp()` never returns a session, so this can only ever run on a subsequent authenticated request, not at signup time itself. It's idempotent — `get_or_create_user_by_id()` — so calling it on every login is safe.

---

## Prompt-injection containment for profile data

**The finding:** free-text profile fields (location, skin concerns) flow into the agent's system prompt so the LLM can reference them. Regex-based jailbreak detection on write is one layer, but it's inherently incomplete — a sufficiently creative phrasing can slip past any fixed pattern list, and once it's in the prompt in plain interpolated text, the model may read it as an instruction rather than data.

**The fix — defense in depth, two layers:**
1. **Write-time filtering:** `backend/security_patterns.py` exports a single `JAILBREAK_PATTERN` regex, imported by both `backend/middleware/content_filter.py` (chat input) and `backend/schemas.py` (`ProfilePatch` field validators) — one source of truth, no import-cycle duplication.
2. **Read-time containment (the more important layer):** all profile data reaching the system prompt is serialized into one `PROFILE_DATA` block via `json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))` and injected as a single labeled block, rather than interpolated field-by-field into prose. The containment mechanism is `json.dumps`'s own string escaping — quotes, backslashes, and (via `ensure_ascii=True`) even Unicode line-separator characters (`U+2028`/`U+2029`) that could otherwise break a naive "put it on its own line" containment scheme. No phrasing inside a JSON string value can be read as a prompt instruction, independent of whether it happens to match a regex.

---

## JWKS rotation correctness

**The finding:** JWT verification against Supabase's JWKS endpoint needs a signing-key cache (to avoid a network round-trip per request), but a naive cache can go wrong in two ways: merging new keys into the old set means a revoked key stays trusted until the process restarts, and refreshing on every unknown `kid` is a denial-of-service vector (an attacker can force unbounded refreshes with garbage `kid`s).

**The fix (`backend/auth.py`):**
- The cache is **replaced wholesale**, never merged, on every refresh — a revoked key disappears from the trusted set as soon as the next refresh happens, not "eventually."
- Refresh attempts are throttled to once per 30 seconds regardless of how many unknown-`kid` lookups arrive in that window.
- A hard **300-second max cache age** forces a refresh even on a cache *hit*, so a revoked key can't stay trusted indefinitely just because no unknown `kid` ever happens to trigger a miss.
- JWKS/ES256 is confirmed the only actually-active signing scheme for the live deployment (verified against the project's real settings); the HS256 shared-secret path exists as a fallback but is inactive.

---

## Routine name uniqueness

**The finding:** routine names were only checked for collisions app-side, in `ProfileStore`. Any write path that bypassed `ProfileStore` (a future admin tool, a script, a bug) could create two routines with the same name for one user, which the frontend's rename/save UX doesn't handle.

**The fix — two layers:** `ProfileStore._find_colliding_routine()` does a case-insensitive check (`func.lower(name) == name.lower()`) used by both `save_routine()` and `rename_routine()`; a `UniqueConstraint(user_id, name)` on the `routines` table backstops it at the database level for exact-case collisions from any other write path. A collision surfaces as a structured `409`, not a generic `500`, so the frontend can show a specific "name already in use" message.

---

## CI/CD & container hardening

- **Every third-party GitHub Action is pinned to a commit SHA**, not a mutable version tag (`actions/checkout`, `actions/setup-node`, `actions/setup-python`, `astral-sh/setup-uv`) — a compromised or re-tagged upstream release can't silently change what CI runs.
- **SSH host key pinning, not trust-on-first-use:** the deploy workflow does not `ssh-keyscan` the target host at deploy time (spoofable by anyone who can race the first connection) — the host key is captured out-of-band and hardcoded into the workflow, with `HostKeyAlgorithms` pinned and `StrictHostKeyChecking yes` set so the connection can't be downgraded to an unpinned key type.
- **Non-root container:** the Docker image creates a dedicated `app` user/group, `chown`s the data/log directories to it, and runs the app as that user — not root — inside the container.

---

## Baseline protections (unrelated to the deepsec pass)

- Input capped at 2000 characters (`MAX_MESSAGE_CHARS`)
- Per-user rate limiting on both chat and the vision-analysis endpoint (in-memory; see [Roadmap](../../README.md#roadmap) for the persistence gap)
- Output PII scrubbing before chat history is persisted (email/phone/SSN patterns) — see [Architecture — Content filter](Architecture.md#content-filter)
- `BaseHTTPMiddleware`-based JWT verification is safe for SSE responses specifically because it never reads the response body
