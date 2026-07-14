<p align="center">
  <img src="frontend/src/assets/hero.png" width="140" alt="Derma6"/>
</p>

<p align="center">
  <strong>Derma6 v3</strong> — AI skincare assistant for male beginners.
  Diagnose your skin type · Build a personalised routine · Catch ingredient conflicts · Schedule active introductions · Find where to buy.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+"/>
  <img src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React 19"/>
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/ChromaDB-vector%20store-F97316" alt="ChromaDB"/>
  <img src="https://img.shields.io/badge/uv-package%20manager-7C3AED" alt="uv"/>
</p>

<p align="center">
  <strong>Live:</strong> <a href="https://167-233-84-81.sslip.io/">https://167-233-84-81.sslip.io/</a>
</p>

---

## Version history

Three iterations, each a separate project milestone: **v1** (Streamlit prototype) → **v2** (decoupled FastAPI + React rebuild) → **v3**, this version (Capstone round — agentic RAG, Supabase, security hardening).

### v1 → v2 — Streamlit monolith → decoupled architecture

Same skincare domain, same 10 core behaviours — production-grade stack:

| | v1 | v2 |
|---|---|---|
| **Frontend** | Streamlit | React 19 + Vite + Tailwind + shadcn/ui |
| **Routing** | Streamlit pages | TanStack Router (type-safe) |
| **Data fetching** | Direct Python calls | TanStack Query |
| **Backend** | Streamlit in-process | FastAPI + uvicorn |
| **Auth** | Session state | JWT (bcrypt + `python-jose`) |
| **Agent** | `create_react_agent` | Explicit `StateGraph` |
| **Streaming** | `st.write_stream` | SSE (`StreamingResponse`) |
| **Observability** | None | LangSmith tracing |
| **Sessions** | Single conversation | Multi-session with history |
| **Skin analysis** | None | Vision LLM (photo upload → skin advice) |

### v2 → v3 — agentic RAG, Supabase, structured output, memory (Capstone round)

