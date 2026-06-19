# Architecture

Derma6 v2 is a three-layer system: a React SPA, a FastAPI backend, and a LangGraph agent. Each layer is fully decoupled — the frontend knows nothing about LangGraph, and the agent knows nothing about HTTP.

---

## Request lifecycle (chat turn)

```
1. User types a message in ChatPage.tsx
2. useStreamChat hook POSTs to /chat/stream with { message, session_id }
3. JWTAuthMiddleware validates the Bearer token; username written to request.state
4. chat.py router calls build_stream(username, session_id, message)
5. build_stream() loads chat history from SQLite, builds the state, runs the graph
6. LangGraph StateGraph: llm_node → (tool_node →)* llm_node → END
7. Each token is yielded as an SSE event: data: {"token": "..."}
8. Tool calls yield: data: {"tool_call": {...}}
9. Final cost yields: data: {"cost": {...}}
10. Frontend appends tokens to the assistant bubble in real time
```

### SSE event types

| Event field | When emitted | Shape |
|---|---|---|
| `token` | Every LLM output token | `{"token": "word"}` |
| `tool_call` | When a tool fires | `{"tool_call": {"name": "...", "result": "..."}}` |
| `cost` | End of turn | `{"cost": {"input_tokens": N, "output_tokens": N, "total_usd": N}}` |
| `error` | On exception | `{"error": "message"}` |

---

## LangGraph graph structure

```
START
  │
  ▼
llm_node  ──(no tool calls)──►  END
  │
  │ (tool calls present)
  ▼
tool_node
  │
  ▼
llm_node  ──── (loop until no tool calls) ────►  END
```

The graph uses `tools_condition` from `langgraph.prebuilt` to decide whether to route to `tool_node` or `END`. This is the standard ReAct loop, but implemented as an explicit `StateGraph` rather than `create_react_agent`. See [ADR-0001](../adr/0001-explicit-stategraph-over-create-react-agent.md).

### State

The graph state is `MessagesState` — a list of `BaseMessage` objects. Each turn:

1. `get_history()` loads prior messages from SQLite and prepends them.
2. The new `HumanMessage` is appended.
3. The graph runs; all messages (including tool calls/results) are produced.
4. After streaming, the assistant's final `AIMessage` is persisted back to SQLite.

### Tool closure pattern

Tools are defined as module-level functions but receive per-user dependencies via closure at agent construction time:

```python
profile_store = ProfileStore(username)
session_store = SessionStore(username)

@lc_tool
def kb_search(query: str) -> str:
    # profile_store is captured from the outer scope
    ...
```

This avoids a global registry and makes per-user data isolation trivial.

---

## Database schema

All tables live in a single SQLite file (default `./data/skincare.db`).

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `username` | TEXT UNIQUE | |
| `hashed_password` | TEXT | bcrypt |
| `role` | TEXT | `"user"` or `"admin"` |
| `created_at` | DATETIME | |

### `sessions`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `username` | TEXT | FK → users |
| `session_id` | TEXT UNIQUE | UUID |
| `title` | TEXT | auto-generated from first message |
| `created_at` | DATETIME | |
| `updated_at` | DATETIME | |

### `chat_messages`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `session_id` | TEXT | FK → sessions |
| `role` | TEXT | `"user"` / `"assistant"` |
| `content` | TEXT | |
| `created_at` | DATETIME | |

### `skin_profiles`
Stores one row per user. Serialises lists/dicts as JSON columns (routines, concerns, medical flags, introduction plans).

---

## Auth flow

```
POST /auth/register  →  hash password, insert user, return JWT
POST /auth/login     →  verify password, return JWT
```

Every subsequent request must include `Authorization: Bearer <token>`.

`JWTAuthMiddleware` (a `BaseHTTPMiddleware`) runs before every route except `/auth/*`, `/health`, and `/docs`. On success it writes `request.state.username`. Route handlers use `Depends(get_current_user)` to read it.

The frontend stores the token in `localStorage`. On any 401 response the `api.ts` axios interceptor clears the token and redirects to `/login`.

---

## Vector store

ChromaDB persists embeddings to `./data/chroma` (configurable via `CHROMA_PERSIST_DIR`).

- **Documents:** 20 markdown files in `knowledge_base/`
- **Splitter:** `RecursiveCharacterTextSplitter` — 1000-char chunks, 150-char overlap
- **Embeddings:** OpenRouter `qwen/qwen3-embedding-8b` (served via the same API key)
- **Retrieval:** top-4 chunks by cosine similarity, filtered at `RETRIEVAL_MIN_SCORE=0.3`

The conflict table (`knowledge_base/conflict_table.json`) is loaded deterministically at startup and never goes through vector search. See [ADR-0003](../adr/0003-conflict-checker-uses-json-lookup-not-rag.md).

---

## Skin analysis (vision)

`POST /analysis/skin` accepts a multipart upload (image file). The image is base64-encoded and sent to `openai/gpt-4o` via OpenRouter with a structured prompt asking for skin type, visible concerns, and product recommendations. The response is streamed as SSE in the same format as the chat endpoint.

The vision call is intentionally separate from the LangGraph graph — it is a one-shot analysis, not an agentic loop.

---

## Logging

Structured JSON logging via a custom `JsonFormatter`. Three log destinations:

| Logger | Sink | Content |
|---|---|---|
| `uvicorn.access` | stdout | HTTP access log |
| `derma6.*` | `./logs/app.log` | Application + agent logs |
| `derma6.audit` | `./logs/audit.log` | Tool invocations (username, tool name, input summary) |

LangSmith tracing is activated automatically when `LANGSMITH_API_KEY` is non-empty. Every `build_stream()` call becomes a traced run under the `derma6` project.

---

## Frontend structure

```
frontend/src/
├── pages/
│   ├── LoginPage.tsx       login / register form
│   ├── ChatPage.tsx        main chat interface + session selector
│   ├── ProfilePage.tsx     skin profile viewer
│   ├── RoutinesPage.tsx    saved AM/PM routines
│   ├── SkinAnalysisPage.tsx  photo upload + vision analysis
│   └── AdminPage.tsx       admin user management
├── components/
│   ├── layout/Sidebar.tsx  nav + session list
│   └── ui/                 shadcn/ui primitives
├── hooks/
│   ├── useStreamChat.ts    SSE streaming + message state
│   └── useSessions.ts      session CRUD via TanStack Query
└── lib/
    ├── api.ts              axios instance + auth interceptor
    ├── auth.tsx            AuthContext (token + username)
    └── sessionContext.tsx  active session state
```

TanStack Router is configured in `main.tsx`. All routes under the `protectedRoute` parent require a valid JWT token; unauthenticated requests are redirected to `/login`.
