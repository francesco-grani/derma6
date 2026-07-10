<p align="center">
  <img src="frontend/src/assets/hero.png" width="140" alt="Derma6"/>
</p>

<p align="center">
  <strong>Derma6 v2</strong> — AI skincare assistant for male beginners.
  Diagnose your skin type · Build a personalised routine · Catch ingredient conflicts · Schedule active introductions.
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

## What changed from v1

Derma6 v2 replaces the Streamlit monolith with a decoupled three-layer architecture. Same skincare domain, same 10 core behaviours — production-grade stack:

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

---

## Features

| | Feature | Description |
|---|---|---|
| 💬 | **Chat** | Streaming conversation with the skincare agent, organised into named sessions |
| 🔬 | **Skin analysis** | Upload a photo — a vision LLM (GPT-4o) analyses your skin and feeds findings into the agent |
| 🧴 | **Routine builder** | Generates AM/PM routines sequenced by application order, conflict-aware |
| ⚠️ | **Ingredient conflict checker** | Cross-references products against a compatibility matrix (e.g. Retinol + Salicylic Acid) |
| 📅 | **Active scheduling** | Gradual introduction plan for strong actives to minimise irritation |
| 👤 | **Skin profile** | Persistent profile — skin type, concerns, medical flags, shaving routine |
| 📚 | **Focused KB** | 20 documents on skincare actives: Paula's Choice, INCI Decoder, PubMed, r/SkincareAddiction |
| 📤 | **Export** | Download full skincare plan (profile + routines + chat) as HTML or PDF |
| 🔐 | **Auth** | JWT login — each user gets their own isolated data |
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
| **Embeddings** | OpenRouter — `qwen/qwen3-embedding-8b` |
| **Vector store** | ChromaDB |
| **Relational store** | SQLite + SQLAlchemy |
| **Auth** | JWT (`python-jose`), bcrypt passwords |
| **Observability** | LangSmith (optional), structured JSON logging, Sentry (optional) |
| **Package manager** | uv (Python), npm (frontend) |

---

## Architecture

```
Browser (React)
    │  HTTP / SSE
    ▼
FastAPI  ──►  JWTAuthMiddleware
    ├── POST /auth/login|register
    ├── POST /chat/stream    ──►  SSE token stream
    ├── GET  /profile/me
    ├── GET  /routines/me
    ├── POST /analysis/skin
    ├── GET  /sessions/me
    └── GET  /export/pdf|html
    │
    ▼
LangGraph StateGraph (explicit ReAct loop)
    ├── llm_node   ──►  OpenRouter (gpt-4o-mini)
    └── tool_node  ──►  6 domain tools
    │
    ├── 6 Tools ───────────────────────────────────────────────
    │   ├── kb_search             ChromaDB semantic search
    │   ├── conflict_checker      JSON conflict matrix (deterministic)
    │   ├── routine_sequencer     Application-order sorting
    │   ├── skin_type_advisor     Type classification from KB + chat
    │   ├── introduction_scheduler  Gradual actives plan
    │   └── spf_recommender       SPF matching to skin profile
    │
    ├── SQLite ─────────────────────────────────────────────────
    │   ├── users          (hashed password, role)
    │   ├── chat_messages  (per session)
    │   ├── sessions       (named conversation threads)
    │   ├── skin_profiles  (type, concerns, flags, routines)
    │   └── rate_limits    (per-user in-memory window)
    │
    └── ChromaDB ───────────────────────────────────────────────
        └── 20-doc KB (1000-char chunks, 150-char overlap)
```

The agent runs as an explicit `StateGraph` (not `create_react_agent`). This was a deliberate choice over the prebuilt helper — see [ADR-0001](docs/adr/0001-explicit-stategraph-over-create-react-agent.md).

### Security

- Input capped at 2000 characters (`MAX_MESSAGE_CHARS`)
- Prompt injection defence: `SECURITY` instruction placed last in the system prompt (sandwich pattern)
- JWT tokens expire in 24 h; auto-logout on 401 in the frontend
- Per-user rate limiting: 10 requests / 60 s (in-memory; resets on restart — see v2 backlog)
- Medical flags trigger a `⚠️ Consult a dermatologist` notice only on specific recommendations
- `BaseHTTPMiddleware` safe for SSE because it never reads the response body

