# Derma6 v2 — Backlog

## Delivered (v2)

- [x] Migrate from Streamlit monolith (v1) to decoupled FastAPI + React architecture
- [x] LangGraph `StateGraph` agent with explicit node/edge topology (prepared for HITL, conditional routing, multi-agent)
- [x] SSE streaming via `StreamingResponse` (`text/event-stream`)
- [x] JWT auth — username + bcrypt, `BaseHTTPMiddleware` + `Depends(get_current_user)` hybrid
- [x] React frontend — Vite + Tailwind + shadcn/ui + TanStack Router + TanStack Query
- [x] Agentic RAG — ChromaDB knowledge base, 10 skincare tools
- [x] Chat session persistence — SQLite, per-user session history
- [x] User profile store — skin type, concerns, flags persisted to SQLite
- [x] LangSmith observability integration
- [x] Skin analysis feature — vision LLM endpoint, condition + confidence + differential diagnoses
- [x] Auto 401 logout — frontend intercepts expired tokens and redirects to login
- [x] Camera modal (`getUserMedia`) in Skin Analysis — `capture="environment"` is mobile-only; replaced with live video stream + canvas snapshot so it works on desktop too
- [x] Test suite — 278 unit tests (45 new for agentic RAG pipeline), 91% coverage on business logic; deepeval evaluation suite (12 LLM-quality tests) with golden dataset at `tests/eval/golden_dataset.json`
- [x] **Agentic RAG pipeline** — `kb_search` upgraded to a 7-node LangGraph `StateGraph`: Query Decomposition → Hybrid Retrieval (HyDE dense + BM25 sparse, RRF merge) → Cross-encoder Reranking → Corrective RAG (CRAG) with local retry before external fallback; `__RAG_PIPELINE_META__` surfaced in SSE metadata event (`rag_routing`, `rag_fallback_triggered`); 11 tunable env vars; `rank-bm25` + `sentence-transformers` dependencies

## Pending

### HITL Features

- [x] **HITL-A: Routine Diff Approval** — agent proposes routine, graph interrupts, user sees before/after diff with approve/rename/cancel options
- [x] **HITL-B: Onboarding Profile Review** — after collecting all 4 onboarding answers, interrupt before `onboarding_complete` is set; user reviews and corrects collected data
- [x] **HITL-C: Medical Flag Double-Confirm** — hard interrupt before writing any medical flag; explicit per-flag confirmation, cannot be overridden by prompt injection
- [x] **HITL-D: Conflict Resolution Decision** — stack conflict detected → interrupt → agent proposes which ingredient to remove; user chooses remove/keep-with-warning per conflict

### Routines

- [x] **Export routine as recurring calendar event** — "Export to Calendar" button per routine in RoutinesPage; user picks a daily/weekly reminder time; generates:
  - A `.ics` file (RFC 5545, `RRULE:FREQ=DAILY`) for Apple Calendar (and any ICS-compatible client)
  - A Google Calendar deep-link URL (`calendar.google.com/calendar/r/eventedit?…`) pre-filled with recurrence
  - Event description contains full routine steps (product name, category label, order)
  - Pure frontend — no backend endpoint needed; built with the native `Blob` + `URL.createObjectURL` pattern

### Infrastructure

- [ ] Conditional routing / multi-agent graph topology
- [ ] Persistent rate limiter — current in-memory limiter resets on restart *(defer to capstone: SQLite `rate_limit_events` table, swap `time.monotonic()` → `time.time()`)*
- [x] Deployment — Hetzner CAX11 (€3.29/mo) + sslip.io SSL; GitHub Actions CI/CD (rsync + docker compose); live at `https://167-233-84-81.sslip.io`

### Admin Features

- [x] **Eval dashboard** — admin UI to trigger deepeval test suite and display results: golden dataset table + metric-level breakdown per test case
- [x] **Cost tracking per user** — log token usage (prompt + completion) per request, aggregate per user, display cost in dollars in admin view
