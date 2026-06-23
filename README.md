<p align="center">
  <img src="frontend/src/assets/hero.png" width="180" alt="Derma6"/>
</p>

<p align="center">
  <strong>Derma6 v2</strong> — AI skincare assistant for male beginners.<br/>
  Diagnose your skin type, build a personalised routine, catch ingredient conflicts, and schedule active introductions.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+"/>
  <img src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React 19"/>
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/ChromaDB-vector%20store-F97316" alt="ChromaDB"/>
  <img src="https://img.shields.io/badge/uv-package%20manager-7C3AED" alt="uv"/>
</p>

---

## What changed from v1 (AE.2.5)

Derma6 v2 replaces the Streamlit monolith with a decoupled three-layer architecture. Same skincare domain, same 10 core behaviours — production-grade stack:

| | v1 (AE.2.5) | v2 (AE.3.6) |
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
| **LLM** | OpenRouter — `openai/gpt-4o-mini` (agent), `openai/gpt-4o` (vision) |
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

### Agent tools

Six domain tools are registered with the LangGraph agent:

| Tool | Purpose |
|---|---|
| `kb_search` | Semantic search over the 20-document knowledge base |
| `conflict_checker` | Deterministic lookup against the ingredient conflict matrix |
| `routine_sequencer` | Orders ingredients by correct application step |
| `skin_type_advisor` | Classifies skin type from KB evidence and conversation |
| `introduction_scheduler` | Builds a gradual schedule for introducing strong actives |
| `spf_recommender` | Recommends SPF products suitable for the user's profile |

Profile-mutating operations (save routine, update concerns, medical flags) were promoted to API endpoints in v2 rather than remaining agent tools — reducing LLM tool-call surface and making writes auditable at the HTTP layer.

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

RAGAs evaluation against a 15-question golden dataset (`eval/eval_dataset.json`). Inherited from v1 and updated for the v2 retrieval pipeline.

```bash
uv run python scripts/index_kb.py   # build / refresh ChromaDB index
uv run python scripts/eval_rag.py   # run RAGAs evaluation
```

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

<sub>Derma6 v2 — Turing College AI Engineering Sprint 3 (AE.3.6) · Built with Claude Code · Powered by OpenRouter</sub>