### Content filter

`backend/middleware/content_filter.py` runs as a FastAPI `Depends` before the agent on every `/api/chat` request:

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

Thirteen tools are registered with the LangGraph agent. Six are domain tools (read-only or stateless); seven are HITL tools that trigger an `interrupt()` — pausing the graph so the user can confirm before any write.

#### Domain tools

| Tool | Purpose |
|---|---|
| `kb_search` | Agentic RAG pipeline — 7-node LangGraph graph inside the tool boundary |
| `conflict_checker` | Deterministic lookup against the ingredient conflict matrix |
| `routine_sequencer` | Orders ingredients by correct application step |
| `skin_type_advisor_tool` | Classifies skin type from KB evidence and saves it to the profile |
| `introduction_scheduler_tool` | Builds a gradual schedule for introducing strong actives |
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
| `update_skin_concerns_tool` | direct write | Saves skin concerns list; no interrupt needed |

The audit logger (`derma6.audit`) records every tool call with username, tool name, and a sanitised args summary before the tool executes.

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
| `rerank` | Cross-encoder (`ms-marco-MiniLM-L-6-v2`) scores all candidates against the **original** query |
| `crag_grade` | LLM grades each reranked doc as relevant/not; computes aggregate score |
| `local_retry` | LLM reformulates query → re-retrieves → re-grades; keeps local KB as authoritative source |
| `external_fallback` | Web search (Tavily → DuckDuckGo) or LLM-only; last resort only (default: `llm-only`) |
| `generate` | Formats context string in `kb_search`-compatible format + appends `__RAG_PIPELINE_META__` block |

All parameters are configurable via environment variables with safe defaults — see [Agentic RAG](docs/wiki/Agentic-RAG.md) in the wiki for the full reference.

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
# Edit .env — fill in OPENROUTER_API_KEY and SECRET_KEY (see .env.example for instructions)

# 3. Build the knowledge base (first run only)
uv run python scripts/index_kb.py

# 4. Start the API server
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

The app will be available at `http://localhost:5173`.

### Generating a SECRET_KEY

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into `.env` as `SECRET_KEY`.

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

Runs on every push to `main`:

1. Build frontend (`npm run build`)
2. `rsync` backend to Hetzner VPS (excludes `.env`, `data/`, `.venv/`)
3. `rsync` `frontend/dist/` → `/app/www/`
4. SSH in and run `docker compose up --build -d`

Use `[skip ci]` in the commit message to bypass both workflows.

---

## Design Decisions

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-explicit-stategraph-over-create-react-agent.md) | Explicit `StateGraph` over `create_react_agent` — required for planned HITL, conditional routing, and multi-agent topology |
| [0002](docs/adr/0002-sse-over-websockets.md) | SSE over WebSockets for streaming — correct for server-push MVP; WebSockets is the v2 path when bidirectional HITL signals arrive |
| [0003](docs/adr/0003-conflict-checker-uses-json-lookup-not-rag.md) | Conflict checker uses a JSON lookup table, not vector search — conflicts are a finite enumerable set; deterministic lookup avoids synonym mismatches and chunk boundary effects |

---

## v2 Backlog

- HITL interrupts (requires `AsyncSqliteSaver`, `thread_id`, resume endpoint)
- Conditional routing / multi-agent graph topology
- WebSockets upgrade for bidirectional mid-stream signals
- Persistent rate limiter (current in-memory window resets on restart)
- Deployment (Cloudflare Pages + Railway — CORS origin and `VITE_API_URL` to be locked)

---

## Wiki

- [Architecture deep-dive](docs/wiki/Architecture.md)
- [Agentic RAG Pipeline](docs/wiki/Agentic-RAG.md)
- [Knowledge Base Maintenance](docs/wiki/Knowledge-Base-Maintenance.md)
- [API Reference](docs/wiki/API-Reference.md)

---

<sub>Derma6 v2 · Built with Claude Code · Powered by OpenRouter</sub>
