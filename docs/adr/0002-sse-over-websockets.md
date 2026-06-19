# ADR-0002: SSE over WebSockets for streaming

**Status:** Accepted  
**Date:** 2026-06-17

## Context

Token-by-token streaming requires a persistent server→client channel. Two options: Server-Sent Events (SSE) or WebSockets.

## Decision

Use SSE (`StreamingResponse`, `text/event-stream`) for the `/chat/stream` and `/analysis/skin` endpoints.

## Rationale

SSE is the correct fit for the current MVP:

- **Unidirectional** — the server pushes tokens; the client never needs to send mid-stream signals
- **HTTP native** — works through proxies, CDNs, and standard HTTP/2 multiplexing without upgrade negotiation
- **FastAPI native** — `StreamingResponse` with an async generator is idiomatic; no extra library
- **`BaseHTTPMiddleware` compatible** — the JWT middleware is safe for SSE because it never buffers the response body; it only reads the request headers

WebSockets become the correct choice when HITL arrives (the client needs to send a "continue" or "modify" signal mid-stream). That upgrade is isolated to the streaming transport layer and does not affect the LangGraph graph or the rest of the API.

## Consequences

- Streaming works correctly today with no extra dependencies
- HITL will require a WebSocket endpoint as a companion or replacement — noted in the v2 backlog
