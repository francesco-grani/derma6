# Derma6 v2 — Backlog

## Delivered (v2)

- [x] Migrate from Streamlit monolith (AE.2.5) to decoupled FastAPI + React architecture
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

## Pending

- [ ] HITL interrupts — requires `AsyncSqliteSaver`, `thread_id` on graph, resume endpoint on API, frontend pause/resume UI
- [ ] Conditional routing / multi-agent graph topology
- [ ] WebSockets upgrade — needed for bidirectional mid-stream signals once HITL lands (SSE is one-way)
- [ ] Persistent rate limiter — current in-memory limiter resets on restart
- [ ] Deployment — target TBD (Cloudflare Pages + Railway likely); when confirmed: lock CORS origin, add `VITE_API_URL` build env var