| | v2 | v3 |
|---|---|---|
| **Retrieval** | Single-shot ChromaDB top-K | 7-node agentic RAG — HyDE + BM25 hybrid retrieval, cross-encoder rerank, CRAG self-correction, web fallback |
| **HITL** | None | 6 tools pause the graph via `interrupt()` for user confirmation before any write |
| **Auth** | Custom JWT (username + bcrypt) | Supabase Auth — email/password, UUID identity, JWKS (ES256) verification |
| **Persistence** | SQLite | Supabase-managed Postgres via Alembic migrations |
| **HITL checkpointer** | — | LangGraph `AsyncPostgresSaver` — interrupted runs survive a restart and resume from any instance |
| **Tool arguments** | Delimited strings, manually parsed | Schema-enforced structured output — nested Pydantic models, `Literal` enums, typed lists |
| **Vision analysis parsing** | Manual `json.loads()` | `structured_completion()` — OpenAI strict-mode JSON schema with a prompt-based fallback |
| **Conversation memory** | Per-session only | Cross-session — freeform facts extracted after each turn, deduped by cosine similarity, recalled into future system prompts |
| **Evaluation** | None | deepeval suite — 28 tests across 7 categories, admin-dashboard visible |
| **Security posture** | Ad hoc | Full AI-driven vulnerability scan, all findings remediated — see [Security](#security) |
| **Deployment** | Local only | Hetzner VPS, Docker Compose + Caddy, GitHub Actions CI/CD |

---

## Features

| | Feature | Description |
|---|---|---|
| 💬 | **Chat** | Streaming conversation with the skincare agent, organised into named sessions |
| 🔬 | **Skin analysis** | Upload a photo — a vision LLM analyses your skin and feeds findings into the agent |
| 🧴 | **Routine builder** | Generates AM/PM routines sequenced by application order, conflict-aware |
| 🛒 | **Product finder** | One-click lookup next to a routine step — real retail *and* secondhand listings (price, source, link-out), from location-aware LLM-discovered sources |
| ⚠️ | **Ingredient conflict checker** | Cross-references products against a compatibility matrix (e.g. Retinol + Salicylic Acid) |
| 📅 | **Active scheduling** | Gradual introduction plan for strong actives to minimise irritation |
| 👤 | **Skin profile** | Persistent profile — skin type, concerns, medical flags, shaving routine |
| 📚 | **Focused KB** | 20 documents on skincare actives: Paula's Choice, INCI Decoder, PubMed, r/SkincareAddiction |
| 📤 | **Export** | Download full skincare plan (profile + routines + chat) as HTML or PDF |
| 🔐 | **Auth** | Supabase Auth (email/password) — JWKS-verified sessions, per-user data isolation enforced end-to-end |
| 🧠 | **Cross-session memory** | Freeform facts from past conversations are extracted, deduped, and recalled in later chats |
| 🔭 | **LangSmith** | Full agent trace per chat turn when `LANGSMITH_API_KEY` is set |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12, FastAPI 0.115+, uvicorn |
| **Agent** | LangGraph `StateGraph`, LangChain tools |
| **Frontend** | React 19, Vite 8, Tailwind 4, shadcn/ui |
| **Routing** | TanStack Router (type-safe file routes) |
| **Data fetching** | TanStack Query |
| **LLM** | OpenRouter — `anthropic/claude-haiku-4.5` (agent), `google/gemini-2.5-flash` (vision) |
| **Structured output** | Pydantic v2 → OpenAI strict-mode JSON schema (`backend/llm/structured.py`), prompt-based fallback |
| **Embeddings** | OpenRouter — `qwen/qwen3-embedding-8b` |
| **Web search** | Tavily (preferred) → DuckDuckGo (fallback) — RAG external fallback + product-finder domain-scoped search |
| **Product sourcing** | `vinted-api-wrapper` (secondhand), BeautifulSoup/lxml (retail page + Kleinanzeigen scraping) |
| **Vector store** | ChromaDB (KB), `pgvector` (cross-session memory facts) |
| **Relational store** | Postgres (Supabase-managed) + SQLAlchemy 2.x + Alembic migrations |
| **HITL persistence** | LangGraph `AsyncPostgresSaver` — interrupted runs survive restarts |
| **Auth** | Supabase Auth — JWKS (ES256) verification, HS256 fallback |
| **Observability** | LangSmith (optional), structured JSON logging, Sentry (optional) |
| **Package manager** | uv (Python), npm (frontend) |

---

## Architecture

```
Browser (React)
    │  HTTP / SSE  (Authorization: Bearer <Supabase JWT>)
    ▼
FastAPI  ──►  JWTAuthMiddleware (verifies against Supabase JWKS)
    ├── POST /api/auth/complete-signup   ──►  provisions the local user row
    ├── POST /api/chat                   ──►  SSE token stream
    ├── POST /api/chat/resume            ──►  resumes an interrupted HITL run
    ├── GET  /api/me/profile · PATCH
    ├── GET  /api/me/routines · PATCH · DELETE
    ├── GET  /api/me/sessions · POST · DELETE
    ├── POST /api/me/analyze-skin
    ├── GET  /api/me/export
    ├── GET  /api/products/find          ──►  product finder (standalone, not an agent tool)
    │        └── source discovery (LLM) → Vinted · retail · secondhand · Kleinanzeigen (SSE stages)
    └── GET  /api/admin/*                ──►  admin-only (users, eval dashboard)
    │
    ▼
LangGraph StateGraph (explicit ReAct loop)
    ├── llm_node   ──►  OpenRouter (claude-haiku-4.5)
    └── tool_node  ──►  13 tools (7 domain + 6 HITL)
    │
    ├── Domain tools ──────────────────────────────────────────
    │   ├── kb_search               agentic RAG pipeline (7-node sub-graph)
    │   ├── conflict_checker        JSON conflict matrix (deterministic)
    │   ├── routine_sequencer       Application-order sorting
    │   ├── skin_type_advisor_tool  Type classification from KB + chat
    │   ├── introduction_scheduler_tool  Gradual actives plan
    │   ├── update_skin_concerns_tool    Direct profile write
    │   └── spf_recommender         SPF matching to skin profile
    │
    ├── HITL tools (interrupt() before writing) ───────────────
    │   └── save_routine · update_beard_style · update_location ·
    │       add_medical_flag · finalize_onboarding · propose_conflict_resolution
    │
    ├── Postgres (Supabase-managed) ────────────────────────────
    │   ├── users, routines, routine_steps, chat_sessions,
    │   │   introduction_plans, skin_analyses, user_memory_facts (pgvector)
    │   ├── message_store              (LangChain chat history)
    │   └── LangGraph checkpoint tables (AsyncPostgresSaver — HITL resume state)
    │
    └── ChromaDB ───────────────────────────────────────────────
        └── 20-doc KB (1000-char chunks, 150-char overlap)
```

The agent runs as an explicit `StateGraph` (not `create_react_agent`). This was a deliberate choice over the prebuilt helper — see [ADR-0001](docs/adr/0001-explicit-stategraph-over-create-react-agent.md).

### Security

Derma6 went through a full AI-driven vulnerability scan of the codebase using [deepsec](https://www.npmjs.com/package/deepsec) — 37 findings across auth, data isolation, prompt-injection surfaces, and CI/CD, all remediated and re-verified via a revalidation pass down to 0 remaining true positives. See [docs/wiki/Security.md](docs/wiki/Security.md) for the full technical write-up; highlights:

- **Session & run ownership** — `session_id`/`run_id` are resolved against their owning user before any chat read/write or HITL resume, closing an IDOR that let one authenticated user read or hijack another user's conversation
- **Client-side cache isolation** — React Query keys are scoped by user id; logout and Supabase's `onAuthStateChange` both synchronously clear the query cache and session storage, closing a cross-account data leak on fast account switches
- **Signup provisioning integrity** — the local user row is provisioned only from a verified Supabase JWT's claims, never from client-supplied values
- **Prompt-injection containment** — all profile data reaching the system prompt is wrapped in a single `json.dumps`-escaped `PROFILE_DATA` block, so no phrasing in a free-text field can be read as an instruction; a shared jailbreak-pattern regex additionally validates free-text profile fields and chat input
- **JWKS rotation correctness** — the signing-key cache is replaced wholesale (never merged) on refresh, with a bounded TTL so a revoked key can't stay trusted indefinitely
- **CI/CD & container hardening** — GitHub Actions pinned to commit SHAs, SSH host key pinned and verified out-of-band (no trust-on-first-use), container runs as a non-root user

Plus the baseline protections:
- Input capped at 2000 characters (`MAX_MESSAGE_CHARS`)
- Jailbreak detection + input/output PII filtering on every chat turn (see [Content filter](#content-filter) below)
- Supabase-issued sessions with automatic refresh; auto-logout on 401 in the frontend
- Per-user rate limiting: 10 requests / 60 s (in-memory; resets on restart — see [Roadmap](#roadmap))
- Medical flags trigger a `⚠️ Consult a dermatologist` notice only on specific recommendations
- `BaseHTTPMiddleware` safe for SSE because it never reads the response body

### Content filter

`backend/middleware/content_filter.py` runs as a FastAPI `Depends` before the agent on every `/api/chat` and `/api/chat/resume` request:

- **Jailbreak detection** — regex patterns for `ignore previous instructions`, `DAN mode`, `act as if you are`, persona-switch phrases, and similar injection patterns; returns HTTP 400 on match
- **Input PII detection** — blocks email addresses, phone numbers, credit card numbers, and SSNs with a user-friendly error message
- **Output PII scrubbing** — after the agent streams, `scrub_pii_output()` replaces any PII patterns in the assembled answer *before* it is persisted to chat history (the streamed text is already at the client; scrubbing is storage-only)

### HITL (Human-in-the-Loop)

Several agent tools use LangGraph's `interrupt()` to pause the graph and wait for a user decision before performing any write. The flow:

1. Tool calls `interrupt(payload)` — graph suspends; `run_id` is stored in the checkpoint
2. Backend emits SSE `{"type": "interrupt", "run_id": "...", "kind": "...", ...}`
3. Frontend renders the appropriate interactive card (save dialog, conflict card, profile review, etc.)
4. User makes a choice; frontend POSTs to `/api/chat/resume` with `{run_id, choice, note}`
5. `stream_resume_response()` calls `graph.astream(Command(resume={...}))` — graph continues from the interrupt point
6. Tool receives the decision, executes the write, and returns; agent produces the final response

### Agent tools

Thirteen tools are registered with the LangGraph agent. Seven are domain tools (read-only, stateless, or direct writes); six are HITL tools that trigger an `interrupt()` — pausing the graph so the user can confirm before any write.

#### Domain tools

| Tool | Purpose |
|---|---|
| `kb_search` | Agentic RAG pipeline — 7-node LangGraph graph inside the tool boundary |
| `conflict_checker` | Deterministic lookup against the ingredient conflict matrix |
| `routine_sequencer` | Orders ingredients by correct application step |
| `skin_type_advisor_tool` | Classifies skin type from KB evidence and saves it to the profile (enum-constrained) |
| `introduction_scheduler_tool` | Builds a gradual schedule for introducing strong actives |
| `update_skin_concerns_tool` | Saves the skin concerns list directly; no interrupt needed |
| `spf_recommender` | Recommends SPF products suitable for the user's profile |

#### HITL tools (each calls `interrupt()` before writing)

| Tool | Interrupt kind | What it does |
|---|---|---|
| `save_routine_tool` | `routine_diff` | Shows a preview card; user can save, overwrite, or cancel |
| `update_beard_style_tool` | `beard_style_select` | Shows a 3-option card; result is saved to profile |
| `update_location_tool` | `location_input` | Shows a text-field card; location saved to profile |
| `add_medical_flag_tool` | `medical_flag_confirm` | Asks user to confirm before adding a diagnosed condition |
| `finalize_onboarding_tool` | `onboarding_review` | Shows a full profile review card; confirms onboarding complete |
| `propose_conflict_resolution_tool` | `conflict_resolution` | Shows options to remove one conflicting ingredient from all routines |

The audit logger (`derma6.audit`) records every tool call with `user_id`, tool name, and a sanitised args summary before the tool executes.

---

## Agentic RAG Pipeline

`kb_search` is backed by a 7-node LangGraph `StateGraph` that runs inside the tool boundary — the outer ReAct agent, FastAPI layer, and API contract are untouched.

```
query_decompose → hybrid_retrieve → rerank → crag_grade
                                                 ├─ ≥ threshold ──────────────────► generate
                                                 └─ < threshold → local_retry
                                                                     ├─ ≥ threshold ► generate
                                                                     └─ < threshold → external_fallback → generate
```

| Node | What it does |
|---|---|
| `query_decompose` | LLM splits complex questions into focused sub-queries (falls back to original on failure) |
| `hybrid_retrieve` | Per sub-query: HyDE dense (ChromaDB) + BM25 sparse in parallel, merged via Reciprocal Rank Fusion |
| `rerank` | Cross-encoder (`ms-marco-MiniLM-L-6-v2`) scores all candidates against the **original** query, plus a small boost for chunks tagged with an active the query names |
| `crag_grade` | LLM grades each reranked doc as relevant/not; computes aggregate score |
| `local_retry` | LLM reformulates query → re-retrieves → re-grades; keeps local KB as authoritative source |
| `external_fallback` | Web search (Tavily → DuckDuckGo) or LLM-only; last resort only (default: `llm-only`) |
| `generate` | Formats context string in `kb_search`-compatible format + appends `__RAG_PIPELINE_META__` block |

All parameters are configurable via environment variables with safe defaults — see [Agentic RAG](docs/wiki/Agentic-RAG.md) in the wiki for the full reference.

---

## Cross-Session Memory

Every chat turn ends with a fire-and-forget background task that extracts freeform, memory-worthy facts ("prefers fragrance-free products", "travels for work often") via schema-enforced LLM extraction, embeds them, and skips storage if a near-duplicate already exists (cosine similarity ≥ `MEMORY_SIMILARITY_THRESHOLD`, default 0.92). On later turns, the incoming message is embedded and the top-K nearest facts for that user (`MEMORY_RETRIEVAL_TOP_K`, default 5) are pulled into the system prompt.

- **Fail-open by design** — a failure to extract or retrieve never blocks or fails the chat response; the turn just proceeds with no facts
- **Denylisted against profile fields** — facts that overlap with data already tracked structurally (skin type, concerns, beard style, ...) are filtered out before storage, so memory only captures what the structured profile doesn't
- **Per-user isolation** — every query filters by `user_id` first; there is no cross-user retrieval path

See [docs/wiki/Memory.md](docs/wiki/Memory.md) for the storage schema, dedup logic, and the `pgvector` dimension caveat that rules out an ANN index at the current embedding width.

---

## Product Finder

A manually-triggered lookup that surfaces real, buyable listings — retail (**new**) and secondhand (**used**) — next to a product the assistant recommends. Clicking **Find this product** on a routine step opens an anchored popover that shows a staged search animation, then fills in place with a mixed grid: price (when found), source, thumbnail, and a link out. It is **not** an agent tool — it's a standalone, auth-gated route (`GET /api/products/find`) the frontend calls directly, so the LangGraph agent, chat contract, and RAG pipeline are untouched.

Because *where to buy* depends on *where you are*, an LLM-driven **source-discovery** step runs first — it discovers the right retailers, Vinted locale, and secondhand marketplaces for the user's location, validates and web-search-verifies each candidate domain, and caches the result (7-day TTL). The lookup then fans out across those sources concurrently:

```
GET /api/products/find?name&brand&source&stream=true
    │
    ├─ product_cache hit (10-min TTL) ───────────────────────► result
    └─ miss → source discovery (LLM + verify, per location) → fan out concurrently:
              ├─ Vinted                (vinted-api-wrapper)
              ├─ retail / new          (domain-scoped Tavily/DDG search + price & thumbnail enrichment)
              ├─ secondhand marketplaces (domain-scoped search)
              └─ Kleinanzeigen         (HTML scrape — Germany only)
                  │
                  └─ relevance filter (batched LLM, ≤2 calls/category) → rank → SSE result
```

- **Never-fail sources** — any source that times out or errors degrades to empty for *that* source; the others still return. `retail_ok` / `secondhand_ok` in the response are `False` only on failure, never on a legitimate zero-result search.
- **Domain-scoped search** — one query per discovered domain (Tavily `include_domains` / DuckDuckGo `site:`), interleaved round-robin so no single retailer dominates.
- **Best-effort enrichment** — retail listings without a snippet price/thumbnail get an independently-timed-out page fetch (og:image / schema.org JSON-LD / Amazon-specific), guarded so a slow page never fails the lookup.
- **Streaming** — `stream=true` emits SSE stage events (`discovery`, `domain_check`, `relevance_filter`, `thumbnail_enrichment`, `price_enrichment`) that drive the rotating loading phrase; the frontend fires one request per source in parallel so each card populates as its source finishes.

See [docs/wiki/Product-Finder.md](docs/wiki/Product-Finder.md) for the full reference — discovery algorithm, per-source mechanics, enrichment tiers, caching, and every config knob.

---

## Evaluation

[deepeval](https://github.com/confident-ai/deepeval) suite — 28 tests across 7 categories covering all six agent tools and the agentic RAG pipeline. Results are visible in Admin → Eval Dashboard (grouped by category, with per-metric kind tagging).

| Evaluator type | Used for | LLM call? |
| --- | --- | --- |
| GEval (LLM-as-judge) | SPF, conflict, skin type, intro scheduler | yes — `gpt-4o-mini` |
| Programmatic | Routine sequencer order + unclassifiable items | no |
| Contextual RAG | KB retrieval relevancy, precision, recall | yes |

```bash
# Refresh actual_output from live tool runs (before eval)
uv run python eval/capture_outputs.py --update-golden

# Run via pytest
uv run pytest --run-eval eval/test_deepeval_evaluations.py -v

# Or trigger from the Admin UI: Admin → Eval Dashboard → Run Eval Suite
```

See [docs/wiki/Evaluation.md](docs/wiki/Evaluation.md) for the full reference — golden dataset schema, capture script usage, evaluator types, known failing tests, and how to add new cases.

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js 20+ with npm
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)

### Backend

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in OPENROUTER_API_KEY, DATABASE_URL, and SUPABASE_URL
# (create a Supabase project first; SUPABASE_JWT_SECRET is only needed as an
#  HS256 fallback — the live JWKS/ES256 path needs no extra config beyond the URL)
# Optional: TAVILY_API_KEY improves web search (RAG fallback + product finder);
#  both degrade to DuckDuckGo when it's unset.

# 3. Apply database migrations (Postgres via Supabase)
uv run alembic upgrade head

# 4. Build the knowledge base (first run only)
uv run python scripts/index_kb.py

# 5. Start the API server
uv run uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://localhost:5173`. It also needs a `frontend/.env` with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` (same Supabase project as the backend).

---

## Running Tests

```bash
# Python
uv run pytest

# Frontend type-check
cd frontend && npx tsc --noEmit
```

---

## CI/CD

Two GitHub Actions workflows handle quality gates and deployment.

### CI (`ci.yml`)

Runs on every push to any branch. Two parallel jobs:

| Job | Steps |
|---|---|
| **frontend** | `npm run lint` (ESLint) → `npm run build` (TypeScript + Vite) |
| **backend** | `uv sync --group dev` → `pytest --cov` (fails if coverage drops below 90%) |

### Deploy (`deploy.yml`)

1. Build frontend (`npm run build`, with `VITE_SUPABASE_URL`/`VITE_SUPABASE_PUBLISHABLE_KEY` injected from repo secrets — Vite bakes `VITE_*` vars in at build time, so the runner needs them even though the app itself never sees `.env`)
2. `rsync --delete` backend to a Hetzner VPS (excludes `.env`, `data/`, `logs/`, dev/tooling directories, `frontend/`)
3. `rsync` `frontend/dist/` → the web root
4. SSH in and run `docker compose up --build -d`

Hardening on the deploy path:
- Every third-party GitHub Action (`checkout`, `setup-node`, `setup-python`, `setup-uv`) is pinned to a commit SHA, not a mutable tag
- The SSH host key is pinned and verified out-of-band rather than trust-on-first-use (`ssh-keyscan` against the runner would be spoofable)
- The container in `docker-compose.yml` runs as a dedicated non-root user, not root
- Reverse proxy is Caddy (auto-TLS), fronting the FastAPI backend and serving the built SPA with client-side-routing fallback

Use `[skip ci]` in the commit message to bypass both workflows.

---

## Design Decisions

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-explicit-stategraph-over-create-react-agent.md) | Explicit `StateGraph` over `create_react_agent` — required for planned HITL, conditional routing, and multi-agent topology |
| [0002](docs/adr/0002-sse-over-websockets.md) | SSE over WebSockets for streaming — correct for server-push MVP; WebSockets is the v2 path when bidirectional HITL signals arrive |
| [0003](docs/adr/0003-conflict-checker-uses-json-lookup-not-rag.md) | Conflict checker uses a JSON lookup table, not vector search — conflicts are a finite enumerable set; deterministic lookup avoids synonym mismatches and chunk boundary effects |

---

## Roadmap

- Conditional routing / multi-agent graph topology
- WebSockets upgrade for bidirectional mid-stream signals (would also unlock true multi-tab HITL)
- Persistent rate limiter (current window is in-memory and resets on restart)
- ANN index for memory-fact retrieval once per-user fact counts outgrow an unindexed scan (`pgvector`'s HNSW/ivfflat cap out at 2000 dims below the current 4096-dim embeddings — see [docs/wiki/Memory.md](docs/wiki/Memory.md))

---

## Wiki

- [Architecture deep-dive](docs/wiki/Architecture.md)
- [Agentic RAG Pipeline](docs/wiki/Agentic-RAG.md)
- [Product Finder](docs/wiki/Product-Finder.md)
- [Cross-Session Memory](docs/wiki/Memory.md)
- [Security](docs/wiki/Security.md)
- [Knowledge Base Maintenance](docs/wiki/Knowledge-Base-Maintenance.md)
- [API Reference](docs/wiki/API-Reference.md)
- [Evaluation](docs/wiki/Evaluation.md)

---

<sub>Derma6 v3 · Built with Claude Code · Powered by OpenRouter</sub>
